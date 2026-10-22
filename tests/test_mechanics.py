"""Pin the published provider MECHANICS to literals. Rates stay free.

Every other test here derives its expectation from the same constant the code
reads, so changing that constant moves both sides and nothing fails. An audit
proved it: CACHE_READ could be changed from 0.10 to 0.40 and all 132 other
assertions still passed.

That is the right behaviour for RATES -- they move constantly, they are
overridable by environment variable, and a test that hardcoded $3.00 would
break the moment someone priced these recipes against their own card.

It is the wrong behaviour for MECHANICS. prices.py puts it plainly: "Rates
move; mechanics have held." The cache read multiplier, the write premium, the
1,024-token minimum, the batch discount and the long-context step are published
provider behaviour, not prices. Changing one silently rewrites the conclusion of
half the recipes -- recipe 05's break-even, recipe 07's whole premise, recipe
16's cliff -- so each is pinned here with the reasoning attached.

If a provider genuinely changes one of these, this file is where you record it,
deliberately, with a date. That is the point: a mechanic should cost you a
conversation, not a silent diff.

    python3 recipes/tests/test_mechanics.py
"""
import math
import pathlib
import sys
import unittest


# Works from either layout: tests/ beside the recipes (this repo), or tests/ at
# the root with the recipes under recipes/ (the published extract).
_UP = pathlib.Path(__file__).resolve().parent.parent
RECIPES = _UP if (_UP / "prices.py").exists() else _UP / "recipes"
TOOLSDIR = _UP / "tools" if (_UP / "tools").exists() else RECIPES / "tools"
sys.path.insert(0, str(RECIPES))
sys.path.insert(0, str(TOOLSDIR))

import prices as P



class PublishedMechanics(unittest.TestCase):
    """Literals on purpose. See the module docstring before changing one."""

    def test_a_cache_hit_is_billed_at_one_tenth_of_the_input_rate(self):
        """Recipe 05's whole saving, and the 0.9x figure every cache claim rests on."""
        self.assertEqual(P.CACHE_READ, 0.10)

    def test_a_cache_write_costs_a_quarter_more_than_an_uncached_call(self):
        """The premium that has to be earned back; without it there is no break-even."""
        self.assertEqual(P.CACHE_WRITE, 1.25)

    def test_the_minimum_cacheable_prefix_is_1024_tokens(self):
        """Below this nothing caches at all -- the failure prefix_lint refuses to price around."""
        self.assertEqual(P.CACHE_MIN, 1024)

    def test_the_batch_tier_is_half_price(self):
        """Recipe 07 is entirely this number."""
        self.assertEqual(P.BATCH, 0.50)

    def test_google_writes_a_cache_at_standard_price_not_a_premium(self):
        """The vendor exception recipe 05 carries: no premium means no break-even to clear."""
        self.assertEqual(P.CACHE_WRITE_GOOGLE, 1.00)

    def test_the_long_context_step_doubles_at_two_hundred_thousand(self):
        """Recipe 16 is a step function; a gradient here would make it a different recipe."""
        self.assertEqual(P.CONTEXT_THRESHOLD, 200_000)
        self.assertEqual(P.CONTEXT_MULTIPLIER, 2.0)

    def test_output_costs_five_times_input_on_both_tiers(self):
        """Recipe 03's reason for existing: shaping output beats shaping input."""
        for tier in ("big", "small"):
            pin, pout = P.MODELS[tier]
            self.assertAlmostEqual(pout / pin, 5.0, places=6, msg=tier)


class MechanicsDriveTheConclusions(unittest.TestCase):
    """The pins above only matter because these conclusions follow from them."""

    def test_the_cache_break_even_is_one_hit(self):
        """Stated as two, a profitable workload gets rejected. Recipe 05 computes it."""
        premium = P.CACHE_WRITE - 1.0
        saved_per_hit = 1.0 - P.CACHE_READ
        self.assertEqual(math.ceil(premium / saved_per_hit), 1)

    def test_one_token_over_the_threshold_reprices_the_whole_request(self):
        """A step, not a slope: the multiplier applies to every token, not the excess."""
        below = P.cost(P.CONTEXT_THRESHOLD - 1, 100, "big")
        above = P.cost(P.CONTEXT_THRESHOLD, 100, "big")
        self.assertAlmostEqual(above / below, P.CONTEXT_MULTIPLIER, places=2)

    def test_caching_changes_the_price_and_never_the_token_count(self):
        """The claim the whole set rests on, and the one recipe 11 used to contradict."""
        import models as M
        plain_tok, plain_cost = M.stack_request(cache=False)
        cached_tok, cached_cost = M.stack_request(cache=True)
        self.assertEqual(plain_tok, cached_tok, "caching must not move the token count")
        self.assertLess(cached_cost, plain_cost, "caching must move the price")

    def test_a_cached_request_over_the_cliff_still_pays_the_step(self):
        """Pricing the cached and uncached halves separately let both slip under it."""
        over = P.CONTEXT_THRESHOLD + 50_000
        full = P.cost_with_cache(over, 500, over // 2, "big")
        halves = (P.cost(over - over // 2, 500, "big")
                  + P.cost(int(over // 2 * P.CACHE_READ), 0, "big"))
        self.assertGreater(full, halves)


class RatesMustStayFree(unittest.TestCase):
    """The other half of the contract: pinning mechanics must not pin prices."""

    def test_rates_are_overridable_and_nothing_here_pins_them(self):
        """A reader pricing these against their own card must not fail this suite."""
        import os
        import importlib
        os.environ["PRICE_IN"] = "7.77"
        try:
            importlib.reload(P)
            self.assertAlmostEqual(P.MODELS["big"][0], 7.77, places=6)
            self.assertEqual(P.CACHE_READ, 0.10)      # mechanic, unaffected
        finally:
            del os.environ["PRICE_IN"]
            importlib.reload(P)
        self.assertAlmostEqual(P.MODELS["big"][0], 3.00, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
