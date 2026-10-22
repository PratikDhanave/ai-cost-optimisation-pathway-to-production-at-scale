#!/usr/bin/env python3
"""RECIPE 13 - Governance: every optimisation gain gets eaten by growth.

Recipes 02-12 reduce the cost of a request. None of them stops the total bill
climbing, because more features launch, more users arrive, and existing users
get more intense. Governance is what converts per-request efficiency into
organisational cost control -- and the arithmetic below is why it is not
optional.

Two demos: the gains-eaten-by-growth sum, and a launch-day spike met by three
different policies.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(13, "Budgets, quotas and circuit breakers", "control - not a discount")

IN_TOK, OUT_TOK = 2_000, 450
big   = P.cost(IN_TOK, OUT_TOK, "big")
small = P.cost(IN_TOK, OUT_TOK, "small")

# --- 1 · the gains get eaten -------------------------------------------------
START_RPD, CUT, GROWTH, MONTHS = 40_000, 0.45, 0.28, 6
print("  THE GAINS GET EATEN")
print(f"  a {CUT*100:.0f}% per-request cut, then {GROWTH*100:.0f}% monthly volume growth")
print(f"  {'month':>6} {'req/day':>10} {'$/request':>12} {'monthly bill':>14} {'vs month 0':>11}")
base_bill = big * START_RPD * 30
for m in range(MONTHS + 1):
    rpd  = START_RPD * (1 + GROWTH) ** m
    per  = big if m == 0 else big * (1 - CUT)
    bill = per * rpd * 30
    print(f"  {m:>6} {rpd:>10,.0f} {money(per):>12} {money(bill):>14} {bill/base_bill:>10.2f}x")
final_ratio = (big * (1 - CUT) * START_RPD * (1 + GROWTH) ** MONTHS * 30) / base_bill
print()
note(f"""
The optimisation worked -- {CUT*100:.0f}% off every request, and it held. By month
{MONTHS} the bill is {final_ratio:.1f}x where it started. Nobody did anything wrong;
the service grew. Without a budget this shows up as a surprise invoice, and the
optimisation programme gets blamed for a growth problem.
""")

# --- 2 · launch day ----------------------------------------------------------
NORMAL_RPD, SPIKE_RPD = 20_000, 150_000
DAILY_BUDGET = big * NORMAL_RPD * 1.5          # 50% headroom over normal

def policy(name, spike, mode):
    """Returns (requests_served, tokens_billed, cost) for one spiked day."""
    served = tokens_b = cost = 0
    for i in range(spike):
        if mode == "stop" and cost >= DAILY_BUDGET:
            continue                                   # refused: no tokens, no cost, no answer
        downgrade = mode == "downgrade" and cost >= DAILY_BUDGET * 0.8
        c = small if downgrade else big
        cost += c
        tokens_b += IN_TOK + OUT_TOK
        served += 1
    return name, served, tokens_b, cost

runs = [policy("no controls",        SPIKE_RPD, "none"),
        policy("downgrade at 80%",   SPIKE_RPD, "downgrade"),
        policy("hard stop at 100%",  SPIKE_RPD, "stop")]

note(f"""
LAUNCH DAY. A marketing email turns {NORMAL_RPD:,} requests/day into {SPIKE_RPD:,}.
Daily budget is {money(DAILY_BUDGET)} -- 50% headroom over a normal day.
""")

print("  TOKENS")
print(f"  {'':28} {'served':>10} {'tokens':>12} {'change':>10}")
base_tok = runs[0][2]
for name, served, tok, _ in runs:
    ch = "" if tok == base_tok else f"{-pct(base_tok, tok):+6.1f}%"
    print(f"  {name:28} {served:>10,} {tok:>12,} {ch:>10}")
print()
note("""
The downgrade policy serves EVERY request and cuts no tokens -- it swaps the
model under the request. Only the hard stop reduces tokens, and it does it by
refusing people.
""")

costs([(n, c) for n, _, _, c in runs], unit="day")

verdict(f"""
No controls: {money(runs[0][3])} in one day, {runs[0][3]/DAILY_BUDGET:.1f}x the
budget, discovered on the invoice.

Downgrade at 80%: {pct(runs[0][3], runs[1][3]):.0f}% cheaper, every request still
answered, quality degraded for the tail of the day. This is almost always the
right default -- it needs recipe 08's routing already built, which is why
governance is the capstone and not the starting point.

Hard stop at 100%: cheapest and it REFUSED {runs[0][1]-runs[2][1]:,} requests.
That is the correct policy for an internal backfill and a catastrophic one for a
checkout flow. The cost did not disappear; it moved somewhere the token bill
cannot see it.

THE FOUR PILLARS, in dependency order -- each needs the one before it:
  VISIBILITY      per-feature metering (recipe 01). Without it the rest is blind.
  ACCOUNTABILITY  every dollar attributed to a team and a feature.
  CONTROLS        budgets, quotas, circuit breakers. What this recipe measures.
  OPTIMISATION    teams with the incentive and the tools to use recipes 02-12.

AND SET THE ALERT ON THE RATE, NOT THE TOTAL. A daily budget breached at 09:00
is useful; the same budget reported at midnight is an autopsy. Alert on spend
velocity against the hour of day, and page someone before the breaker trips.
""")
headline(-pct(base_tok, runs[1][2]), -pct(runs[0][3], runs[1][3]),
         (runs[0][3] - runs[1][3]) * 30)
