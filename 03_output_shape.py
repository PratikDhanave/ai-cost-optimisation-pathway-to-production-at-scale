#!/usr/bin/env python3
"""RECIPE 03 - Shape the output, not just the input.

Output is billed at 5x input on both tiers in prices.py. A classifier that
answers in prose is paying frontier rates for grammar nobody reads. This is the
highest-value-per-hour lever in the set and the one teams reach for last,
because the prose feels like quality.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, count, pct, money
import prices as P

banner(3, "Shape the output, not just the input", "output side - where the money is")

PROSE = """Based on my analysis of this support ticket, I would classify this as a
billing issue. The key indicator is that the customer explicitly mentions being
charged twice for their monthly subscription, which is a duplicate-charge
scenario and therefore falls squarely within the billing category rather than
the technical support or account management categories. I am highly confident in
this classification, and I would recommend routing this ticket to the billing
team for a refund review."""

JSON_OUT = '{"category": "billing", "confidence": 0.95, "route": "billing_team"}'

ENUM_OUT = "billing"

IN_TOK = 320          # the ticket plus a short instruction, same for all three

rows, prose_t = [], count(PROSE)
for label, text in (("prose answer", PROSE), ("structured JSON", JSON_OUT), ("bare enum", ENUM_OUT)):
    rows.append((label, IN_TOK, count(text)))

note(f"""
One classification task, three output contracts. The INPUT is identical in all
three -- only the instruction about how to answer changed.
""")

tokens(rows)

VOL = 150_000
cs = [(label, P.cost(i, o, "big")) for label, i, o in rows]
costs(cs, volume_per_day=VOL)

saving = (cs[0][1] - cs[1][1]) * VOL * 30
json_t = count(JSON_OUT)

verdict(f"""
Prose -> JSON cuts total request tokens {pct(IN_TOK + prose_t, IN_TOK + json_t):.0f}%
and cost {pct(cs[0][1], cs[1][1]):.0f}%: {money(saving)}/month at this volume,
for a change to one instruction line and a parser.

Two cautions the arithmetic will not give you:
- The enum row is cheapest and often wrong to ship. No confidence score means no
  threshold, no threshold means no human-review queue, and the misclassification
  cost lands outside the token bill where this recipe cannot see it.
- JSON is cheaper than prose and NOT cheaper than every alternative. Compare
  formats on YOUR schema with YOUR tokenizer. Published format comparisons are
  mostly illustrative; trust the one you can re-run and label the rest.
""")
headline(-pct(IN_TOK + prose_t, IN_TOK + json_t), -pct(cs[0][1], cs[1][1]), saving)
