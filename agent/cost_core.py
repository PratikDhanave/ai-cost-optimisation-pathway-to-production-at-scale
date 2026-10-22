"""Model-agnostic cost control. Pure functions, standard library only.

This module knows nothing about ADK, about any SDK, or about the network. It is
the half that can be tested without a framework or an API key, which is why it
is a separate file: cost_plugin.py is thin glue over this.

MODEL-AGNOSTIC MEANS TWO THINGS, and the second is the one people miss.

  1. Rates are looked up, never hardcoded. Obvious.
  2. CACHE MECHANICS DIFFER BY PROVIDER and cannot be averaged. Several bill a
     cache write at a premium over the standard input rate; at least one bills
     the write at the standard rate and charges time-based storage instead,
     which removes the break-even entirely. A "generic" cache multiplier would
     be wrong for somebody no matter which number you picked.

So an unknown model is NOT costed at a default. It is reported as unknown, and
the caller decides. Guessing a rate produces a confident number that is wrong,
which is worse than no number at all -- the same reason tools/bill_estimate.py
errors on a missing column instead of assuming one.
"""
from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    """Rates per 1M tokens, and the cache mechanics that go with them."""
    name: str
    patterns: tuple            # fnmatch patterns against the model string
    input_per_m: float
    output_per_m: float
    cache_read: float          # multiplier on the input rate for a cache hit
    cache_write: float         # multiplier on the input rate to write the cache
    cache_min_tokens: int      # below this, nothing caches at all
    batch: float               # multiplier for the async tier, 1.0 if none
    cache_storage_billed: bool # True: time-based storage instead of a write premium
    note: str = ""


# Rates are ILLUSTRATIVE and move constantly. The MECHANICS -- the multipliers,
# the minimum, whether storage is billed -- are what this registry exists for,
# and they change far more slowly. Override rates per deployment; do not assume
# these are current.
PROVIDERS: tuple = (
    Provider(
        name="anthropic-style",
        patterns=("*claude*", "*sonnet*", "*opus*", "*haiku*"),
        input_per_m=3.00, output_per_m=15.00,
        cache_read=0.10, cache_write=1.25, cache_min_tokens=1024,
        batch=0.50, cache_storage_billed=False,
        note="cache write at a premium; no storage charge",
    ),
    Provider(
        name="openai-style",
        patterns=("gpt-*", "*o1*", "*o3*", "*o4*"),
        input_per_m=2.50, output_per_m=10.00,
        cache_read=0.10, cache_write=1.25, cache_min_tokens=1024,
        batch=0.50, cache_storage_billed=False,
        note="cache write at a premium on recent models; no storage charge",
    ),
    Provider(
        name="google-style",
        patterns=("gemini*", "*vertex*"),
        input_per_m=1.25, output_per_m=5.00,
        cache_read=0.10, cache_write=1.00, cache_min_tokens=1024,
        batch=0.50, cache_storage_billed=True,
        note="write at the STANDARD rate; cost moves into time-based storage, "
             "so there is no write premium and no break-even to clear",
    ),
)


def resolve(model: str | None):
    """The provider whose mechanics apply, or None if we do not know."""
    if not model:
        return None
    m = str(model).lower()
    for p in PROVIDERS:
        if any(fnmatch.fnmatch(m, pat) for pat in p.patterns):
            return p
    return None


# --- usage ------------------------------------------------------------------

# Field names differ by SDK and by version. Each tuple is tried in order.
_IN_KEYS = ("prompt_token_count", "input_tokens", "prompt_tokens", "input_token_count")
_OUT_KEYS = ("candidates_token_count", "output_tokens", "completion_tokens",
             "output_token_count")
_CACHED_KEYS = ("cached_content_token_count", "cache_read_input_tokens",
                "cached_tokens", "cache_read_tokens")


def _dig(obj, keys):
    for k in keys:
        v = getattr(obj, k, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return None


@dataclass(frozen=True)
class Usage:
    """What a turn billed. `cached_in` is None when the backend did not say.

    None and 0 mean different things and must not be collapsed. Zero means the
    provider told us nothing was cached. None means we do not know -- and
    treating that as zero overstates the uncached share, which is exactly the
    error that makes caching look like it did nothing.
    """
    in_tokens: int
    out_tokens: int
    cached_in: int | None = None

    @property
    def cached_known(self) -> bool:
        return self.cached_in is not None


def read_usage(usage_metadata) -> Usage | None:
    """Pull a Usage out of whatever shape the backend handed back."""
    if usage_metadata is None:
        return None
    i, o = _dig(usage_metadata, _IN_KEYS), _dig(usage_metadata, _OUT_KEYS)
    if i is None and o is None:
        return None
    return Usage(in_tokens=i or 0, out_tokens=o or 0,
                 cached_in=_dig(usage_metadata, _CACHED_KEYS))


@dataclass(frozen=True)
class Cost:
    usd: float | None
    provider: str
    reason: str = ""

    @property
    def known(self) -> bool:
        return self.usd is not None


def price(model: str | None, usage: Usage | None, *, batch: bool = False,
          rates: dict | None = None) -> Cost:
    """Cost of one turn, or an explicit unknown.

    `rates` optionally overrides {"input_per_m": x, "output_per_m": y} for a
    deployment that knows its own numbers.
    """
    if usage is None:
        return Cost(None, "unknown", "the backend reported no usage metadata")
    p = resolve(model)
    if p is None:
        return Cost(None, "unknown",
                    f"no rates registered for model {model!r}; add it to "
                    f"PROVIDERS or pass rates= rather than assuming a default")
    pin = (rates or {}).get("input_per_m", p.input_per_m)
    pout = (rates or {}).get("output_per_m", p.output_per_m)
    if batch:
        pin, pout = pin * p.batch, pout * p.batch

    cached = usage.cached_in or 0
    uncached = max(0, usage.in_tokens - cached)
    usd = (uncached / 1e6 * pin
           + cached / 1e6 * pin * p.cache_read
           + usage.out_tokens / 1e6 * pout)
    reason = "" if usage.cached_known else (
        "backend did not report cached tokens; billed as fully uncached, so "
        "this is an UPPER bound")
    return Cost(usd, p.name, reason)


def cache_is_worth_it(model: str | None, prefix_tokens: int) -> tuple[bool, str]:
    """Whether a cache marker on this prefix can pay, for THIS provider."""
    p = resolve(model)
    if p is None:
        return False, f"unknown model {model!r}: cannot say"
    if prefix_tokens < p.cache_min_tokens:
        return False, (f"prefix is {prefix_tokens:,} tokens, under "
                       f"{p.cache_min_tokens:,}: nothing caches, and you still "
                       f"pay any write premium")
    if p.cache_storage_billed:
        return True, (f"{p.name}: the write is at the standard rate, so there is "
                      f"no premium to earn back -- but storage is billed by time, "
                      f"so a cache nobody reads still costs")
    premium = p.cache_write - 1.0
    saved = 1.0 - p.cache_read
    hits = math.ceil(premium / saved) if saved > 0 else 0
    return True, (f"{p.name}: break-even at {hits} hit "
                  f"(write {p.cache_write}x, read {p.cache_read}x)")


# --- tool pruning -----------------------------------------------------------

@dataclass
class ToolTracker:
    """Which tools have gone unused, and for how long.

    Tool schemas are re-sent on every single turn whether the model calls them
    or not, so an unused tool is a fixed tax on the whole session. This records
    use and names the ones that have earned removal.
    """
    unused_after: int = 5
    _turns: int = 0
    _last_used: dict = field(default_factory=dict)
    _known: set = field(default_factory=set)

    def observe_tools(self, names) -> None:
        for n in names:
            self._known.add(n)
            self._last_used.setdefault(n, None)

    def record_call(self, name: str) -> None:
        self._known.add(name)
        self._last_used[name] = self._turns

    def end_turn(self) -> None:
        self._turns += 1

    def prunable(self) -> list:
        """Tools unused for `unused_after` turns, oldest-idle first.

        A tool that has never been called is only prunable once we have seen
        enough turns to say so -- otherwise the first turn of every session
        would prune everything before the agent had a chance to use anything.
        """
        out = []
        for n in sorted(self._known):
            last = self._last_used.get(n)
            idle = self._turns if last is None else self._turns - last
            if idle >= self.unused_after:
                out.append((n, idle))
        return [n for n, _ in sorted(out, key=lambda t: -t[1])]


# --- budget -----------------------------------------------------------------

@dataclass
class Budget:
    """Spend against a ceiling, with the two responses named separately.

    DOWNGRADE serves every request at lower quality. STOP protects the budget
    absolutely and refuses real users. They are different promises and the
    caller picks per feature, so this returns the decision rather than acting.
    """
    limit_usd: float
    downgrade_at: float = 0.80
    stop_at: float = 1.00
    spent_usd: float = 0.0
    unknown_turns: int = 0

    def add(self, cost: Cost) -> None:
        if cost.known:
            self.spent_usd += cost.usd
        else:
            # An uncosted turn is not a free turn. Counting it as zero makes a
            # budget drift silently, so it is counted separately and surfaced.
            self.unknown_turns += 1

    @property
    def fraction(self) -> float:
        return self.spent_usd / self.limit_usd if self.limit_usd else 0.0

    def decide(self) -> str:
        """'proceed' | 'downgrade' | 'stop'."""
        if self.limit_usd <= 0:
            return "proceed"
        if self.fraction >= self.stop_at:
            return "stop"
        if self.fraction >= self.downgrade_at:
            return "downgrade"
        return "proceed"

    def status(self) -> str:
        s = (f"${self.spent_usd:,.4f} of ${self.limit_usd:,.2f} "
             f"({self.fraction*100:.0f}%) -> {self.decide()}")
        if self.unknown_turns:
            s += (f"; {self.unknown_turns} turn(s) not costed and NOT counted "
                  f"towards the limit")
        return s
