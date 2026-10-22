"""The cost models the recipes and the visual demo share.

These live here, imported by every recipe that needs them, for one reason: a
model implemented twice drifts.

Every function takes its rates from prices.py and obeys the published mechanics
-- the cache minimum, the cascade's double-pay, capacity-driven GPU counts. The
recipes narrate these models; they do not reimplement them.
"""
import math
import prices as P

# --- recipe 11: the four-lever stack ----------------------------------------
# One set of inputs, shared by recipe 11 and anything else that needs them.
STACK = dict(prefix=800, history=12_000, truncated=4_000, out=500)
LEVERS = ("trunc", "cache", "route", "batch")


def stack_request(route=False, trunc=False, cache=False, batch=False):
    """Returns (input_tokens_billed, cost) for one request under these levers."""
    history = STACK["truncated"] if trunc else STACK["history"]
    prefix  = STACK["prefix"]
    model   = "small" if route else "big"

    # TOKENS SENT DO NOT CHANGE WHEN YOU CACHE. An earlier version multiplied
    # the prefix by CACHE_READ and returned that as the token count, so recipe
    # 11 reported caching cutting 5.6% of tokens -- contradicting recipe 05 and
    # the whole point of separating the two columns. The discount belongs in
    # the price, which is what cost_with_cache is for.
    in_tok = prefix + history
    cached = prefix if cache else 0
    return round(in_tok), P.cost_with_cache(in_tok, STACK["out"], cached,
                                            model, batch=batch)


def stack_all():
    """Every one of the 16 lever combinations, precomputed."""
    out = {}
    for mask in range(16):
        kw = {l: bool(mask >> i & 1) for i, l in enumerate(LEVERS)}
        tok, cost = stack_request(**kw)
        out["".join("1" if kw[l] else "0" for l in LEVERS)] = dict(
            tokens=tok, out_tokens=STACK["out"], cost=cost, on=kw)
    return out


# --- recipe 12: self-hosting ------------------------------------------------
HOST = dict(in_tok=1_400, out_tok=300, gpu_hourly=3.50, gpu_min=2,
            tok_per_sec=1_100, ops_hours=40, ops_rate=120)


def cap_per_gpu():
    """Requests one accelerator can serve in a month at this model size."""
    return HOST["tok_per_sec"] * 3600 * 730 / (HOST["in_tok"] + HOST["out_tok"])


def selfhost(monthly_req):
    """(gpus, utilisation, fixed_monthly, cost_per_request).

    GPU count follows CAPACITY, not preference -- which is what makes the cost
    a staircase rather than a curve, and why the naive fixed/rate break-even
    reports a volume the hardware cannot physically serve.
    """
    cap = cap_per_gpu()
    gpus = max(HOST["gpu_min"], math.ceil(monthly_req / cap))
    fixed = HOST["gpu_hourly"] * gpus * 730 + HOST["ops_hours"] * HOST["ops_rate"]
    return gpus, monthly_req / (gpus * cap), fixed, fixed / monthly_req


def managed_per_request(model="small"):
    return P.cost(HOST["in_tok"], HOST["out_tok"], model)


def selfhost_floor():
    """The least a self-hosted request can ever cost: one GPU, flat out, no ops."""
    return HOST["gpu_hourly"] * 730 / cap_per_gpu()


def selfhost_breakeven(target_price, step=5_000, limit=20_000_000):
    """First requests/day at which the staircase dips under target_price."""
    for rpd in range(step, limit + 1, step):
        if selfhost(rpd * 30)[3] < target_price:
            return rpd
    return None
