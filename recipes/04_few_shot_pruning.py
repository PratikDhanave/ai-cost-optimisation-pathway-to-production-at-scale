#!/usr/bin/env python3
"""RECIPE 04 - Prune the few-shot examples.

Eight examples went in during development because eight felt safe. Nobody ever
measured whether two would do. Examples live in the prefix, so they are paid on
every request and they are the single most common source of a bloated prompt.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, count, pct, money
import prices as P

banner(4, "Prune the few-shot examples", "input side - trades accuracy for tokens")

EXAMPLES = [
    ('"I was charged twice for March."', '{"category":"billing","confidence":0.97}'),
    ('"The app crashes when I open settings."', '{"category":"technical","confidence":0.95}'),
    ('"How do I change my delivery address?"', '{"category":"account","confidence":0.91}'),
    ('"My refund has not arrived after 10 days."', '{"category":"billing","confidence":0.93}'),
    ('"Is the blue version back in stock?"', '{"category":"product","confidence":0.96}'),
    ('"I cannot log in since the update."', '{"category":"technical","confidence":0.94}'),
    ('"Cancel my subscription please."', '{"category":"account","confidence":0.98}'),
    ('"Do these shoes run small?"', '{"category":"product","confidence":0.89}'),
]
INSTRUCTION = "Classify the support ticket. Reply with JSON only: category, confidence."
TICKET, OUT = 90, 22

def prompt(n):
    shots = "\n".join(f"Ticket: {q}\nAnswer: {a}" for q, a in EXAMPLES[:n])
    return f"{INSTRUCTION}\n\n{shots}\n\nTicket:"

rows = [(f"{n} examples" if n else "zero-shot", count(prompt(n)) + TICKET, OUT)
        for n in (8, 4, 2, 0)]

note("""
Four prompts, same classifier, same task. Only the example count changes.
""")

tokens(rows)

VOL = 150_000
cs = [(label, P.cost(i, o, "big")) for label, i, o in rows]
costs(cs, volume_per_day=VOL)

eight, two = cs[0][1], cs[2][1]
saving = (eight - two) * VOL * 30

verdict(f"""
8 -> 2 examples: {pct(rows[0][1] + rows[0][2], rows[2][1] + rows[2][2]):.0f}% fewer
tokens, {pct(eight, two):.0f}% lower cost, {money(saving)}/month.

THE MEASUREMENT THIS RECIPE CANNOT DO FOR YOU. Pruning examples trades accuracy
for tokens, and the exchange rate is specific to your task. The procedure:
  1. build a labelled eval set -- a few hundred real tickets, hand-graded
  2. run 8 / 4 / 2 / 0 examples against it
  3. plot accuracy against cost per CORRECT answer, not cost per request
  4. keep the cheapest configuration that holds your accuracy floor
Cost per correct answer is the denominator that matters: if dropping to two
examples costs you four points of accuracy, the re-work and the escalations are
a bigger line than the tokens you saved. Ship the eval, not the intuition.

Keep the examples that cover a category no other example covers. Drop the
duplicates first -- this set has two billing and two technical examples doing
substantially the same work.
""")
headline(-pct(rows[0][1] + rows[0][2], rows[2][1] + rows[2][2]), -pct(eight, two), saving)
