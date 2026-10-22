#!/usr/bin/env python3
"""meter.py - per-feature token and cost metering. The take-home artifact.

Recipe 01 asserts you cannot optimise what you have not attributed. This is the
attribution: a context manager that records tokens, cost, latency and outcome
for every call, writes one row per call to CSV, and reports the distribution --
not the mean, which recipe 01 showed is 3x the median on a realistic mix.

    from meter import Meter
    meter = Meter("spend.csv")

    with meter.call(feature="ticket_classifier", model="small") as c:
        resp = your_provider_call(...)
        c.record(in_tok=resp.usage.input_tokens,
                 out_tok=resp.usage.output_tokens,
                 cached_in_tok=resp.usage.cache_read_input_tokens,
                 outcome="solved")

    meter.report()

WHY cached_in_tok IS A SEPARATE FIELD: a cached input token is billed at 0.1x,
so a meter that sums raw input tokens overstates spend on any cached workload
and makes caching look like it did nothing. Keep them apart at the point of
measurement -- you cannot reconstruct the split later.

WHY outcome IS REQUIRED: cost per request is the wrong denominator. A truncated
or failed call costs full price and solves nothing (recipe 10), so the number
that matters is cost per SOLVED call. Pass "solved" / "failed" / "truncated"
and the report gives you both.

    python3 recipes/tools/meter.py --demo
"""
import argparse, csv, pathlib, statistics, sys, time
from contextlib import contextmanager

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "recipes"))
import prices as P
from _harness import money

FIELDS = ["ts", "feature", "model", "in_tok", "cached_in_tok", "out_tok",
          "batch", "outcome", "ms", "usd"]


class _Call:
    def __init__(self, feature, model, batch):
        self.feature, self.model, self.batch = feature, model, batch
        self.in_tok = self.cached_in_tok = self.out_tok = 0
        self.outcome = "unknown"

    def record(self, in_tok=0, out_tok=0, cached_in_tok=0, outcome="solved"):
        self.in_tok, self.out_tok = in_tok, out_tok
        self.cached_in_tok, self.outcome = cached_in_tok, outcome

    @property
    def usd(self):
        # cached input is billed at CACHE_READ; uncached input at full rate
        uncached = max(0, self.in_tok - self.cached_in_tok)
        return (P.cost(uncached, self.out_tok, self.model, batch=self.batch)
                + P.cost(self.cached_in_tok * P.CACHE_READ, 0, self.model, batch=self.batch))


class Meter:
    def __init__(self, path=None):
        self.path = pathlib.Path(path) if path else None
        self.rows = []
        if self.path and not self.path.exists():
            with self.path.open("w", newline="") as f:
                csv.DictWriter(f, FIELDS).writeheader()

    @contextmanager
    def call(self, feature, model="big", batch=False):
        c, t0 = _Call(feature, model, batch), time.perf_counter()
        try:
            yield c
        finally:
            row = dict(ts=f"{time.time():.3f}", feature=c.feature, model=c.model,
                       in_tok=c.in_tok, cached_in_tok=c.cached_in_tok, out_tok=c.out_tok,
                       batch=int(c.batch), outcome=c.outcome,
                       ms=round((time.perf_counter() - t0) * 1000, 1),
                       usd=round(c.usd, 8))
            self.rows.append(row)
            if self.path:
                with self.path.open("a", newline="") as f:
                    csv.DictWriter(f, FIELDS).writerow(row)

    # --- reporting -----------------------------------------------------------
    def report(self, out=print):
        if not self.rows:
            out("  no calls recorded")
            return
        spend = [r["usd"] for r in self.rows]
        spend_sorted = sorted(spend)
        total = sum(spend)

        def q(p):
            return spend_sorted[min(len(spend_sorted) - 1, int(len(spend_sorted) * p))]

        out("")
        out("  PER FEATURE")
        out(f"  {'feature':24} {'calls':>7} {'solved':>7} {'tokens':>12} "
            f"{'spend':>12} {'$/solved':>11} {'share':>7}")
        feats = sorted({r["feature"] for r in self.rows})
        for feat in feats:
            rs = [r for r in self.rows if r["feature"] == feat]
            solved = [r for r in rs if r["outcome"] == "solved"]
            tok = sum(r["in_tok"] + r["out_tok"] for r in rs)
            s = sum(r["usd"] for r in rs)
            per_solved = s / len(solved) if solved else float("inf")
            out(f"  {feat:24} {len(rs):>7,} {len(solved):>7,} {tok:>12,} "
                f"{money(s):>12} {money(per_solved) if solved else 'n/a':>11} "
                f"{s/total*100:>6.1f}%")
        out("")
        out("  DISTRIBUTION  (the mean is not the number to budget on)")
        out(f"  median {money(statistics.median(spend))}   mean {money(statistics.mean(spend))}"
            f"   P95 {money(q(0.95))}   P99 {money(q(0.99))}   max {money(spend_sorted[-1])}")
        out(f"  mean / median = {statistics.mean(spend)/max(statistics.median(spend),1e-12):.1f}x"
            f"   |   top 1% of calls = {sum(spend_sorted[int(len(spend_sorted)*0.99):])/total*100:.0f}% of spend")

        wasted = sum(r["usd"] for r in self.rows if r["outcome"] != "solved")
        out("")
        out(f"  WASTE: {money(wasted)} ({wasted/total*100:.1f}%) spent on calls that "
            f"did not solve anything")
        cached = sum(r["cached_in_tok"] for r in self.rows)
        if cached:
            out(f"  CACHE: {cached:,} input tokens served at {P.CACHE_READ}x "
                f"(saved ~{money(cached/1e6*P.MODELS['big'][0]*(1-P.CACHE_READ))})")
        out(f"  TOTAL: {money(total)} across {len(self.rows):,} calls")
        out("")


def _demo():
    """A synthetic day across three features, with a realistic skew."""
    import random
    random.seed(7)       # deterministic: this is a demo, not a benchmark
    m = Meter()
    plan = [("ticket_classifier", "small", 1200, (900, 1400), (15, 40), 0.01),
            ("support_chat",      "big",    300, (3000, 14000), (200, 600), 0.04),
            ("doc_enrichment",    "small",  900, (2000, 3000), (300, 500), 0.02)]
    for feature, model, n, inr, outr, failrate in plan:
        for _ in range(n):
            with m.call(feature=feature, model=model) as c:
                it = random.randint(*inr)
                ot = random.randint(*outr)
                # the long tail: a few calls run away, which is the whole point of P99
                if random.random() < 0.01:
                    it, ot = it * 8, ot * 6
                bad = random.random() < failrate
                c.record(in_tok=it, out_tok=ot,
                         cached_in_tok=800 if feature == "support_chat" else 0,
                         outcome="truncated" if bad else "solved")
    print("=" * 78)
    print("meter.py --demo   one synthetic day, three features, 2,400 calls")
    print("=" * 78)
    m.report()
    # the reach lesson, computed rather than asserted
    chat = [r for r in m.rows if r["feature"] == "support_chat"]
    share_calls = len(chat) / len(m.rows) * 100
    share_spend = sum(r["usd"] for r in chat) / sum(r["usd"] for r in m.rows) * 100
    print(f"  REACH: support_chat is {share_calls:.0f}% of calls and {share_spend:.0f}% of spend.")
    print("  Optimise it first. A 50% cut on ticket_classifier -- the feature with")
    print("  four times the call volume -- moves the total bill by under 5%.")
    print("")
    print("  Attribution is the precondition for every other recipe: without the")
    print("  per-feature split you cannot tell which lever has REACH, and reach x")
    print("  discount is the ceiling on what any optimisation can return.")
    print("")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    if ap.parse_args().demo:
        _demo()
    else:
        print(__doc__)
