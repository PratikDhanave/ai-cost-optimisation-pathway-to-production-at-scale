#!/usr/bin/env python3
"""RECIPE 11 - Compose the levers, and stop adding their percentages up.

One request shape -- an 800-token stable prefix, a 12,000-token history and 500
output tokens -- and four levers that can each be on or off.

The point of the recipe is the LAST table. Four levers worth 40%, 50%, 73% and
50% do not compose to 213% off. Each one shrinks the base the next one works on,
so the marginal value of a lever depends entirely on what is already switched
on -- which is why reach x discount, not discount alone, decides the order you
do this work in.
"""
import pathlib, sys, itertools
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, costs, verdict, headline, money, pct
import prices as P
from models import STACK, LEVERS, stack_request as request

banner(11, "Compose the levers; stop adding percentages", "composition - why percentages do not add")

PREFIX, HISTORY, TRUNCATED, OUT = (STACK["prefix"], STACK["history"],
                                   STACK["truncated"], STACK["out"])
VOL = 150_000

# The model itself lives in models.py, shared with the visual demo so the two
# cannot drift. LEVERS is its canonical order.

base_tok, base = request()

# --- tokens first, as always -------------------------------------------------
print("  TOKENS   (only ONE of the four levers touches tokens at all)")
print(f"  {'':28} {'in':>10} {'out':>10} {'change':>10}")
for label, kw in (("nothing on", {}),
                  ("route -> small model", {"route": True}),
                  ("truncate history",     {"trunc": True}),
                  ("cache the prefix",     {"cache": True}),
                  ("batch tier",           {"batch": True})):
    t, _ = request(**kw)
    ch = "" if not kw else f"{-pct(base_tok, t):+6.1f}%"
    print(f"  {label:28} {t:>10,} {OUT:>10,} {ch:>10}")
print()
note("""
Truncation removes tokens. Routing, caching and the batch tier remove none --
they change what a token costs. Three of the four levers are invisible in the
token column and worth most of the money.
""")

# --- cumulative, in the order that actually works --------------------------
order, on, rows = ["trunc", "cache", "route", "batch"], {}, [("nothing on", base)]
for lever in order:
    on[lever] = True
    rows.append((f"+ {lever}", request(**on)[1]))
costs(rows, volume_per_day=VOL)

full = rows[-1][1]

# --- the non-additivity table ------------------------------------------------
print("  MARGINAL VALUE OF EACH LEVER, depending on what is already on")
print(f"  {'lever':12} {'alone':>14} {'added last':>14} {'ratio':>8}")
for lever in order:
    alone = base - request(**{lever: True})[1]
    others = {k: True for k in order if k != lever}
    last   = request(**others)[1] - full
    print(f"  {lever:12} {money(alone) + '/req':>14} {money(last) + '/req':>14} "
          f"{(last/alone if alone else 0):>7.2f}x")
print()

solo_sum = sum(pct(base, request(**{l: True})[1]) for l in order)
note(f"""
Add the four solo percentages up and you get {solo_sum:.0f}% off.
Run all four together and the real number is {pct(base, full):.0f}%.
The gap is not an error -- it is what double counting looks like.
""")

verdict(f"""
All four levers: {pct(base, full):.0f}% off, {money((base-full)*VOL*30)}/month at
{VOL:,} requests/day. Tokens fell {pct(base_tok, request(**{k: True for k in order})[0]):.0f}%.
The cost cut is far larger than the token cut, and that is the shape of a real
programme: most of the money is in what a token costs, not how many you send.

ORDER OF OPERATIONS, and it is not a preference:
  1. MEASURE first (recipe 01). Without per-feature attribution you cannot tell
     which lever has reach, and reach x discount is the ceiling.
  2. Truncate / window / prune -- it shrinks the base every later lever works on.
  3. Cache what is left that is genuinely stable (never before step 2).
  4. Route by difficulty, with the escalation rate measured, not assumed.
  5. Batch whatever nobody is waiting on.

DO NOT QUOTE THAT PERCENTAGE AT ANYONE. It is an artifact of the inputs chosen
at the top of this file -- a 12,000-token history truncated to 4,000 is an
aggressive assumption, and the four levers happen to stack cleanly here. Change
the history length or the batchable share and the headline moves tens of points.
Refuse to estimate a savings percentage before reading a bill. A recipe that
computes one from its own assumptions has not read a bill either. The MECHANISM transfers. The number does not.

AND THE RULE THAT MAKES THE NUMBER CREDIBLE: measure each lever's marginal
contribution against the stack as it stands, never its solo percentage.
tools/instrument.py implements exactly that rule -- incremental attribution is
what stops four teams each claiming the same saving.
""")
headline(-pct(base_tok, request(**{k: True for k in order})[0]), -pct(base, full),
         (base - full) * VOL * 30)
