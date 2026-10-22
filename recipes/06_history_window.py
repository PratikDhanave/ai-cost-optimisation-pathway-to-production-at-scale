#!/usr/bin/env python3
"""RECIPE 06 - Conversation history grows quadratically. Window it.

A chat turn re-sends every previous turn. Twenty turns is not twenty turns of
cost, it is two hundred and ten -- and nobody notices, because each individual
request looks reasonable. This is the mechanism behind most "the bill tripled
and we did not ship anything" incidents.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, pct, money, scaled
import prices as P

banner(6, "Window the conversation history", "structural - stops quadratic growth")

SYS, PER_TURN, TURNS, OUT = 800, 350, 20, 250

def run(window=None, cache=False):
    """Total input tokens billed across a whole conversation."""
    billed, history = 0, []
    for t in range(TURNS):
        keep = history if window is None else history[-window:]
        prefix = SYS + sum(keep)
        # a cached stable prefix is still SENT -- it is billed at 0.1x, not dropped
        billed += (SYS * P.CACHE_READ + sum(keep)) if (cache and t) else prefix
        billed += PER_TURN
        history.append(PER_TURN * 2)        # the turn plus its reply join the history
    return billed

full      = run()
windowed  = run(window=6)
linear    = (SYS + PER_TURN) * TURNS

note(f"""
A {TURNS}-turn conversation, {SYS}-token system prompt, {PER_TURN} tokens per turn.
if each turn cost only its own tokens   {linear:>9,} tokens
what a full-history conversation bills  {full:>9,} tokens   {full/linear:.1f}x
last-6-turns window                     {windowed:>9,} tokens
""")

out_total = OUT * TURNS
tokens([("full history",    full,     out_total),
        ("last 6 turns",    windowed, out_total)])

CONV_PER_DAY = scaled(8_000)
costs([("full history", P.cost(full, out_total, "big")),
       ("last 6 turns", P.cost(windowed, out_total, "big")),
       ("windowed + cached prefix", P.cost(run(window=6, cache=True), out_total, "big"))],
      volume_per_day=CONV_PER_DAY, unit="conversation")

saving = (P.cost(full, out_total, "big") - P.cost(windowed, out_total, "big")) * CONV_PER_DAY * 30

verdict(f"""
Windowing to six turns removes {pct(full, windowed):.0f}% of input tokens and
{money(saving)}/month at {CONV_PER_DAY:,} conversations/day.

ORDER OF OPERATIONS. Window BEFORE you cache. Caching a history that grows every
turn means re-writing the cache every turn and paying the write premium
{TURNS} times; the prefix must be stable for caching to pay, and a growing
history is the definition of unstable. Window first, then cache the part that
genuinely does not move -- the third row above, which is the two levers composed
in the right order.

WHAT BREAKS. Six turns is a guess. A user who refers back to something said
twelve turns ago now gets a model that has forgotten it, and the cost of that
lands in re-asked questions and abandoned sessions. Summarise the dropped
history into a compact running state instead of discarding it, and measure task
completion, not tokens, when you choose the window.
""")
headline(-pct(full + out_total, windowed + out_total),
         -pct(P.cost(full, out_total, "big"), P.cost(windowed, out_total, "big")), saving)
