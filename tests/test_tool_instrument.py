#!/usr/bin/env python3
"""Pins the public behaviour of recipes/tools/instrument.py.

The instrument's product is its REFUSALS: it is the thing a client accepts a
savings claim from even though the party being paid measured it. Every rule
below guards one specific way a saving gets overstated, so a regression here is
a commercial defect, not a cosmetic one.

    python3 recipes/tests/test_tool_instrument.py
"""
import pathlib, sys, unittest

# Works from either layout: tests/ beside the recipes (this repo), or tests/ at
# the root with the recipes under recipes/ (the published extract).
_UP = pathlib.Path(__file__).resolve().parent.parent
RECIPES = _UP if (_UP / "prices.py").exists() else _UP / "recipes"
TOOLSDIR = _UP / "tools" if (_UP / "tools").exists() else RECIPES / "tools"
sys.path.insert(0, str(RECIPES))
sys.path.insert(0, str(TOOLSDIR))

import instrument
import models as M


ALL_LEVERS = list(M.LEVERS)


def _inst(baseline_unit=1.00, floor=0.95, quality=0.99):
    i = instrument.Instrument(quality_floor=floor)
    i.set_baseline(unit_cost=baseline_unit, quality=quality)
    return i


class QualityFloor(unittest.TestCase):

    def test_quality_below_the_floor_claims_nothing_even_when_unit_cost_halved(self):
        """Cheapness bought by degrading output is a cost moved where the token bill cannot see it."""
        r = _inst().assess(unit_cost=0.50, volume=100_000, quality=0.80,
                           levers_on=ALL_LEVERS)
        self.assertFalse(r["claimable"])
        self.assertEqual(r["value"], 0.0)
        self.assertIn("floor", r["reason"])
        # The halved unit cost is real and is still not claimed: rule 5 is
        # checked before the cost test, so quality cannot be traded for value.
        self.assertIn("0.800", r["reason"])

    def test_quality_exactly_at_the_default_floor_is_still_claimable(self):
        """The refusal must trigger BELOW the agreed floor, not at it, or the floor is really floor+epsilon."""
        i = instrument.Instrument()               # default floor
        self.assertEqual(i.floor, 0.95)
        i.set_baseline(unit_cost=1.00, quality=0.99)
        r = i.assess(unit_cost=0.60, volume=1_000, quality=0.95,
                     levers_on=["cache"])
        self.assertTrue(r["claimable"])


class UnitCostMustHaveFallen(unittest.TestCase):

    def test_unit_cost_equal_to_or_above_baseline_is_refused(self):
        """A flat or worse unit cost has nothing to certify; `>=` must not soften to `>`."""
        i = _inst(baseline_unit=1.00)
        for unit in (1.00, 1.20, 5.00):
            with self.subTest(unit_cost=unit):
                r = i.assess(unit_cost=unit, volume=1_000, quality=0.99,
                             levers_on=ALL_LEVERS)
                self.assertFalse(r["claimable"])
                self.assertEqual(r["value"], 0.0)
                self.assertIn("not below baseline", r["reason"])
        # ...and the smallest genuine fall is claimable, so the boundary sits
        # exactly at equality rather than somewhere above it.
        r = i.assess(unit_cost=0.999999, volume=1_000, quality=0.99,
                     levers_on=["cache"])
        self.assertTrue(r["claimable"])

    def test_a_refusal_carries_zero_value_and_no_attribution_to_quote(self):
        """A refusal that still shipped per-lever credits would be quoted as a claim anyway."""
        i = _inst(baseline_unit=1.00)
        refusals = [
            i.assess(unit_cost=0.10, volume=1_000, quality=0.10, levers_on=ALL_LEVERS),
            i.assess(unit_cost=1.00, volume=1_000, quality=0.99, levers_on=ALL_LEVERS),
        ]
        for r in refusals:
            with self.subTest(reason=r["reason"][:40]):
                self.assertEqual(r["value"], 0.0)
                self.assertNotIn("attribution", r)
                self.assertNotIn("counterfactual", r)
                self.assertNotIn("unit_reduction", r)


class SuccessfulOutputDenominator(unittest.TestCase):

    def test_a_period_that_solved_nothing_refuses_to_report_a_unit_cost(self):
        """Dividing by attempted requests would let a period that solved nothing look cheap."""
        for solved in (0, -5):
            with self.subTest(solved=solved):
                with self.assertRaises(ValueError) as ctx:
                    instrument.Instrument.unit_cost(5_000.0, solved)
                self.assertIn("undefined", str(ctx.exception))
        self.assertAlmostEqual(instrument.Instrument.unit_cost(5_000.0, 1_000),
                               5.0, places=9)

    def test_spend_falling_while_solved_work_falls_faster_is_refused(self):
        """"We spent 10% less" is the overclaim rules 1 and 2 exist to kill: failing more often is not saving."""
        i = _inst(baseline_unit=instrument.Instrument.unit_cost(1_000.0, 1_000))
        worse = instrument.Instrument.unit_cost(900.0, 800)   # 10% less spend
        self.assertGreater(worse, 1.0)
        r = i.assess(unit_cost=worse, volume=800, quality=0.99,
                     levers_on=ALL_LEVERS)
        self.assertFalse(r["claimable"])
        self.assertIn("not below baseline", r["reason"])


class Counterfactual(unittest.TestCase):

    def test_value_and_counterfactual_are_both_priced_at_current_volume(self):
        """The only number that survives a growing service: spend rose 80% and the saving is still real."""
        i = _inst(baseline_unit=1.00)
        small = i.assess(unit_cost=0.60, volume=1_000, quality=0.99,
                         levers_on=["cache"])
        grown = i.assess(unit_cost=0.60, volume=3_000, quality=0.99,
                         levers_on=["cache"])
        self.assertAlmostEqual(small["value"], 400.0, places=6)
        self.assertAlmostEqual(grown["value"], 1_200.0, places=6)
        # "What you would have spent" is the baseline unit cost at TODAY's
        # volume, so it grows with the service too.
        self.assertAlmostEqual(grown["counterfactual"], 3_000.0, places=6)
        self.assertAlmostEqual(grown["unit_reduction"], 40.0, places=6)
        # Total-spend accounting would report this period as a LOSS: baseline
        # spend 1,000 against current spend 1,800. The instrument certifies
        # 1,200 of saving anyway, because unit cost is what moved.
        self.assertGreater(0.60 * 3_000, 1.00 * 1_000)


class IncrementalAttribution(unittest.TestCase):

    def test_credits_sum_exactly_to_the_certified_value(self):
        """The identity that stops four teams invoicing the same dollar of saving."""
        i = _inst(baseline_unit=1.00)
        for volume in (1, 1_000, 420_000 * 30, 9_000_000):
            with self.subTest(volume=volume):
                r = i.assess(unit_cost=0.3125, volume=volume, quality=0.99,
                             levers_on=ALL_LEVERS)
                credits = r["attribution"]["credits"]
                self.assertEqual(set(credits), set(ALL_LEVERS))
                self.assertLessEqual(abs(sum(credits.values()) - r["value"]),
                                     max(1e-9, abs(r["value"]) * 1e-12))

    def test_credits_are_an_apportionment_of_the_total_not_the_raw_marginals(self):
        """Marginal figures understate the joint effect; publishing them raw would under-credit every lever."""
        r = _inst(baseline_unit=1.00).assess(unit_cost=0.3125, volume=10_000,
                                             quality=0.99, levers_on=ALL_LEVERS)
        a = r["attribution"]
        raw = sum(a["marginal"].values())
        # Each lever's marginal excludes what the others already took, so the
        # raw sum is a FRACTION of the joint effect -- and the tool reports that
        # factor instead of burying it.
        self.assertLess(a["overstatement"], 1.0)
        self.assertGreater(a["overstatement"], 0.0)
        # Credits are the certified value apportioned in marginal proportion.
        for lever, marginal in a["marginal"].items():
            with self.subTest(lever=lever):
                self.assertAlmostEqual(a["credits"][lever] / r["value"],
                                       marginal / raw, places=9)

    def test_a_two_lever_period_credits_only_those_two_and_still_reconciles(self):
        """A lever that was not on must not be handed a share of someone else's work."""
        r = _inst(baseline_unit=1.00).assess(unit_cost=0.50, volume=10_000,
                                             quality=0.99,
                                             levers_on=["trunc", "route"])
        credits = r["attribution"]["credits"]
        self.assertEqual(set(credits), {"trunc", "route"})
        self.assertAlmostEqual(sum(credits.values()), r["value"], places=6)
        for lever in ("cache", "batch"):
            self.assertNotIn(lever, credits)


class LayerSplit(unittest.TestCase):

    def test_caching_and_batching_land_in_application_and_rate_stays_zero(self):
        """Booking cache and batch as rate drops the two largest levers from a 50% share to 20%."""
        self.assertEqual(instrument.LAYER["cache"], "application")
        self.assertEqual(instrument.LAYER["batch"], "application")
        self.assertEqual(set(instrument.LAYER.values()), {"application"})
        r = _inst(baseline_unit=1.00).assess(unit_cost=0.50, volume=10_000,
                                             quality=0.99,
                                             levers_on=["cache", "batch"])
        by_layer = r["attribution"]["by_layer"]
        # Reported separately and never summed: a code change is application
        # even when its token count does not fall, and no commitment is in play
        # here, so the rate line must be empty rather than absorbing half.
        self.assertEqual(sorted(by_layer), ["application", "rate"])
        self.assertEqual(by_layer["rate"], 0.0)
        self.assertAlmostEqual(by_layer["application"], r["value"], places=6)

    def test_an_unknown_lever_is_never_silently_credited(self):
        """Silently ignoring an unmodelled lever would certify the full value with part of it unattributed."""
        i = _inst(baseline_unit=1.00)
        with self.assertRaises(TypeError):
            i.assess(unit_cost=0.50, volume=10_000, quality=0.99,
                     levers_on=["commit"])     # a rate-layer term, not modelled
        # Nor may a lever-less period certify value with nothing behind it: the
        # reconciliation identity fires rather than returning an unattributed
        # claim. (Rough edge, not a wrong number -- see the summary.)
        with self.assertRaises(AssertionError):
            i.assess(unit_cost=0.50, volume=10_000, quality=0.99, levers_on=[])


if __name__ == "__main__":
    unittest.main(verbosity=2)
