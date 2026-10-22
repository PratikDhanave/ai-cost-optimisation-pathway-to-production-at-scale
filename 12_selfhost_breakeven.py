#!/usr/bin/env python3
"""RECIPE 12 - Self-hosting: the break-even moves when you optimise first.

This is not an optimisation, it is a change of cost MODEL -- from variable
(per token) to fixed (per GPU-hour). Two consequences nobody likes:

  1. A GPU bills 24/7 whether you send it traffic or not, so utilisation, not
     the hourly rate, decides the per-token price.
  2. Every earlier recipe RAISES the break-even volume. Cutting your API bill in
     half doubles the traffic you need before owning hardware pays. Optimise
     first, then re-run this -- in that order, or you will buy GPUs to serve a
     bill you could have deleted.
"""
import math, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money
import prices as P
from models import HOST, cap_per_gpu, selfhost as self_host, selfhost_floor

banner(12, "Self-hosting break-even", "architecture - fixed cost versus variable")

IN_TOK, OUT_TOK = HOST["in_tok"], HOST["out_tok"]
GPU_HOURLY   = HOST["gpu_hourly"]
GPU_MIN      = HOST["gpu_min"]       # floor: one GPU is not a production deployment
TOK_PER_SEC  = HOST["tok_per_sec"]
OPS_HOURS_MO = HOST["ops_hours"]
OPS_RATE     = HOST["ops_rate"]
OPS_FIXED    = OPS_HOURS_MO * OPS_RATE
api_small    = P.cost(IN_TOK, OUT_TOK, "small")
CAP_PER_GPU  = cap_per_gpu()

# self_host() and selfhost_floor() live in models.py, shared with the visual
# demo. GPU count follows capacity there, which is what makes this a staircase.

tokens([("managed API", IN_TOK, OUT_TOK),
        ("self-hosted", IN_TOK, OUT_TOK)])
note("""
No token change, and this recipe cannot pretend otherwise. Self-hosting changes
who owns the hardware, not what you send it.
""")

note(f"""
ONE accelerator at ${GPU_HOURLY:.2f}/hr serves {CAP_PER_GPU/30:,.0f} requests/day at
{IN_TOK + OUT_TOK:,} tokens each. The floor is {GPU_MIN} GPUs -- one is not a
production deployment: no redundancy, no rolling upgrade, no headroom.

Operations is a FIXED cost on top: {OPS_HOURS_MO} engineer-hours at ${OPS_RATE}/hr
= {money(OPS_FIXED)}/month, traffic or no traffic.
""")

print("  COST PER REQUEST -- GPU count follows capacity, so the cost is a staircase")
print(f"  {'req/day':>10} {'GPUs':>6} {'utilisation':>13} {'fixed/mo':>12} "
      f"{'self-hosted':>13} {'managed':>12} {'winner':>12}")
for rpd in (10_000, 50_000, 110_000, 120_000, 200_000, 500_000, 2_000_000):
    g, util, fixed, per = self_host(rpd * 30)
    win = "self-host" if per < api_small else "managed API"
    print(f"  {rpd:>10,} {g:>6} {util*100:>12.1f}% {money(fixed):>12} "
          f"{money(per):>13} {money(api_small):>12} {win:>12}")
print()

# first volume at which the staircase dips under the API line
be = next((r for r in range(5_000, 4_000_001, 5_000) if self_host(r * 30)[3] < api_small), None)
note(f"""
BREAK-EVEN: {be:,} requests/day, found by walking the staircase rather than
dividing fixed cost by rate -- the naive division ignores capacity and reports a
break-even the hardware cannot physically serve.

Watch the 110,000 -> 120,000 rows: demand rises 9% and the per-request cost
RISES too, because crossing the capacity boundary bought a third GPU that is
barely used. Self-hosting punishes you for growing just past a boundary.
""")

optimised = api_small * 0.5     # a 50% cut from recipes 02-09 is unremarkable
be2 = next((r for r in range(5_000, 20_000_001, 5_000) if self_host(r * 30)[3] < optimised), None)

# The floor self-hosting can ever reach: a fully loaded GPU, ops amortised away.
floor = selfhost_floor()

if be2:
    tail = f"{be2/be:.1f}x further away -- the bet got harder to win."
else:
    tail = (f"NEVER, and structurally rather than at some larger scale: a GPU running flat\n"
            f"out, with operations amortised to nothing, cannot serve a request below\n"
            f"{money(floor)} at this throughput. The optimised managed price is "
            f"{money(optimised)}.\n  No volume closes a gap that is already open at infinite volume.")

note(f"""
NOW APPLY THE EARLIER RECIPES -- this is the part that decides the question.
Halve the managed per-request cost ({money(api_small)} -> {money(optimised)}):
  break-even before optimisation   {be:>12,} requests/day
  break-even after optimisation    {(format(be2, ",") if be2 else "never"):>12} requests/day
  {tail}
""")

verdict(f"""
Self-hosting is a volume bet, and the thing you are betting on is UTILISATION.
At 10,000 requests/day the GPUs sit nearly idle and the per-request cost is
absurd; the hourly rate never changes, only the denominator does.

WHAT THIS ARITHMETIC LEAVES OUT, all of it real:
- Opportunity cost. {OPS_HOURS_MO} hours/month is a quarter of an engineer. On a
  five-person team that is 5% of your feature throughput, permanently.
- The skills. vLLM, CUDA, quantisation, GPU memory, distributed serving. If the
  team does not have them, the ramp is weeks to months and the hiring market for
  them is brutal. If the marginal cost of that hire exceeds the saving, managed
  APIs win even when the per-token arithmetic says otherwise.
- Capability gap. No native prompt caching, weaker tool calling, and a quality
  delta you must measure on your own eval set -- which means recipes 05 and 08
  partly stop applying.
- Spot instances cut the GPU line substantially and add eviction handling.

THE HYBRID IS USUALLY THE ANSWER. Self-host the simple, high-volume, stable
traffic where the GPU stays busy; route the complex tail to a managed frontier
model. That is recipe 08's cascade with a self-hosted small tier -- and it keeps
utilisation high, which is the only number that makes this work.
""")
headline(0.0, 0.0)
