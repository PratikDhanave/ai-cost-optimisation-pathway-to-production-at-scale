#!/usr/bin/env python3
"""gateway.py - the four controls, enforced at the proxy instead of in every app.

Recipes 05-13 each describe a control. Implemented per-application they are four
code changes per team, forever, and the team that skips them is the team whose
feature breaks the budget. At the gateway they are configuration, applied to
traffic nobody has to remember to route.

Four controls, in the order a request meets them:

  1. RESPONSE CACHE   identical request already answered -> serve it for $0
  2. BUDGET           spend against a daily ceiling, checked before dispatch
  3. DOWNGRADE        past a soft threshold, route to the cheaper model
  4. HARD STOP        past the ceiling, refuse rather than overspend
  then METER          every call attributed to a feature (tools/meter.py)

A RESPONSE CACHE IS NOT PROMPT CACHING, and conflating them is a real mistake.
Prompt caching (recipe 05) discounts the prefix of a call that still happens --
provider-side, always safe, 0.1x. A response cache skips the call entirely at
0.0x, and it is only safe where an identical request must produce an acceptable
identical answer. Serve a stale answer from it and the saving is free; serve a
stale answer that mattered and you have broken the product to save a cent. Short
TTLs, idempotent features only, never user-specific results.

    python3 recipes/tools/gateway.py --demo
"""
import argparse, hashlib, pathlib, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "recipes"))
import prices as P
from _harness import count, money
from meter import Meter


class Refused(Exception):
    """Raised when the hard stop fires. The caller must handle it."""


class Gateway:
    def __init__(self, backend, daily_budget, meter=None, cache_ttl=0,
                 downgrade_at=0.8, hard_stop_at=1.0, cacheable_features=()):
        self.backend = backend
        self.budget = daily_budget
        self.meter = meter or Meter()
        self.cache_ttl = cache_ttl
        self.downgrade_at, self.hard_stop_at = downgrade_at, hard_stop_at
        self.cacheable = set(cacheable_features)
        self.spend = 0.0
        self.stats = dict(served=0, cache_hits=0, downgraded=0, refused=0)
        self._cache = {}

    def _key(self, prompt, model):
        return hashlib.sha256(f"{model}\x00{prompt}".encode()).hexdigest()

    def handle(self, feature, prompt, model="big", batch=False, now=None):
        now = time.time() if now is None else now

        # 1 - response cache, only for features explicitly marked safe
        if self.cache_ttl and feature in self.cacheable:
            k = self._key(prompt, model)
            hit = self._cache.get(k)
            if hit and now - hit[0] < self.cache_ttl:
                self.stats["cache_hits"] += 1
                self.stats["served"] += 1
                return hit[1], dict(cached=True, model=model, usd=0.0)

        # 2/4 - budget and hard stop
        if self.spend >= self.budget * self.hard_stop_at:
            self.stats["refused"] += 1
            raise Refused(f"daily budget {money(self.budget)} reached")

        # 3 - downgrade
        effective = model
        if self.spend >= self.budget * self.downgrade_at and model == "big":
            effective, _ = "small", self.stats.__setitem__(
                "downgraded", self.stats["downgraded"] + 1)

        in_tok = count(prompt)
        with self.meter.call(feature=feature, model=effective, batch=batch) as c:
            text, out_tok = self.backend(prompt, effective)
            c.record(in_tok=in_tok, out_tok=out_tok, outcome="solved")
            usd = c.usd
        self.spend += usd
        self.stats["served"] += 1

        if self.cache_ttl and feature in self.cacheable:
            self._cache[self._key(prompt, model)] = (now, text)
        return text, dict(cached=False, model=effective, usd=usd)


# --- demo --------------------------------------------------------------------

def _fake_backend(prompt, model):
    """Deterministic stand-in for a provider. Returns (text, output_tokens)."""
    base = 120 if model == "small" else 180       # the big model is chattier
    spread = int(hashlib.sha256(prompt.encode()).hexdigest()[:4], 16) % 90
    return f"[{model}] answer to {prompt[:24]}...", base + spread


def _traffic(n, dup_rate=0.18):
    """A burst with a realistic share of exactly-repeated requests."""
    import random
    random.seed(11)
    pool = [f"Classify ticket {i}: the customer reports a problem with their order " * 3
            for i in range(40)]
    out = []
    for i in range(n):
        if out and random.random() < dup_rate:
            out.append(random.choice(out))         # an exact repeat
        else:
            out.append(random.choice(pool) + f" ref={i}")
    return out


def _run(label, requests, **kw):
    g = Gateway(_fake_backend, **kw)
    refused = 0
    for p in requests:
        try:
            g.handle(feature="classifier", prompt=p, model="big", now=1_000_000)
        except Refused:
            refused += 1
    return label, g, refused


def _demo():
    REQS = _traffic(4_000)
    BUDGET = 6.00      # deliberately tight, so the controls actually fire

    print("=" * 78)
    print(f"gateway.py --demo   {len(REQS):,} requests, {money(BUDGET)} daily budget")
    print("=" * 78)
    print("  All four runs see identical traffic. Only the gateway config changes.\n")

    runs = [
        _run("no controls",            REQS, daily_budget=10 ** 9),
        _run("response cache only",    REQS, daily_budget=10 ** 9,
             cache_ttl=3600, cacheable_features=("classifier",)),
        _run("cache + downgrade",      REQS, daily_budget=BUDGET,
             cache_ttl=3600, cacheable_features=("classifier",), hard_stop_at=10 ** 9),
        _run("cache + downgrade + stop", REQS, daily_budget=BUDGET,
             cache_ttl=3600, cacheable_features=("classifier",)),
    ]

    print("  TOKENS")
    print(f"  {'':26} {'answered':>9} {'cache hits':>11} {'tokens billed':>15} {'change':>9}")
    base_tok = None
    for label, g, _ in runs:
        tok = sum(r["in_tok"] + r["out_tok"] for r in g.meter.rows)
        base_tok = base_tok or tok
        ch = "" if tok == base_tok else f"{(tok/base_tok-1)*100:+6.1f}%"
        print(f"  {label:26} {g.stats['served']:>9,} {g.stats['cache_hits']:>11,} "
              f"{tok:>15,} {ch:>9}")
    print()
    print("  The cache removes whole calls, so its token saving is the honest kind.")
    print("  The downgrade reduces tokens only incidentally -- the small model happens")
    print("  to answer more briefly here -- and most of its saving is in the RATE, not")
    print("  the count. The hard stop reduces tokens by refusing people.\n")

    print("  COST")
    print(f"  {'':26} {'spend':>12} {'vs uncontrolled':>17} {'refused':>9} {'downgraded':>12}")
    base = runs[0][1].spend
    for label, g, refused in runs:
        print(f"  {label:26} {money(g.spend):>12} {(g.spend/base-1)*100:>16.1f}% "
              f"{refused:>9,} {g.stats['downgraded']:>12,}")
    print()

    uncontrolled = runs[0][1].spend
    print(f"  Uncontrolled spend is {uncontrolled/BUDGET:.1f}x the {money(BUDGET)} budget, and")
    print("  without the gateway nobody finds out until the invoice.\n")
    print("  THE TRADE, stated plainly: the response cache saves the most and carries")
    print("  the only correctness risk -- it answers a new request with an old answer.")
    print("  The downgrade degrades quality for the tail of the day and answers")
    print("  everyone. The hard stop protects the budget absolutely and refuses")
    print("  real users. Pick per feature, not once for the whole estate.\n")
    print("  Per-feature attribution from the same run:")
    runs[3][1].meter.report()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    if ap.parse_args().demo:
        _demo()
    else:
        print(__doc__)
