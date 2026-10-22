#!/usr/bin/env python3
"""bill_estimate.py - run the levers against YOUR traffic, not mine.

Every other file here uses prompts I wrote. This one takes a CSV of your own
usage and ranks the levers by what they would actually be worth on it, because
REACH x DISCOUNT is the ceiling and reach is the half that is specific to you.
A 90%-off lever on 2% of spend loses to a 50%-off lever on everything.

    python3 recipes/tools/bill_estimate.py --schema     # the columns it needs
    python3 recipes/tools/bill_estimate.py --demo       # sample data, end to end
    python3 recipes/tools/bill_estimate.py usage.csv

IT FAILS LOUDLY RATHER THAN ASSUMING. A missing required column is an error
naming the column, never a default. An optional column that is absent downgrades
the levers that depend on it from MEASURED to NEEDS A HUMAN -- those are listed
separately and are never added into the headline, because an estimate built on
a guess about your architecture is not an estimate.
"""
import argparse, csv, pathlib, sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _harness import money
import prices as P

REQUIRED = {
    "feature":       "what the call was for, so spend can be attributed",
    "model":         "a key in prices.MODELS (big / small), or your own tier name",
    "input_tokens":  "input tokens billed for this row",
    "output_tokens": "output tokens billed for this row",
    "requests":      "how many requests this row represents (1 for a per-call export)",
}
OPTIONAL = {
    "cached_input_tokens": "input tokens already served from cache, billed at the read rate",
    "prefix_tokens":       "the STABLE prefix length, which decides whether caching can pay",
    "latency_sensitive":   "1 if a person is waiting, 0 if nobody is -- decides batchability",
    "outcome":             "solved / failed / truncated, for cost per SOLVED call",
}


class SchemaError(Exception):
    pass


def load(path):
    rows = list(csv.DictReader(pathlib.Path(path).open(newline="", encoding="utf8")))
    if not rows:
        raise SchemaError("the file has no data rows")
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        raise SchemaError(
            "missing required column(s): " + ", ".join(missing) + "\n  " +
            "\n  ".join(f"{c:22} {REQUIRED[c]}" for c in missing) +
            "\n\n  Run --schema for the full specification. No defaults are "
            "assumed:\n  guessing one of these would silently change every figure below.")
    present = [c for c in OPTIONAL if c in rows[0]]
    return rows, present


def analyse(rows, present):
    by_feature = defaultdict(lambda: dict(spend=0.0, reqs=0, in_tok=0, out_tok=0,
                                          batchable=0.0, cacheable=0.0, big=0.0,
                                          solved=0.0, wasted=0.0))
    total = 0.0
    for r in rows:
        n = float(r["requests"])
        it, ot = float(r["input_tokens"]), float(r["output_tokens"])
        cached = float(r.get("cached_input_tokens") or 0)
        model = r["model"] if r["model"] in P.MODELS else "big"
        spend = (P.cost(max(0.0, it - cached), ot, model)
                 + P.cost(cached * P.CACHE_READ, 0, model)) * n
        f = by_feature[r["feature"]]
        f["spend"] += spend; f["reqs"] += n
        if "outcome" in present:
            if str(r.get("outcome", "")).strip().lower() == "solved":
                f["solved"] += n
            else:
                f["wasted"] += spend
        f["in_tok"] += it * n; f["out_tok"] += ot * n
        if model == "big":
            f["big"] += spend
        if "latency_sensitive" in present and str(r["latency_sensitive"]).strip() in ("0", "false", "False"):
            f["batchable"] += spend
        if "prefix_tokens" in present and float(r.get("prefix_tokens") or 0) >= P.CACHE_MIN and not cached:
            f["cacheable"] += spend
        total += spend
    return by_feature, total


def report(by_feature, total, present, out=print):
    out("")
    out("  YOUR SPEND, BY FEATURE")
    out(f"  {'feature':24} {'requests':>12} {'spend':>14} {'share':>8} {'$/request':>12}")
    for name, f in sorted(by_feature.items(), key=lambda kv: -kv[1]["spend"]):
        out(f"  {name:24} {f['reqs']:>12,.0f} {money(f['spend']):>14} "
            f"{f['spend']/total*100:>7.1f}% {money(f['spend']/f['reqs']):>12}")
    out(f"  {'TOTAL':24} {sum(f['reqs'] for f in by_feature.values()):>12,.0f} "
        f"{money(total):>14}")
    out("")

    # --- levers we can measure from what you gave us -------------------------
    measured, unknown = [], []

    batch_base = sum(f["batchable"] for f in by_feature.values())
    if "latency_sensitive" in present:
        measured.append(("move async work to the batch tier", batch_base,
                         batch_base / total, P.BATCH,
                         "rows you marked latency_sensitive=0"))
    else:
        unknown.append(("batch tier", "no latency_sensitive column -- only you know which "
                                      "traffic has nobody waiting on it"))

    cache_base = sum(f["cacheable"] for f in by_feature.values())
    if "prefix_tokens" in present:
        measured.append(("cache the stable prefix", cache_base, cache_base / total,
                         1 - P.CACHE_READ,
                         f"rows with a prefix >= {P.CACHE_MIN:,} tokens and no cache hits yet"))
        short = total - cache_base
        if short > 0:
            unknown.append(("caching the rest",
                            f"{money(short)} sits on prefixes under the {P.CACHE_MIN:,}-token "
                            "minimum or already cached -- a reorder recovers nothing there"))
    else:
        unknown.append(("prompt caching", "no prefix_tokens column -- caching depends on a "
                                          "STABLE prefix clearing the minimum, which this "
                                          "data cannot show. Run tools/prefix_lint.py on the "
                                          "templates instead"))

    big = sum(f["big"] for f in by_feature.values())
    measured.append(("route the easy share to a cheaper model", big, big / total,
                     (1 - P.cost(1, 0, "small") / P.cost(1, 0, "big")) * 0.7,
                     "frontier-model spend, assuming 70% of it is routable -- CONFIRM"))

    out("  LEVERS RANKED BY REACH x DISCOUNT, on your numbers")
    out(f"  {'lever':40} {'reach':>8} {'discount':>9} {'worth':>13}")
    rows_out = sorted(measured, key=lambda m: -(m[1] * m[3]))
    for name, base, reach, disc, basis in rows_out:
        out(f"  {name:40} {reach*100:>7.1f}% {disc*100:>8.0f}% {money(base*disc):>13}")
        out(f"    basis: {basis}")
    out("")
    out(f"  Those three together are worth at most {money(sum(m[1]*m[3] for m in rows_out))} "
        f"of {money(total)}")
    out("  -- AT MOST, because they overlap. Routing a request you also batched does")
    out("  not save twice. Compose them in recipe 11's order and measure the")
    out("  marginal value of each with tools/instrument.py; do not add these up.")
    out("")
    if unknown:
        out("  WHAT THIS DATA CANNOT TELL YOU -- not estimated, not included above:")
        for name, why in unknown:
            out(f"    {name:24} {why}")
        out("")
    if "outcome" not in present:
        out("  AND THE BIGGEST GAP: no outcome column, so every figure here is cost per")
        out("  REQUEST. The number that matters is cost per SOLVED request, and a")
        out("  workload failing 8% of the time is 8% more expensive than this says.")
        out("")
    else:
        wasted = sum(f["wasted"] for f in by_feature.values())
        out("  COST PER SOLVED REQUEST -- the denominator that actually matters")
        out(f"  {'feature':24} {'$/request':>12} {'$/solved':>12} {'penalty':>9}")
        for name, f in sorted(by_feature.items(), key=lambda kv: -kv[1]["spend"]):
            per_req = f["spend"] / f["reqs"]
            if f["solved"]:
                per_solved = f["spend"] / f["solved"]
                out(f"  {name:24} {money(per_req):>12} {money(per_solved):>12} "
                    f"{(per_solved/per_req-1)*100:>+8.0f}%")
            else:
                out(f"  {name:24} {money(per_req):>12} {'never solved':>12} "
                    f"{'infinite':>9}")
        out("")
        out(f"  {money(wasted)} ({wasted/total*100:.0f}% of spend) bought nothing. That is")
        out("  the first lever, it is free, and it does not appear in the ranking above")
        out("  because fixing a failure is not an optimisation -- it is a defect.")
        out("")


def _schema():
    print("  REQUIRED COLUMNS")
    for c, d in REQUIRED.items():
        print(f"    {c:22} {d}")
    print("\n  OPTIONAL -- each one absent downgrades a lever to 'needs a human'")
    for c, d in OPTIONAL.items():
        print(f"    {c:22} {d}")
    print("\n  One row per request, or one row per group with `requests` as the count.")
    print("  Export from your provider console or your own metering (tools/meter.py")
    print("  writes this shape directly).\n")


def _demo():
    import tempfile
    sample = [
        ("ticket_classifier", "small", 900,  30,  360_000, 0,     420,  0, "solved"),
        ("support_chat",      "big",   9_800, 420, 90_000, 2_400, 2_100, 1, "solved"),
        ("doc_enrichment",    "small", 2_400, 380, 210_000, 0,    1_900, 0, "solved"),
        ("fraud_screen",      "big",   1_200, 90,  30_000, 0,     600,  1, "solved"),
        ("agent_tasks",       "big",   48_000, 3_600, 6_000, 1_800, 2_100, 1, "truncated"),
    ]
    print("=" * 78)
    print("bill_estimate.py --demo   five features, one month, levers ranked on them")
    print("=" * 78)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "usage.csv"
        with p.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["feature", "model", "input_tokens", "output_tokens", "requests",
                        "cached_input_tokens", "prefix_tokens", "latency_sensitive", "outcome"])
            w.writerows(sample)
        rows, present = load(p)
        print(f"  loaded {len(rows)} rows; optional columns present: "
              f"{', '.join(present) or 'none'}")
        by_feature, total = analyse(rows, present)
        report(by_feature, total, present)

        print("  NOW THE SAME FILE WITHOUT latency_sensitive:")
        for r in rows:
            r.pop("latency_sensitive")
        present2 = [c for c in present if c != "latency_sensitive"]
        by2, t2 = analyse(rows, present2)
        report(by2, t2, present2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.schema:
        _schema(); return 0
    if a.demo:
        _demo(); return 0
    if not a.path:
        ap.error("give a CSV path, or --schema / --demo")
    try:
        rows, present = load(a.path)
    except SchemaError as e:
        print(f"\n  CANNOT READ {a.path}\n  {e}\n")
        return 1
    print(f"  {len(rows)} rows; optional columns present: {', '.join(present) or 'none'}")
    by_feature, total = analyse(rows, present)
    report(by_feature, total, present)
    return 0


if __name__ == "__main__":
    sys.exit(main())
