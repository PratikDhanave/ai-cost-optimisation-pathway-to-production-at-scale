"""Tests for the cost logic. Standard library only -- no ADK, no API key.

Split deliberately: everything that decides anything lives in cost_core and is
tested here with no framework at all. The ADK glue has its own tests which skip
when google-adk is absent, so this file passes in the same dependency-free CI
job as the recipes.

    python3 recipes/agent/test_cost.py
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cost_core import (Budget, ToolTracker, Usage, cache_is_worth_it, price,
                       read_usage, resolve)


class TestResolve(unittest.TestCase):
    def test_recognises_by_pattern_not_exact_name(self):
        self.assertEqual(resolve("claude-sonnet-5").name, "anthropic-style")
        self.assertEqual(resolve("gpt-5.6-terra").name, "openai-style")
        self.assertEqual(resolve("gemini-2.5-pro").name, "google-style")

    def test_unknown_model_is_unknown_not_a_default(self):
        self.assertIsNone(resolve("llama-4-maverick"))
        self.assertIsNone(resolve(None))


class TestPricing(unittest.TestCase):
    def test_unknown_model_refuses_to_price(self):
        c = price("some-new-model", Usage(1000, 100))
        self.assertFalse(c.known)
        self.assertIn("no rates registered", c.reason)

    def test_no_usage_metadata_refuses_to_price(self):
        self.assertFalse(price("claude-sonnet-5", None).known)

    def test_cached_tokens_are_billed_at_the_read_rate(self):
        full = price("claude-sonnet-5", Usage(10_000, 0))
        half = price("claude-sonnet-5", Usage(10_000, 0, cached_in=5_000))
        self.assertLess(half.usd, full.usd)
        # 5k uncached at 1.0x + 5k cached at 0.1x = 55% of fully uncached
        self.assertAlmostEqual(half.usd / full.usd, 0.55, places=6)

    def test_missing_cached_field_is_an_upper_bound_not_zero(self):
        """None and 0 must not collapse: one is 'unknown', one is 'none cached'."""
        unknown = price("claude-sonnet-5", Usage(10_000, 0, cached_in=None))
        self.assertTrue(unknown.known)
        self.assertIn("UPPER bound", unknown.reason)
        stated = price("claude-sonnet-5", Usage(10_000, 0, cached_in=0))
        self.assertEqual(unknown.usd, stated.usd)
        self.assertEqual(stated.reason, "")

    def test_rates_can_be_overridden_per_deployment(self):
        c = price("claude-sonnet-5", Usage(1_000_000, 0),
                  rates={"input_per_m": 1.00, "output_per_m": 1.00})
        self.assertAlmostEqual(c.usd, 1.00, places=6)


class TestCacheMechanicsDifferByProvider(unittest.TestCase):
    """The reason a 'generic' cache multiplier would be wrong for somebody."""

    def test_below_the_minimum_nothing_caches(self):
        ok, why = cache_is_worth_it("claude-sonnet-5", 600)
        self.assertFalse(ok)
        self.assertIn("under", why)

    def test_premium_provider_has_a_break_even(self):
        ok, why = cache_is_worth_it("claude-sonnet-5", 4_000)
        self.assertTrue(ok)
        self.assertIn("break-even at 1 hit", why)

    def test_storage_provider_has_no_break_even_at_all(self):
        ok, why = cache_is_worth_it("gemini-2.5-pro", 4_000)
        self.assertTrue(ok)
        self.assertIn("no premium", why)
        self.assertIn("storage", why)

    def test_unknown_model_will_not_guess(self):
        ok, why = cache_is_worth_it("mystery-model", 4_000)
        self.assertFalse(ok)
        self.assertIn("cannot say", why)


class TestUsageExtraction(unittest.TestCase):
    def test_reads_differing_field_names(self):
        for shape in ({"prompt_token_count": 10, "candidates_token_count": 5},
                      {"input_tokens": 10, "output_tokens": 5},
                      {"prompt_tokens": 10, "completion_tokens": 5}):
            u = read_usage(shape)
            self.assertEqual((u.in_tokens, u.out_tokens), (10, 5), shape)

    def test_absent_cached_field_stays_none(self):
        u = read_usage({"input_tokens": 10, "output_tokens": 5})
        self.assertIsNone(u.cached_in)
        self.assertFalse(u.cached_known)

    def test_no_usable_fields_returns_none(self):
        self.assertIsNone(read_usage({"something_else": 1}))
        self.assertIsNone(read_usage(None))


class TestReasoningTokens(unittest.TestCase):
    """Found by a live run, not by any offline test.

    A current model returned candidates=7 with thoughts=230: seven visible
    tokens, and two hundred and thirty more billed as output that are never
    returned. Reading the output field alone understated the turn 34x.
    """

    def test_reasoning_is_reconciled_from_the_total(self):
        u = read_usage({"prompt_token_count": 87, "candidates_token_count": 7,
                        "thoughts_token_count": 230, "total_token_count": 324})
        self.assertEqual(u.out_tokens, 237)
        self.assertEqual(u.hidden_out, 230)

    def test_a_provider_that_already_includes_it_is_not_double_counted(self):
        u = read_usage({"prompt_tokens": 87, "completion_tokens": 237,
                        "total_tokens": 324})
        self.assertEqual(u.out_tokens, 237)
        self.assertEqual(u.hidden_out, 0)

    def test_no_total_means_no_adjustment(self):
        u = read_usage({"input_tokens": 87, "output_tokens": 7})
        self.assertEqual(u.out_tokens, 7)
        self.assertEqual(u.hidden_out, 0)

    def test_the_cost_difference_is_the_point(self):
        g = {"prompt_token_count": 87, "candidates_token_count": 7,
             "thoughts_token_count": 230, "total_token_count": 324}
        self.assertGreater(price("gemini-3.8-flash", read_usage(g)).usd,
                           price("gemini-3.8-flash", Usage(87, 7)).usd * 5)


class TestToolPruning(unittest.TestCase):
    def test_nothing_is_pruned_before_enough_turns_have_passed(self):
        t = ToolTracker(unused_after=3)
        t.observe_tools(["a", "b"])
        t.end_turn()
        self.assertEqual(t.prunable(), [])

    def test_unused_tool_is_prunable_after_the_threshold(self):
        t = ToolTracker(unused_after=3)
        t.observe_tools(["a", "b"])
        for _ in range(3):
            t.record_call("a")
            t.end_turn()
        self.assertEqual(t.prunable(), ["b"])

    def test_a_tool_used_recently_is_never_prunable(self):
        t = ToolTracker(unused_after=2)
        t.observe_tools(["a"])
        for _ in range(10):
            t.record_call("a")
            t.end_turn()
        self.assertEqual(t.prunable(), [])

    def test_a_tool_used_once_long_ago_is_still_never_pruned(self):
        """The bug the end-to-end run caught: idle-time pruning removed the
        only tool the agent had ever used, because it went quiet for a while."""
        t = ToolTracker(unused_after=3)
        t.observe_tools(["used_once", "never_used"])
        t.record_call("used_once")
        for _ in range(50):
            t.end_turn()
        self.assertEqual(t.prunable(), ["never_used"])


    def test_a_never_prune_tool_survives_however_quiet(self):
        """The dev-UI run pruned the plugin's own cost_status tool."""
        t = ToolTracker(unused_after=2, never_prune=frozenset({"cost_status"}))
        t.observe_tools(["cost_status", "other"])
        for _ in range(50):
            t.end_turn()
        self.assertEqual(t.prunable(), ["other"])


class TestBudget(unittest.TestCase):
    def test_thresholds_in_order(self):
        b = Budget(limit_usd=1.0)
        self.assertEqual(b.decide(), "proceed")
        b.spent_usd = 0.85
        self.assertEqual(b.decide(), "downgrade")
        b.spent_usd = 1.01
        self.assertEqual(b.decide(), "stop")

    def test_zero_limit_disables_the_budget(self):
        b = Budget(limit_usd=0.0)
        b.spent_usd = 999
        self.assertEqual(b.decide(), "proceed")

    def test_an_uncosted_turn_is_not_a_free_turn(self):
        """Counting unknown cost as zero makes a budget drift silently."""
        b = Budget(limit_usd=1.0)
        b.add(price("mystery-model", Usage(10_000, 500)))
        self.assertEqual(b.spent_usd, 0.0)
        self.assertEqual(b.unknown_turns, 1)
        self.assertIn("NOT counted", b.status())


if __name__ == "__main__":
    unittest.main(verbosity=2)
