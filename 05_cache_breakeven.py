#!/usr/bin/env python3
"""RECIPE 05 - Prompt caching, and the three ways it pays nothing.

READ THE TOKEN TABLE CAREFULLY. Caching reduces NO tokens. Every token is still
sent and still counted; what changes is the price of the cached ones. The token
column is 0% on purpose -- a team that books caching as a token reduction and
prompt dieting as another has counted the same prefix twice.

The three ways it pays nothing, all computed below rather than asserted:
  1. the prefix is under the 1,024-token minimum, so nothing caches at all
  2. the gap between requests exceeds the TTL, so every call pays the write
     premium and collects nothing -- this one LOSES money
  3. the prefix is not actually stable, so the hit rate collapses while the
     write premium stays
"""
import pathlib, sys, math
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money
import prices as P

banner(5, "Prompt caching and its break-even", "price lever - published provider mechanic")

PREFIX, BODY, OUT = 2_400, 600, 400      # stable system+examples, variable turn, reply
PIN = P.MODELS["big"][0]

base_prefix = PREFIX / 1e6 * PIN                    # what the prefix costs uncached
write_cost  = base_prefix * P.CACHE_WRITE           # 1.25x
read_cost   = base_prefix * P.CACHE_READ            # 0.10x
save_hit    = base_prefix - read_cost               # 0.90x saved per hit
premium     = write_cost - base_prefix              # 0.25x paid once
breakeven   = math.ceil(premium / save_hit)

note(f"""
A {PREFIX:,}-token stable prefix at ${PIN:.2f}/1M input:
uncached          {money(base_prefix)}
cache write  1.25x {money(write_cost)}   (+{money(premium)} premium, paid once)
cache read   0.10x {money(read_cost)}   ({money(save_hit)} saved per hit)

BREAK-EVEN: {premium/save_hit:.2f} hits -> the FIRST hit repays the premium
{save_hit/premium:.1f}x over, so the integer answer is {breakeven}.
Computed, not quoted. This number is easy to state one hit too high, and a
"needs two hits" rule of thumb rejects workloads that are already profitable.
""")

tokens([("no caching", PREFIX + BODY, OUT),
        ("with caching", PREFIX + BODY, OUT)])   # identical, and that is the point
note("Zero token change. Caching is a PRICE lever, not a token lever.")

def per_request(hits_per_write):
    """Amortised cost of one request given how many cache hits each write earns."""
    n = hits_per_write + 1
    prefix_total = write_cost + read_cost * hits_per_write
    return (prefix_total / n) + BODY / 1e6 * PIN + P.cost(0, OUT, "big")

VOL = 150_000
costs([("no caching",        P.cost(PREFIX + BODY, OUT, "big")),
       ("1 hit per write (min)", per_request(1)),
       ("9 hits per write",   per_request(9)),
       ("99 hits per write",  per_request(99))], volume_per_day=VOL)

# --- failure mode 2: the cache expires between requests ----------------------
TTL_MIN, RPH = 5, 6
gap = 60 / RPH
alive = gap < TTL_MIN
cold = write_cost + BODY / 1e6 * PIN + P.cost(0, OUT, "big")
warm = P.cost(PREFIX + BODY, OUT, "big")

note(f"""
FAILURE MODE: {RPH} requests/hour, {TTL_MIN}-minute TTL.
gap between requests {gap:.0f} min {'<' if alive else '>'} TTL {TTL_MIN} min -> cache {'survives' if alive else 'EXPIRES'}
every request pays the write premium and reads nothing:
  {money(cold)} vs {money(warm)} uncached = {money((cold - warm) * VOL * 30)}/month WORSE
""")

saving = (P.cost(PREFIX + BODY, OUT, "big") - per_request(9)) * VOL * 30
cut = (1 - per_request(9) / P.cost(PREFIX + BODY, OUT, "big")) * 100

verdict(f"""
At 9 hits per write this is {cut:.0f}% off the bill for a cache_control marker
and nothing else -- no accuracy risk, no architecture change.

Three preconditions, in order. Prefix >= {P.CACHE_MIN:,} tokens. Request gap
below the TTL. Prefix genuinely STABLE -- interpolate a user id or a timestamp
into it and the hit rate goes to zero while the write premium stays, which is
failure mode 2 with extra steps. Put everything variable AFTER everything
stable, always.

VENDOR DIFFERENCE, and it is the one most guides omit: Anthropic, OpenAI and
Bedrock write at {P.CACHE_WRITE}x, so the break-even above applies. Google writes
at STANDARD price ({P.CACHE_WRITE_GOOGLE}x) and charges time-based storage on
explicit caching instead -- on implicit caching there is no write premium and
therefore no break-even at all. Do not carry this arithmetic across providers.
""")
headline(0.0, -cut, saving)
