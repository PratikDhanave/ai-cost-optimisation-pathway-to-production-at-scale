#!/usr/bin/env python3
"""RECIPE 19 - Tool schemas: the tax you pay on every call, used or not.

Every tool you register ships its full JSON schema in the context on every
single request, whether the model calls it or not. Connect five MCP servers and
you can be sending tens of thousands of tokens of type definitions before the
model has done any work at all -- on every turn, of every conversation, forever.

This is the only lever here where ADDING A FEATURE silently raises the price of
every request in the system, including the overwhelming majority that never
touch the thing you added. Nobody reviews a new tool as a cost change.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(19, "Tool schemas and the per-call tax", "fixed overhead - billed whether used or not")

# Reported sizes: a light tool is roughly 100 tokens of schema, a heavy one
# roughly 1,000 -- the difference is entirely parameter descriptions, nested
# objects and enums. Treat as the right order of magnitude, not a measurement.
LIGHT, HEAVY = 100, 1_000
PROMPT, USER, OUT = 700, 180, 420
VOL, STEPS = 60_000, 12

def schema_tokens(n_light, n_heavy):
    return n_light * LIGHT + n_heavy * HEAVY

SETUPS = [
    ("no tools",                 0,  0),
    ("8 tools, mostly light",    6,  2),
    ("20 tools",                14,  6),
    ("54 tools, 5 MCP servers", 30, 24),
]

note(f"""
A light tool is about {LIGHT} tokens of schema, a heavy one about {HEAVY:,}.
The schema sits in the context on EVERY request -- it is not sent once per
session and it is not sent only when the tool is used.
""")

rows = [(name, PROMPT + USER + schema_tokens(l, h), OUT) for name, l, h in SETUPS]
tokens(rows)

print("  WHAT SHARE OF THE REQUEST IS SCHEMA")
print(f"  {'setup':26} {'schema tok':>11} {'share of input':>15} {'$/request':>12}")
for (name, l, h), (_, in_tok, _) in zip(SETUPS, rows):
    s = schema_tokens(l, h)
    print(f"  {name:26} {s:>11,} {s/in_tok*100:>14.1f}% "
          f"{money(P.cost(in_tok, OUT, 'big')):>12}")
print()

cs = [(name, P.cost(i, o, "big")) for name, i, o in rows]
costs(cs, volume_per_day=VOL)

# --- the agent multiplier ----------------------------------------------------
big = schema_tokens(*SETUPS[-1][1:])
note(f"""
NOW PUT IT IN AN AGENT. Recipe 10's loop re-reads the context every step, so a
{STEPS}-step task carries the schema {STEPS} times:
  {big:,} tokens x {STEPS} steps = {big*STEPS:,} tokens of type definitions
  for ONE task, before a single useful word is written.
""")

# --- the cost of adding one tool --------------------------------------------
one_heavy = P.cost(HEAVY, 0, "big") * VOL * 30
note(f"""
THE REVIEW NOBODY DOES: adding ONE heavy tool costs {money(one_heavy)}/month at
{VOL:,} requests/day -- paid on every request, including the ~95% that never
call it. In an agent it is {money(one_heavy*STEPS)}/month, because the schema is
re-sent on every step. A pull request that adds a tool is a pricing change.
""")

trimmed = PROMPT + USER + schema_tokens(8, 2)   # only what this feature can use
full = rows[-1][1]
saving = (P.cost(full, OUT, "big") - P.cost(trimmed, OUT, "big")) * VOL * 30

verdict(f"""
Loading only the 10 tools a given feature can actually use, instead of all 54:
{pct(full + OUT, trimmed + OUT):.0f}% fewer tokens and {money(saving)}/month.

FOUR FIXES, cheapest first:
1. SCOPE THE TOOLSET PER FEATURE OR PER SESSION. A support agent does not need
   the deployment tools. This is configuration, not engineering, and it is
   usually the whole win.
2. COMPRESS THE SCHEMAS. Strip descriptions and enums, flatten nested objects.
   The model needs the shape; it rarely needs your prose.
3. LOAD LAZILY. Let the model ask for a tool group when it discovers it needs
   one, rather than shipping everything on the chance it might.
4. REPLACE SCHEMAS WITH CODE. Giving the model a sandboxed interpreter and a
   small API surface removes the per-tool schema entirely. Reported reductions
   are large; the trade is a sandbox you now have to secure and operate.

AND CACHE WHAT IS LEFT. The tool block is stable and usually well over the
{P.CACHE_MIN:,}-token minimum, which makes it the ideal cache prefix (recipe 05)
-- provided it sits BEFORE anything per-request and you do not regenerate the
schema order on each call. A tool list that reorders itself is a prefix that
changes, and that is recipe 05's failure mode with a different cause.
""")
headline(-pct(full + OUT, trimmed + OUT),
         -pct(P.cost(full, OUT, "big"), P.cost(trimmed, OUT, "big")), saving)
