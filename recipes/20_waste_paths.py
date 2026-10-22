#!/usr/bin/env python3
"""RECIPE 20 - Retries, timeouts and abandoned streams: paying for nothing.

Every other recipe makes a successful request cheaper. This one is about the
requests that produce nothing and are billed in full anyway. It is the only
lever that costs no quality at all, and most teams have never measured it.

Three mechanics, each worse than it looks:

  A TIMEOUT IS NOT A FAILURE TO BILL. Tokens are counted when the provider
  accepts the request. If your client gives up at 30s and the model finishes at
  35s, that work happened and you are paying for it. Retry and you pay twice
  for one answer.

  RETRY LAYERS MULTIPLY. The SDK retries 3 times. Your wrapper retries 3 times.
  That is 9 billed attempts, not 3 -- and nobody wrote "9" anywhere.

  AN ABANDONED STREAM IS STILL GENERATED. Tokens produced before the user
  closed the tab are billed. Cancellation is best-effort; the model may keep
  going briefly after you disconnect.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct, scaled
import prices as P

banner(20, "Retries, timeouts and abandoned streams", "waste - no quality cost to fix")

IN_TOK, OUT_TOK, VOL = 3_200, 900, scaled(120_000)
one = P.cost(IN_TOK, OUT_TOK, "big")

# Observed-ish operating conditions. All ASSUMPTIONS -- the point is the shape
# and the arithmetic; your own numbers come from your error and timeout logs.
HARD_FAIL   = 0.011   # 5xx before any generation: input billed, no output
TIMEOUT     = 0.023   # client gave up; the model finished anyway, billed in full
ABANDON     = 0.065   # user closed the tab mid-stream
ABANDON_PCT = 0.55    # share of the output already generated when they left
SDK_RETRIES, APP_RETRIES = 3, 3

note(f"""
One successful request costs {money(one)}. Per 1,000 requests, on these
assumptions:
  {HARD_FAIL*1000:>5.0f} hard failures before generation  (input billed, no output)
  {TIMEOUT*1000:>5.0f} client timeouts on work that COMPLETED (billed in full, then retried)
  {ABANDON*1000:>5.0f} streams abandoned mid-answer      ({ABANDON_PCT:.0%} of output already paid for)
""")

in_only = P.cost(IN_TOK, 0, "big")
partial = P.cost(IN_TOK, OUT_TOK * ABANDON_PCT, "big")

waste_fail    = HARD_FAIL * in_only
waste_timeout = TIMEOUT * one            # the completed-but-discarded first answer
waste_abandon = ABANDON * partial
good          = (1 - HARD_FAIL - TIMEOUT - ABANDON) * one
blended       = good + waste_fail + waste_timeout + waste_abandon + TIMEOUT * one

print("  WHERE THE MONEY GOES, PER REQUEST")
print(f"  {'':34} {'$/request':>12} {'share':>8}")
for label, v in (("answers a user actually got", good),
                 ("hard failures (input billed)", waste_fail),
                 ("timed-out work, discarded", waste_timeout),
                 ("the retry of that same work", TIMEOUT * one),
                 ("abandoned streams", waste_abandon)):
    print(f"  {label:34} {money(v):>12} {v/blended*100:>7.1f}%")
print(f"  {'TOTAL':34} {money(blended):>12}")
print()

waste = blended - good
note(f"""
{money(waste)} of every {money(blended)} -- {waste/blended*100:.0f}% -- buys nothing.
At {VOL:,} requests/day that is {money(waste * VOL * 30)}/month for output no
human ever read.
""")

# --- the retry layers --------------------------------------------------------
print("  STACKED RETRY LAYERS, on a request that keeps timing out")
print(f"  {'configuration':34} {'attempts':>9} {'billed':>12}")
for label, n in (("one layer, 3 attempts", SDK_RETRIES),
                 ("SDK 3 x app 3 (the common accident)", SDK_RETRIES * APP_RETRIES),
                 ("plus a gateway retry", SDK_RETRIES * APP_RETRIES * 2)):
    print(f"  {label:34} {n:>9} {money(one * n):>12}")
print()
note("""
Nobody configures nine attempts. Two teams each configure three, in different
layers, and the multiplication is invisible until the invoice. Count your retry
layers before tuning any of them.
""")

tokens([("a successful request", IN_TOK, OUT_TOK),
        ("the same request, timed out and retried", IN_TOK * 2, OUT_TOK * 2)])

fixed = good + HARD_FAIL * in_only + 0.25 * (waste_timeout + TIMEOUT * one) + 0.3 * waste_abandon

# The same arithmetic in TOKENS, because fixing waste removes whole billed
# calls -- this lever genuinely does cut tokens, unlike the price levers.
_full = IN_TOK + OUT_TOK
tok_today = ((1 - HARD_FAIL - TIMEOUT - ABANDON) * _full
             + HARD_FAIL * IN_TOK
             + TIMEOUT * _full * 2                      # discarded, then retried
             + ABANDON * (IN_TOK + OUT_TOK * ABANDON_PCT))
tok_fixed = ((1 - HARD_FAIL - TIMEOUT - ABANDON) * _full
             + HARD_FAIL * IN_TOK
             + TIMEOUT * _full * 2 * 0.25
             + ABANDON * (IN_TOK + OUT_TOK * ABANDON_PCT) * 0.3)
costs([("as it runs today", blended), ("waste paths fixed", fixed)], volume_per_day=VOL)

saving = (blended - fixed) * VOL * 30
verdict(f"""
{pct(blended, fixed):.0f}% off and {pct(tok_today, tok_fixed):.0f}% fewer tokens,
{money(saving)}/month, with NO quality trade at all. There is no accuracy to
lose here -- this is work nobody received. Unlike the price levers, fixing
waste removes whole billed calls, so the token column moves too.

WHAT ACTUALLY FIXES IT:
- LENGTHEN THE TIMEOUT BEFORE ADDING A RETRY. A timeout that fires on work that
  would have completed converts one bill into two and fixes nothing. Set it from
  your p99 generation time, not from a default.
- SEND AN IDEMPOTENCY KEY where the provider supports one, so a retry of an
  accepted request cannot be billed as a second generation.
- COUNT YOUR RETRY LAYERS. Pick ONE layer to own retries and disable the others.
- PROPAGATE CANCELLATION on disconnect. It is best-effort and the provider may
  bill a little past the abort, but it is the difference between paying for
  half an answer and paying for all of it.
- TREAT stop_reason AND ERROR CLASS AS COST METRICS, not reliability metrics.
  tools/meter.py records outcome per call for exactly this reason.

THE REASON THIS IS LAST AND NOT FIRST: it is invisible. Every other lever shows
up as a smaller number on a dashboard. This one shows up as a number that was
never supposed to be there, and you only find it by instrumenting failures --
which is recipe 01, again.
""")
headline(-pct(tok_today, tok_fixed), -pct(blended, fixed), saving)
