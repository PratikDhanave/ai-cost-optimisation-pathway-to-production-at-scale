#!/usr/bin/env python3
"""RECIPE 21 - Cost per user, and the ones who cost more than they pay.

Every other recipe asks what a request costs. This one asks whether a CUSTOMER
is profitable, which is the question that decides whether the feature survives.

Flat-rate pricing against usage-based cost is a structural mismatch. Usage is a
power law: the median user is cheap, the mean is comfortable, and a small tail
consumes more than it pays. On a per-request dashboard everything looks fine.
On a per-user ledger a minority of accounts is eating the margin -- and because
they are your most engaged users, every growth initiative recruits more of them.

This is the Chapter-4 question the rest of the set assumes you have answered.
"""
import pathlib, statistics, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(21, "Cost per user and the unprofitable tail", "unit economics - per customer, not per call")

PRICE, USERS = 20.00, 50_000          # flat monthly subscription
IN_TOK, OUT_TOK = 2_600, 640
per_req = P.cost(IN_TOK, OUT_TOK, "big")

# A usage distribution, stated as assumptions. The SHAPE -- a long thin tail
# carrying most of the volume -- is the finding and it is near-universal.
# Replace these with your own cohort data before acting on any of it.
BANDS = [
    ("dormant",      0.34,     4),
    ("light",        0.41,    40),
    ("regular",      0.18,   190),
    ("heavy",        0.055,  900),
    ("power",        0.014, 3_400),
    ("extreme",      0.001, 17_000),
]

note(f"""
{USERS:,} subscribers at {money(PRICE)}/month flat. One request costs
{money(per_req)}, so a subscription pays for {PRICE/per_req:,.0f} requests.
Above that number the account loses money.
""")

tokens([("one request", IN_TOK, OUT_TOK)])
note("Unchanged by anything in this recipe. The lever here is not the request --\n"
     "it is which users you let make how many of them.")

print("  PER USER, PER MONTH")
print(f"  {'band':12} {'share':>7} {'requests':>10} {'cost':>11} {'margin':>11} {'':>3}")
total_cost = total_margin = 0.0
unprofit_users = unprofit_loss = 0.0
for name, share, reqs in BANDS:
    n = USERS * share
    cost = reqs * per_req
    margin = PRICE - cost
    total_cost += cost * n
    total_margin += margin * n
    if margin < 0:
        unprofit_users += n
        unprofit_loss += -margin * n
    print(f"  {name:12} {share:>6.1%} {reqs:>10,} {money(cost):>11} {money(margin):>11} "
          f"{'LOSS' if margin < 0 else '':>3}")
revenue = PRICE * USERS
print(f"  {'TOTAL':12} {'':>7} {'':>10} {money(total_cost):>11} {money(total_margin):>11}")
print()

print("  THE P&L, WHICH LOOKS FINE")
print(f"  {'revenue':28} {money(revenue):>14}/month")
print(f"  {'inference cost':28} {money(total_cost):>14}/month")
print(f"  {'gross margin':28} {money(total_margin):>14}/month   "
      f"{total_margin/revenue*100:.0f}%")
print()

med = statistics.median([r for _, s, r in BANDS for _ in range(int(s * 1000))])
mean_reqs = sum(s * r for _, s, r in BANDS)
note(f"""
THE AVERAGE HIDES IT, EXACTLY AS IN RECIPE 01.
median user {med:>8,.0f} requests   mean user {mean_reqs:>8,.0f} requests
Gross margin is {total_margin/revenue*100:.0f}% and looks healthy. Underneath it,
{unprofit_users:,.0f} accounts ({unprofit_users/USERS*100:.1f}%) are sold below
cost and together destroy {money(unprofit_loss)}/month of margin.
""")

cap = PRICE * 0.45 / per_req        # a fair-use cap at 45% of the subscription
capped_cost = sum(USERS * s * min(r, cap) * per_req for _, s, r in BANDS)
affected = sum(s for _, s, r in BANDS if r > cap)

note(f"""
A FAIR-USE CAP at {cap:,.0f} requests/month -- the point where an account has
consumed 45% of what it pays -- touches {affected*100:.1f}% of users and recovers
{money(total_cost - capped_cost)}/month, taking margin from
{total_margin/revenue*100:.0f}% to {(revenue-capped_cost)/revenue*100:.0f}%.
""")

verdict(f"""
THE STRUCTURAL PROBLEM: flat price, usage-based cost. It does not get better
with scale -- it gets worse, because growth recruits proportionally more of the
tail and the tail is where the loss is. A per-request dashboard will never show
you this; the per-request cost is identical for everyone.

FOUR RESPONSES, roughly in order of how much customers hate them:
1. ROUTE THE TAIL, don't cap it. Heavy users are your most engaged. Send their
   traffic to a cheaper model (recipe 08), cache harder, window more
   aggressively. Same product, cheaper delivery, nobody is told "no".
2. FAIR-USE LIMITS with a generous ceiling, published up front. The cap above
   touches {affected*100:.1f}% of accounts.
3. TIER THE PRICE so heavy use buys a heavier plan.
4. METER AND CHARGE for usage above an included allowance.

MEASURE BEFORE YOU PICK. The three numbers that decide it: cost per user by
decile, revenue per user by the same decile, and the correlation between usage
and retention. If your heaviest users are also your least likely to churn, a
cap is the most expensive saving you will ever make -- the margin comes back
and the customer does not.

AND THE REASON THIS RECIPE IS LAST: every lever in recipes 02 to 20 improves
the numbers above. A 60% cut in cost per request turns most of this tail
profitable without a single conversation about limits. Do that work first.
""")
headline(0.0, -pct(total_cost, capped_cost), total_cost - capped_cost)
