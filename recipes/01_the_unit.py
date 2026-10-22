#!/usr/bin/env python3
"""RECIPE 01 - Tokens are the unit, and the average is a lie.

Nothing is optimised here. This recipe establishes the two facts every later
recipe leans on: what one real request actually costs, and why the mean cost per
request is the wrong number to run a service on.
"""
import pathlib, sys, statistics
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, count, money, scaled
import prices as P

banner(1, "Tokens are the unit", "measure first - nothing is optimised here")

SYSTEM = """You are a customer support assistant for an online retailer. You help
customers with questions about orders, shipping, returns, refunds, and product
availability. Always be polite and professional. If you do not know the answer,
say so and offer to escalate to a human agent. Never invent order numbers,
tracking numbers, delivery dates, or refund amounts."""

USER = "I ordered a pair of running shoes last Tuesday and they still have not shipped. Order 48812."

REPLY = """Thanks for getting in touch, and sorry for the delay. I can see order
48812 was placed last Tuesday and is still awaiting dispatch from our warehouse.
Orders normally ship within two business days, so this one is overdue. I have
flagged it for the fulfilment team and you should receive tracking details within
24 hours. If nothing arrives by then, reply here and I will escalate it."""

sys_t, usr_t, out_t = count(SYSTEM), count(USER), count(REPLY)
in_t = sys_t + usr_t

note(f"""
One support request, counted:
system prompt {sys_t:>5} tokens   (sent on EVERY request, forever)
user message  {usr_t:>5} tokens
reply         {out_t:>5} tokens   (billed at {P.OUTPUT_PREMIUM:.0f}x the input rate)
""")

tokens([("one request", in_t, out_t)])

VOL = scaled(150_000)   # requests/day -- the scale at which a per-request rounding error becomes a budget line
costs([("big model",   P.cost(in_t, out_t, "big")),
       ("small model", P.cost(in_t, out_t, "small"))], volume_per_day=VOL)

# --- the average is a lie ----------------------------------------------------
# A LABELLED SYNTHETIC distribution: most requests are one cheap turn, a few are
# long agentic runs. The shape is the finding, not these particular draws.
# Measure your own distribution; it is the first thing recipe 01 asks for.
runs = [in_t + out_t] * 94 + [ (in_t + out_t) * 12 ] * 5 + [ (in_t + out_t) * 180 ]
per  = [P.cost(r * 0.9, r * 0.1, "big") for r in runs]
per.sort()

mean, median = statistics.mean(per), statistics.median(per)
p99 = per[int(len(per) * 0.99)]
top1_share = per[-1] / sum(per) * 100

note(f"""
100 requests, same service, cost per request:
median {money(median)}      mean {money(mean)}      P99 {money(p99)}
mean / median = {mean/median:.1f}x       the single most expensive request is {top1_share:.0f}% of total spend
""")

verdict(f"""
The mean is {mean/median:.1f}x the median, so a budget built on the mean is
wrong for almost every request AND wrong for the ones that matter. Track the
distribution, alert on P99, and attribute spend per feature before optimising
anything. It is also why recipe 11 measures each lever's marginal value instead
of adding the headline percentages together.
""")
headline(0.0, 0.0)
