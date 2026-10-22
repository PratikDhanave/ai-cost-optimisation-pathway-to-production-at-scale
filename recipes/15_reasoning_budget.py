#!/usr/bin/env python3
"""RECIPE 15 - Reasoning tokens: billed as output, and you never see them.

The dial nobody touches, on the most expensive side of the bill. A reasoning
model thinks before it answers, and that thinking is billed as OUTPUT -- the
side that costs several times input -- while never appearing in the response.
You are paying, at the premium rate, for text you cannot read.

This is recipe 10's max_tokens lesson inverted. max_tokens is a cap the model
cannot see, so it saves nothing. A reasoning budget IS visible to the model: it
plans against it. One is a wall, the other is an instruction.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(15, "Reasoning tokens and the effort dial", "output side - the invisible half")

IN_TOK, ANSWER = 1_400, 320

# Effort levels: thinking tokens spent, and the share of tasks solved.
# ILLUSTRATIVE -- the shape (sharply rising cost, flattening accuracy) is the
# finding; these particular numbers are assumptions. Measure your own.
LEVELS = [
    ("off",      0,      0.71),
    ("low",      900,    0.83),
    ("medium",   3_400,  0.89),
    ("high",     11_000, 0.91),
    ("maximum",  28_000, 0.915),
]

note(f"""
One task, five effort settings. Input is {IN_TOK:,} tokens and the visible answer
is {ANSWER} tokens in every case -- only the invisible thinking changes.
Thinking is billed at the OUTPUT rate (${P.MODELS['big'][1]:.0f}/1M), which is
{P.OUTPUT_PREMIUM:.0f}x the input rate.
""")

rows = [(f"effort {name}", IN_TOK, ANSWER + think) for name, think, _ in LEVELS]
tokens(rows)

cs = [(f"effort {name}", P.cost(IN_TOK, ANSWER + think, "big")) for name, think, _ in LEVELS]
costs(cs, volume_per_day=40_000)

print("  COST PER SOLVED TASK -- the only ranking that matters")
print(f"  {'effort':14} {'solved':>8} {'$/request':>12} {'$/solved':>12} {'vs off':>9}")
base = None
for (name, think, solved), (_, c) in zip(LEVELS, cs):
    per_solved = c / solved
    base = base or per_solved
    print(f"  {name:14} {solved:>7.0%} {money(c):>12} {money(per_solved):>12} "
          f"{(per_solved/base-1)*100:>+8.0f}%")
print()

best = min(zip(LEVELS, cs), key=lambda z: z[1][1] / z[0][2])
note(f"""
On that ranking the winner is effort {best[0][0]} -- but read what it assumes.
Cost per solved task prices a FAILURE AT ZERO. It says a wrong answer is free,
which is true of the token bill and true of nothing else.
""")

# --- what the table above hides -------------------------------------------
print("  THE SAME TABLE, PRICING A FAILURE")
print("  if a failed task costs you this much in re-work, escalation or a lost")
print("  customer, the cheapest effort setting moves:")
print(f"  {'failure costs':>15} {'best effort':>14} {'total / task':>14}")
for fail_cost in (0.00, 0.05, 0.50, 5.00):
    scored = [(name, c + (1 - solved) * fail_cost / solved)
              for (name, _, solved), (_, c) in zip(LEVELS, cs)]
    win = min(scored, key=lambda z: z[1])
    print(f"  {money(fail_cost):>15} {win[0]:>14} {money(win[1]):>14}")
print()
note(f"""
A failure that costs nothing says use the cheapest setting. A failure that costs
a few cents moves the answer. The token bill cannot see this column, which is
why "cost per solved task" is the floor of the argument and not the whole of it.
Put a number on a wrong answer before you pick an effort level.
""")

verdict(f"""
THREE THINGS THAT MAKE THIS DIFFERENT FROM max_tokens (recipe 10):
- The model can SEE an effort setting or a stated token budget and plans against
  it. It cannot see max_tokens; it just gets cut off mid-sentence and the turn
  is discarded and still billed.
- Reasoning tokens land on the OUTPUT side. A 1,400-token input with 28,000
  thinking tokens is an input-shaped request with an output-shaped bill.
- They are invisible in the response, so a dashboard that samples response
  LENGTH sees nothing. Read the usage object, not the text.

WHAT TO DO: pick the lowest effort that clears your accuracy floor, measured on
a labelled set, and set it PER TASK rather than globally. Classification does
not need the same budget as a migration plan. Most teams leave one global
setting at the vendor default and never look at it again -- which is why this is
the dial nobody touches.
""")
headline(-pct(IN_TOK + ANSWER + LEVELS[-1][1], IN_TOK + ANSWER + best[0][1]),
         -pct(cs[-1][1], best[1][1]), (cs[-1][1] - best[1][1]) * 40_000 * 30)
