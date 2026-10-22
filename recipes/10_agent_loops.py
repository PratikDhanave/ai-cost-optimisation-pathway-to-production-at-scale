#!/usr/bin/env python3
"""RECIPE 10 - Agent loops multiply everything, and max_tokens is not a lever.

An agent re-reads its own growing trace on every step, so the quadratic growth of
recipe 06 arrives multiplied by the step count. Then the obvious-looking fix
makes it worse: capping max_tokens does not reduce spend, because a truncated
turn is discarded AND STILL BILLED. The three controls below look
interchangeable and do completely different jobs.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, pct, money, scaled
import prices as P

banner(10, "Agent loops, and the max_tokens trap", "multiplier - and one control that is not a lever")

SYS, TOOL_RESULT, THOUGHT, STEPS = 900, 450, 300, 12

def loop(steps=STEPS, keep=None, cache=False):
    """Input tokens billed across one agent run."""
    billed, trace = 0, []
    for s in range(steps):
        window = trace if keep is None else trace[-keep:]
        billed += round(SYS * P.CACHE_READ if (cache and s) else SYS) + sum(window)
        trace.append(TOOL_RESULT + THOUGHT)
    return billed

one_shot = SYS + TOOL_RESULT
full     = loop()
pruned   = loop(keep=4)
both     = loop(keep=4, cache=True)
out      = THOUGHT * STEPS

note(f"""
One {STEPS}-step agent run, {SYS}-token system prompt, {TOOL_RESULT}-token tool results.
a single non-agentic call would bill   {one_shot:>8,} input tokens
the agent run bills                    {full:>8,} input tokens   {full/one_shot:.0f}x
""")

tokens([("full trace every step", full,   out),
        ("last 4 steps kept",     pruned, out),
        ("pruned + cached prefix", both,  out)])

RUNS = scaled(5_000)
cs = [("full trace", P.cost(full, out, "big")),
      ("pruned trace", P.cost(pruned, out, "big")),
      ("pruned + cached", P.cost(both, out, "big"))]
costs(cs, volume_per_day=RUNS, unit="run")

# --- the trap ---------------------------------------------------------------
CAP_LOW, CAP_HIGH = 16_384, 64_000
FAIL_AT_LOW = 0.15          # share of attempts the low cap TRUNCATES -- none of them solved
solved_low  = 1 - FAIL_AT_LOW

run_cost = P.cost(full, out, "big")
per_attempt_low  = run_cost                      # truncated attempts cost the same
per_solved_low   = run_cost / solved_low         # ...and are then retried or abandoned
per_solved_high  = run_cost                      # no truncation, every attempt counts

note(f"""
THE max_tokens TRAP. Cap at {CAP_LOW:,} instead of {CAP_HIGH:,} and
{FAIL_AT_LOW*100:.0f}% of attempts end on the cap. A truncated turn solves
nothing and is billed in full, so:
cost per ATTEMPT   {money(per_attempt_low)}  -- looks unchanged, because it is
cost per SOLVED    {money(per_solved_low)}  vs {money(per_solved_high)} at the high cap
                   +{(per_solved_low/per_solved_high-1)*100:.0f}% per solved task -- the cap made it WORSE

NOT MEASURED HERE, and flagged as such: the 15% truncation share above is an
assumption, chosen because it is conservative. Measure your own stop_reason
distribution before quoting a figure -- it is one field in the API response,
and it is the whole argument.

THREE CONTROLS, THREE JOBS:
  task budget   model SEES a live token countdown and self-regulates   SAVES MONEY
  max_tokens    caps one response, invisibly to the model              SAVES NOTHING
  spend limit   platform-enforced hard dollar stop                     BACKSTOP ONLY
""")

saving = (P.cost(full, out, "big") - P.cost(both, out, "big")) * RUNS * 30

verdict(f"""
Pruning the trace and caching the prefix: {pct(full + out, both + out):.0f}% fewer
tokens, {money(saving)}/month at {RUNS:,} runs/day.

SET max_tokens HIGH -- {CAP_HIGH:,} for agentic work -- and treat
stop_reason == "max_tokens" as a FAILURE to alert on, not a budget control.
Economise with the levers the model can see: a task budget it can read, fewer
steps, cheaper tools, and a step limit that ends a run instead of truncating it.

Measure cost per COMPLETED TASK. It is the only denominator under which these
three controls rank correctly, and the one that makes the max_tokens result
obvious instead of surprising.
""")
headline(-pct(full + out, both + out),
         -pct(P.cost(full, out, "big"), P.cost(both, out, "big")), saving)
