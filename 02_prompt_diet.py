#!/usr/bin/env python3
"""RECIPE 02 - Put the system prompt on a diet.

The cheapest lever in the book, and the only one that costs nothing to try: the
system prompt ships on every single request, so a word removed is a word removed
a hundred and fifty thousand times a day. Both prompts below do the same job;
the second says it once instead of three times.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, count, pct
import prices as P

banner(2, "Put the system prompt on a diet", "input side - free, no quality risk")

BEFORE = """You are an extremely helpful, knowledgeable, and professional customer
support assistant working for an online retail company that sells clothing,
footwear, and sporting goods to customers all around the world.

Your primary role and responsibility is to assist customers with any questions
they may have. Customers may ask you about their orders, about shipping and
delivery, about returns and exchanges, about refunds, or about whether a
particular product is currently available in stock.

Please always make sure to be polite, courteous, friendly, and professional in
every single one of your responses to the customer. It is very important that
you maintain a professional tone at all times.

If you do not know the answer to a question that a customer asks you, then you
should say that you do not know the answer, and you should offer to escalate the
conversation to a human support agent who may be able to help further.

It is extremely important that you never invent or make up any information. In
particular, you must never invent order numbers, you must never invent tracking
numbers, you must never invent delivery dates, and you must never invent refund
amounts. If you do not have this information available to you, do not guess.

Please remember to always be polite and professional, and please remember never
to invent any information that you do not actually have."""

AFTER = """Customer support for an online retailer: orders, shipping, returns,
refunds, stock.

Be professional. If you do not know, say so and offer escalation.
Never invent order numbers, tracking numbers, dates or amounts."""

b, a = count(BEFORE), count(AFTER)
USER, OUT = 27, 108          # unchanged by this lever -- measured in recipe 01

note(f"""
Same instructions, {pct(b, a):.0f}% fewer tokens. What came out:
- three repetitions of "be polite and professional" -> one
- four sentences forbidding invented data -> one clause with a list
- the company backstory the model never needed to answer a shipping question
""")

tokens([("verbose system prompt", b + USER, OUT),
        ("same job, said once",   a + USER, OUT)])

VOL = 150_000
c_before = P.cost(b + USER, OUT, "big")
c_after  = P.cost(a + USER, OUT, "big")
costs([("verbose", c_before), ("dieted", c_after)], volume_per_day=VOL)

saving = (c_before - c_after) * VOL * 30
verdict(f"""
The token cut is {pct(b, a):.0f}% on the system prompt but only
{pct(b + USER + OUT, a + USER + OUT):.0f}% on the request, because the output is
untouched and output costs {P.OUTPUT_PREMIUM:.0f}x more per token. That is the
trap in this lever: prompt dieting is free and safe, and it is still the SMALL
half of the bill. Recipe 03 goes after the expensive half.

An afternoon's work, no quality risk, no architecture change.
""")
headline(-pct(b + USER + OUT, a + USER + OUT), -pct(c_before, c_after), saving)
