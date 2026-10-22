#!/usr/bin/env python3
"""RECIPE 14 - Optimisation reduces volume; negotiation reduces rate.

The last lever is commercial, and it is the only one in the set you cannot
deploy from an editor. Two facts and one trap:

  volume x rate = bill. Recipes 02-12 attack volume. A committed-use discount
  attacks rate. 50% off volume and 20% off rate is 60% off the bill, and neither
  gets there alone.

  THE TRAP: a commitment is sized from a forecast. Forecast BEFORE you optimise
  and you commit to volume you are about to delete -- then pay for it anyway.
  Order matters more here than anywhere else in the set.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(14, "Committed use and forecasting", "commercial - rate, not volume")

IN_TOK, OUT_TOK, RPD = 1_900, 420, 180_000
base = P.cost(IN_TOK, OUT_TOK, "big")
OPTIMISED = 0.50      # volume cut already banked from recipes 02-09
COMMIT    = 0.20      # illustrative committed-use rate discount -- NOT a quoted term

tokens([("list rate",            IN_TOK, OUT_TOK),
        ("committed-use rate",   IN_TOK, OUT_TOK)])
note("""
Zero tokens. A commitment is a price, not a payload -- the fourth price lever in
this set, after caching, batch and routing.
""")

month_base = base * RPD * 30
rows = [("list rate, unoptimised",       month_base),
        ("optimised volume only",        month_base * OPTIMISED),
        ("committed rate only",          month_base * (1 - COMMIT)),
        ("both",                         month_base * OPTIMISED * (1 - COMMIT))]
print("  COST")
print(f"  {'':28} {'monthly':>14} {'vs list':>10}")
for label, c in rows:
    print(f"  {label:28} {money(c):>14} {-pct(month_base, c):>+9.1f}%")
print()
note(f"""
{OPTIMISED*100:.0f}% off volume and {COMMIT*100:.0f}% off rate compose to
{pct(month_base, rows[3][1]):.0f}% off -- multiplicatively, not additively. The
two levers do not overlap because they act on different factors, which is the
one case in this whole set where stacking is clean.
""")

# --- the trap ----------------------------------------------------------------
UNUSED_RECOVERY = 0.0        # most commitments are use-it-or-lose-it
commit_on_old = month_base * (1 - COMMIT)            # sized from pre-optimisation volume
actual_need   = month_base * OPTIMISED * (1 - COMMIT)
stranded      = (commit_on_old - actual_need) * (1 - UNUSED_RECOVERY)

note(f"""
THE TRAP, in numbers. Commit to pre-optimisation volume, then land the
optimisation programme:
  committed spend, sized on old volume   {money(commit_on_old)}/month
  what you actually consume              {money(actual_need)}/month
  stranded commitment                    {money(stranded)}/month  -- paid for nothing
  {money(stranded * 12)}/year, and it buys a discount on tokens you no longer send.

Net of the stranded spend, the commitment turned a {pct(month_base, month_base*OPTIMISED):.0f}%
saving into {pct(month_base, commit_on_old):.0f}%. The discount was real. The
commitment destroyed more than it returned.
""")

# --- forecast the three growth components separately -------------------------
ORGANIC, BEHAVIOURAL, FEATURE_STEP, M = 0.05, 0.09, 0.22, 6
print("  WHY A SINGLE GROWTH RATE UNDER-FORECASTS")
print(f"  {'month':>6} {'organic only':>14} {'+ behavioural':>15} {'+ feature steps':>17}")
for m in range(M + 1):
    o = month_base * (1 + ORGANIC) ** m
    b = month_base * ((1 + ORGANIC) * (1 + BEHAVIOURAL)) ** m
    fsteps = 1 + FEATURE_STEP * (m // 3)          # a feature lands every third month
    print(f"  {m:>6} {money(o):>14} {money(b):>15} {money(b * fsteps):>17}")
print()
note(f"""
Same service, three forecasts. Month {M}: {money(month_base*(1+ORGANIC)**M)} on a
user-growth rate alone, versus
{money(month_base*((1+ORGANIC)*(1+BEHAVIOURAL))**M*(1+FEATURE_STEP*(M//3)))} once
behavioural intensity and launched features are modelled separately --
{(((1+ORGANIC)*(1+BEHAVIOURAL))**M*(1+FEATURE_STEP*(M//3))/(1+ORGANIC)**M - 1)*100:.0f}% higher.
Commit against the first number and you under-buy; budget against it and you
breach every quarter.

ORGANIC is user count -- predictable, and the only one most teams model.
BEHAVIOURAL is tokens per user per day. Conversations lengthen, queries get
  harder, a user who sent two messages a day sends ten. Invisible in user
  metrics, loud in token metrics. TRACK IT AS ITS OWN SERIES.
FEATURE-DRIVEN is a step function, not a curve. A launch does not ramp; it
  arrives at volume and then grows organically from there.
""")

verdict(f"""
SEQUENCE, and it is the whole recipe:
  1. Meter per feature for several months (recipe 01). A commitment sized on one
     month of data is a guess with a contract attached.
  2. Land the optimisation programme (recipes 02-12). THEN measure the floor.
  3. Forecast the three growth components separately from that optimised floor.
  4. Commit to the CONSERVATIVE band of that forecast -- the volume you are
     confident about even if next quarter's roadmap slips.
  5. Leave the uncertain tail on pay-as-you-go. Paying list rate on the tail is
     cheaper than stranding a commitment on the base.

Multi-provider mix is the hedge that makes step 4 safe: a second provider
qualified and integrated means a commitment is a negotiation and not a
dependency. The cost of that optionality is real -- two sets of evals, two
tokenizers, two failure modes -- and it is the price of not having your rate set
unilaterally at renewal.

NOTHING HERE IS A QUOTED TERM. The {COMMIT*100:.0f}% is illustrative. Real
committed-use terms depend on volume, duration, provider and timing, and the
discount is the part of this recipe you cannot compute -- you have to ask.
""")
headline(0.0, -pct(month_base, rows[3][1]), month_base - rows[3][1])
