#!/usr/bin/env python3
"""RECIPE 16 - The long-context price cliff: one token, double the bill.

Every other lever in this set is a gradient. This one is a STEP. Past a
threshold, the higher rate applies to every token in the request -- not just the
ones past the line -- so a request that creeps one token over the edge can cost
roughly twice the request that stopped one token short.

It is the only mechanic here where the cheapest fix is to send LESS of something
you already decided you needed, and where a 1% trim can be worth 50%.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(16, "The long-context price cliff", "pricing discontinuity - a step, not a slope")

TH, OUT = P.CONTEXT_THRESHOLD, 800

note(f"""
Threshold here: {TH:,} input tokens, above which every token bills at
{P.CONTEXT_MULTIPLIER:.0f}x. Vendors differ -- some step at 200K, some at 272K,
and at least one bills a 1M window at standard rates throughout. CONFIRM YOURS;
this recipe is about the SHAPE, and the shape is a cliff.
""")

print("  COST AS CONTEXT GROWS")
print(f"  {'input tokens':>14} {'multiplier':>11} {'$/request':>12} {'vs previous':>12}")
prev = None
for n in (120_000, 180_000, 199_000, TH, 210_000, 260_000):
    c = P.cost(n, OUT, "big")
    step = f"{(c/prev-1)*100:+.0f}%" if prev else ""
    flag = "  <-- one token over" if n == TH else ""
    print(f"  {n:>14,} {P.context_multiplier(n):>10.1f}x {money(c):>12} {step:>12}{flag}")
    prev = c
print()

below, above = P.cost(TH - 1, OUT, "big"), P.cost(TH, OUT, "big")
tokens([("199,999 tokens", TH - 1, OUT), ("200,000 tokens", TH, OUT)])
note(f"""
ONE extra input token -- 0.0005% more tokens -- for {(above/below-1)*100:.0f}% more money.
There is no other lever in this set where the derivative does that.
""")

# --- what it does to a real distribution ------------------------------------
# A RAG pipeline whose context grew over time. Most requests are comfortably
# under; a minority have crept over the line and carry the whole penalty.
DIST = [(140_000, 0.55), (175_000, 0.26), (195_000, 0.12), (205_000, 0.05), (240_000, 0.02)]
VOL = 12_000

blended = sum(share * P.cost(n, OUT, "big") for n, share in DIST)
over = sum(share for n, share in DIST if n >= TH)
over_spend = sum(share * P.cost(n, OUT, "big") for n, share in DIST if n >= TH)

note(f"""
A RAG pipeline's request sizes, after a year of nobody watching:
""" + "\n".join(f"{n:>9,} tokens  {share:>5.0%} of traffic"
                for n, share in DIST) + f"""

{over:.0%} of requests are over the line and they are {over_spend/blended:.0%} of the spend.
""")

# trimming the two over-threshold buckets back under the line
trimmed = sum(share * P.cost(min(n, TH - 1_000), OUT, "big") for n, share in DIST)
costs([("as it is today", blended),
       ("over-threshold requests trimmed under the line", trimmed)],
      volume_per_day=VOL)

saving = (blended - trimmed) * VOL * 30
verdict(f"""
Trimming {over:.0%} of requests back under the threshold cuts the blended bill
{pct(blended, trimmed):.0f}% -- {money(saving)}/month -- by removing a few
thousand tokens from a small minority of calls. Nothing else changes.

WHAT TO DO, in order:
1. Plot the DISTRIBUTION of your input sizes, not the mean. A mean of 150K tells
   you nothing about the 5% sitting at 205K, and those are the expensive ones.
2. Put a hard guard just under the threshold -- drop the lowest-ranked retrieved
   chunks until the request fits. Recipe 09 is the mechanism; this is the
   deadline it has to hit.
3. Alert on requests within a few thousand tokens of the line. They are one
   prompt edit away from doubling.

AND THE TRAP INSIDE THE TRAP: a retry that appends context, a conversation that
grows, or a prompt change that adds examples can all push a workload over the
cliff with no code review flagging anything. tools/cost_gate.py catches the
prompt edit; only a runtime guard catches the other two.
""")
headline(0.0, -pct(blended, trimmed), saving)
