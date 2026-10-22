"""Rates, in USD per 1M tokens, and the multipliers the providers publish.

PROVENANCE. The $3/$15 big-model and $0.80/$4.00 small-model pair is a
realistic frontier/small pair, not a quote. Confirm it against the live pricing
page before putting a dollar figure in front of anyone.

The MULTIPLIERS are different in kind: each is a published provider mechanic,
documented by the providers themselves, and they are what actually drive every
result here. Rates move; mechanics have held.
"""

PRICE_DATE = "2026-10-21"      # when these rates were last checked
RATES_ARE  = "illustrative"    # never "quoted"

def _env(name, default):
    """Let a reader price these recipes against their own rate card.

        PRICE_IN=2.50 PRICE_OUT=10 python3 recipes/02_prompt_diet.py

    Every figure in every recipe is recomputed from these, because nothing is
    hardcoded downstream -- which is the point of putting the rates in one file.
    """
    import os
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


MODELS = {
    # name:        (input $/1M, output $/1M)   -- override with PRICE_* env vars
    "big":   (_env("PRICE_IN",       3.00), _env("PRICE_OUT",       15.00)),
    "small": (_env("PRICE_IN_SMALL", 0.80), _env("PRICE_OUT_SMALL",  4.00)),
}

# Output costs 5x input on both tiers. That ratio, not the absolute rate, is why
# recipe 03 (output shape) beats most input-side work.
OUTPUT_PREMIUM = MODELS["big"][1] / MODELS["big"][0]

# --- published mechanics -----------------------------------------------------

CACHE_READ  = 0.10   # cached input billed at 10% of the uncached rate
CACHE_WRITE = 1.25   # Anthropic / OpenAI / Bedrock: writing the cache costs 1.25x
CACHE_MIN   = 1024   # minimum cacheable prefix, per breakpoint
BATCH       = 0.50   # async batch tier: 50% off both directions, ~24h turnaround

# Google is the exception: the write is at STANDARD price
# (1.0x) and the cost moves into time-based storage instead, so on implicit
# caching there is no write premium and therefore no break-even at all.
# Check your provider's own caching docs before porting this arithmetic.
CACHE_WRITE_GOOGLE = 1.00


# --- two mechanics the 2026 price sheets added, both discontinuous ----------

# Reasoning / thinking tokens are billed as OUTPUT -- the expensive side -- and
# are not returned in the response. You pay for text you never see.
REASONING_IS_OUTPUT = True

# The long-context cliff. Past a threshold, EVERY token in the request bills at
# the higher rate, not just the ones past the line. Thresholds differ by vendor
# (200K on several, 272K on others) and at least one vendor bills a 1M window at
# standard rates, so confirm yours before relying on this.
CONTEXT_THRESHOLD = 200_000
CONTEXT_MULTIPLIER = 2.0     # illustrative: the step, not a quoted rate


def context_multiplier(in_tok):
    """1.0 below the threshold, CONTEXT_MULTIPLIER at or above it.

    A step function, deliberately. The whole point is that it is not a gradient:
    one token over the line re-prices the entire request.
    """
    return CONTEXT_MULTIPLIER if in_tok >= CONTEXT_THRESHOLD else 1.0


def cost(in_tok, out_tok, model="big", batch=False):
    """Dollars for one request. The only pricing arithmetic in the repo."""
    pin, pout = MODELS[model]
    if batch:
        pin, pout = pin * BATCH, pout * BATCH
    m = context_multiplier(in_tok)
    return (in_tok / 1e6 * pin + out_tok / 1e6 * pout) * m
