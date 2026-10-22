#!/usr/bin/env python3
"""RECIPE 17 - Semantic caching: 100% off, and the only lever that can be wrong.

Prompt caching (recipe 05) discounts a call that still happens. A semantic cache
SKIPS the call: a new question close enough to an old one gets the old answer,
at zero marginal cost. It is the largest discount available and the only lever
in this set that can hand a user an answer to a question they did not ask.

The dial is a similarity threshold, and it trades the two against each other.
Loosen it for more hits and you buy wrong answers. Nothing in the token bill
will tell you that you did.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(17, "Semantic caching and the wrong-answer tax", "price lever - with a correctness cost")

IN_TOK, OUT_TOK, VOL = 2_100, 480, 90_000
EMBED_PER_REQ = 0.0000012      # one embedding call to look the question up

full = P.cost(IN_TOK, OUT_TOK, "big")

# Threshold -> (hit rate, share of HITS that are actually wrong answers).
# ILLUSTRATIVE. The shape -- hits and false hits rising together -- is the
# finding; measure both on your own traffic before setting a threshold.
LEVELS = [
    ("off",         0.00, 0.000),
    ("0.97 strict", 0.18, 0.004),
    ("0.93",        0.37, 0.021),
    ("0.88",        0.56, 0.068),
    ("0.80 loose",  0.71, 0.154),
]

note(f"""
Every request costs {money(full)} uncached. A cache HIT costs the embedding
lookup only -- {money(EMBED_PER_REQ)} -- because the model is never called.
That is a {(1 - EMBED_PER_REQ/full)*100:.1f}% saving on a hit, which no other
lever here comes close to.
""")

tokens([("cache miss", IN_TOK, OUT_TOK), ("cache hit", 0, 0)])
note("A hit sends nothing. This is the only lever in the set that removes the\n"
     "request rather than repricing it -- and that is exactly why it can be wrong.")

rows = []
for name, hit, false_rate in LEVELS:
    per = (1 - hit) * full + hit * EMBED_PER_REQ + EMBED_PER_REQ
    rows.append((f"threshold {name}", per))
costs(rows, volume_per_day=VOL)

print("  WHAT THE SAVING COSTS YOU")
print(f"  {'threshold':14} {'hit rate':>9} {'spend/mo':>12} {'wrong answers/day':>19}")
for (name, hit, false_rate), (_, per) in zip(LEVELS, rows):
    wrong = VOL * hit * false_rate
    print(f"  {name:14} {hit:>8.0%} {money(per*VOL*30):>12} {wrong:>18,.0f}")
print()

strict = rows[1][1]
note(f"""
At the loosest setting you save {pct(full, rows[-1][1]):.0f}% and hand out
{VOL*LEVELS[-1][1]*LEVELS[-1][2]:,.0f} wrong answers a day. At the strictest you
save {pct(full, strict):.0f}% and hand out {VOL*LEVELS[1][1]*LEVELS[1][2]:,.0f}.
Both appear on the bill as a success.
""")

verdict(f"""
WHERE IT IS SAFE, and the list is shorter than people assume:
- idempotent, factual lookups where an identical answer is genuinely correct
- short TTLs, so a stale answer expires before it matters
- NEVER anything user-specific, personalised, time-sensitive or stateful. A
  semantic cache keyed on "what is my balance" is a data incident, not a saving.

HOW TO SET THE THRESHOLD: sample real hits and have a human grade whether the
returned answer actually answers the new question. That is the only measurement
that matters and no similarity score substitutes for it. Then price a wrong
answer -- support contact, re-work, lost trust -- and pick the threshold where
the saving still exceeds it. Recipe 15 does the same arithmetic for effort.

AND KEEP IT SEPARATE FROM PROMPT CACHING IN THE LEDGER. Prompt caching is a
provider discount on a call you still make: always safe, no correctness risk.
This skips the call. Reporting them as one number hides the only risk you took.
""")
headline(-100.0 * LEVELS[1][1], -pct(full, strict), (full - strict) * VOL * 30)
