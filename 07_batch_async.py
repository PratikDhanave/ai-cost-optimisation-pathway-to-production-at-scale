#!/usr/bin/env python3
"""RECIPE 07 - Move what nobody is waiting for to the batch tier.

Half price, both directions, for work that can tolerate a turnaround measured in
hours. No prompt change, no model change, no accuracy change, zero tokens saved.
It is the largest single discount in the set and the only one that is purely a
scheduling decision.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money
import prices as P

banner(7, "Move async work to the batch tier", "price lever - a scheduling decision")

IN_TOK, OUT_TOK = 2_200, 600

# A real workload is a mix. Only the interactive share must stay on the live tier.
WORKLOAD = [
    ("nightly ticket classification", 400_000, True),
    ("document enrichment backfill",  250_000, True),
    ("weekly digest generation",       40_000, True),
    ("live chat replies",             120_000, False),   # a person is waiting
    ("checkout fraud screen",          30_000, False),   # a person is waiting
]
batchable = sum(v for _, v, b in WORKLOAD if b)
live      = sum(v for _, v, b in WORKLOAD if not b)
total     = batchable + live

note(f"""
Daily request mix:
""" + "\n".join(f"{n:34} {v:>9,}  {'BATCHABLE' if b else 'must be live'}"
                for n, v, b in WORKLOAD) + f"""

{batchable:,} of {total:,} requests ({batchable/total*100:.0f}%) have nobody waiting on them.
""")

tokens([("live tier",  IN_TOK, OUT_TOK),
        ("batch tier", IN_TOK, OUT_TOK)])
note("Identical. The batch tier changes the RATE, not the request.")

live_c  = P.cost(IN_TOK, OUT_TOK, "big")
batch_c = P.cost(IN_TOK, OUT_TOK, "big", batch=True)
costs([("live tier", live_c), ("batch tier", batch_c)], volume_per_day=total)

all_live = live_c * total * 30
mixed    = (live_c * live + batch_c * batchable) * 30
note(f"""
Applied to the real mix, not to everything:
everything on the live tier   {money(all_live)}/month
batchable share moved         {money(mixed)}/month
                              {money(all_live - mixed)}/month saved, {(1-mixed/all_live)*100:.0f}%
""")

verdict(f"""
{P.BATCH*100:.0f}% off both directions for the {batchable/total*100:.0f}% of traffic
nobody is waiting on. No quality risk at all -- it is the same model and the same
prompt.

WHAT IT COSTS YOU. Turnaround is a service-level commitment, not a latency
number: plan for hours and handle the job that comes back late or partially.
Build the queue, the retry and the partial-failure path BEFORE you move
production traffic, because a batch job that silently drops 3% of a nightly
classification run is a data problem that outlives the saving.

THE ONE INCOMPATIBILITY WORTH KNOWING: on Bedrock, prompt caching is NOT
supported with the batch inference API. Recipes 05 and 07 do not always compose
-- check your provider before assuming both discounts apply to the same request.
""")
headline(0.0, -(1 - mixed / all_live) * 100, all_live - mixed)
