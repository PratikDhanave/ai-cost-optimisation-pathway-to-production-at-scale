#!/usr/bin/env python3
"""Pins the four gateway controls: response cache, budget, downgrade, hard stop.

These controls are the product. Each one either removes a call, re-prices it, or
refuses it, and every one of those is a decision somebody's invoice depends on,
so the behaviour is pinned here rather than left to the demo output.

    python3 recipes/tests/test_tool_gateway.py
"""
import pathlib, sys
import unittest

# Works from either layout: tests/ beside the recipes (this repo), or tests/ at
# the root with the recipes under recipes/ (the published extract).
_UP = pathlib.Path(__file__).resolve().parent.parent
RECIPES = _UP if (_UP / "prices.py").exists() else _UP / "recipes"
TOOLSDIR = _UP / "tools" if (_UP / "tools").exists() else RECIPES / "tools"
sys.path.insert(0, str(RECIPES))
sys.path.insert(0, str(TOOLSDIR))

import gateway
from gateway import Gateway, Refused



OUT_TOK = 100          # fixed, so a model difference is a RATE difference only
PROMPT = "Classify this ticket: the customer cannot complete their order. " * 4


class Backend:
    """Records what it was asked, and labels its answer with the model that ran.

    The labelling mirrors the tool's own `_fake_backend`, which is the only way a
    caller can tell after the fact which model produced a given string.
    """

    def __init__(self, out_tok=OUT_TOK):
        self.calls = []
        self.out_tok = out_tok

    def __call__(self, prompt, model):
        self.calls.append((prompt, model))
        return f"[{model}] answer to {prompt[:24]}", self.out_tok


def gw(backend=None, **kw):
    kw.setdefault("daily_budget", 1_000.0)
    return Gateway(backend or Backend(), **kw)


class ResponseCache(unittest.TestCase):

    def test_a_repeat_request_on_a_cacheable_feature_costs_nothing_and_is_counted(self):
        """The cache is the only control that removes a whole call, so a hit must bill $0 and still appear in the stats."""
        b = Backend()
        g = gw(b, cache_ttl=3600, cacheable_features=("classifier",))

        first_text, first = g.handle("classifier", PROMPT, now=1_000)
        billed = g.spend
        second_text, second = g.handle("classifier", PROMPT, now=1_001)

        self.assertFalse(first["cached"])
        self.assertGreater(first["usd"], 0.0)
        self.assertTrue(second["cached"])
        self.assertEqual(second["usd"], 0.0)
        self.assertEqual(second_text, first_text)
        # a hit must not reach the provider, must not move spend, and must not
        # be metered as a call -- but it is still a request the gateway served
        self.assertEqual(len(b.calls), 1)
        self.assertEqual(g.spend, billed)
        self.assertEqual(len(g.meter.rows), 1)
        self.assertEqual(g.stats["cache_hits"], 1)
        self.assertEqual(g.stats["served"], 2)

    def test_the_response_cache_stays_off_unless_both_the_ttl_and_the_feature_opt_in(self):
        """Serving a stale answer is the one control with a correctness risk, so it must be impossible to switch on by accident."""
        for label, kw in [
            ("feature not marked safe", dict(cache_ttl=3600, cacheable_features=())),
            ("no ttl configured",       dict(cache_ttl=0, cacheable_features=("classifier",))),
            ("neither",                 dict()),
        ]:
            with self.subTest(label):
                b = Backend()
                g = gw(b, **kw)
                g.handle("classifier", PROMPT, now=1_000)
                _, second = g.handle("classifier", PROMPT, now=1_001)
                self.assertFalse(second["cached"])
                self.assertGreater(second["usd"], 0.0)
                self.assertEqual(len(b.calls), 2)
                self.assertEqual(g.stats["cache_hits"], 0)
                self.assertEqual(len(g.meter.rows), 2)

    def test_an_entry_as_old_as_the_ttl_is_refetched_and_billed_again(self):
        """A short TTL is the whole safety argument for the cache; if the boundary leaked, answers would outlive their stated freshness."""
        b = Backend()
        g = gw(b, cache_ttl=60, cacheable_features=("classifier",))
        g.handle("classifier", PROMPT, now=1_000)

        _, inside = g.handle("classifier", PROMPT, now=1_059.9)
        _, at_edge = g.handle("classifier", PROMPT, now=1_060)

        self.assertTrue(inside["cached"])
        self.assertFalse(at_edge["cached"])        # exactly TTL seconds old = expired
        self.assertGreater(at_edge["usd"], 0.0)
        self.assertEqual(g.stats["cache_hits"], 1)
        self.assertEqual([m for _, m in b.calls], ["big", "big"])

    def test_a_cached_reply_from_a_worse_model_is_never_served(self):
        """A caller that asked for the frontier model must not be handed a downgraded reply out of cache.

        DESIGN DECISION, not a relaxed assertion. An earlier version of this
        test expected the hit to be served and merely LABELLED "small". That is
        defensible -- the caller can audit it -- but it still hands someone a
        quality downgrade they did not opt into. gateway.py takes the stricter
        line: never serve output from a worse model than the caller would have
        received. The reverse is fine, and is tested below.
        """
        b = Backend()
        g = gw(b, daily_budget=1.0, downgrade_at=0.8, hard_stop_at=10 ** 9,
               cache_ttl=3600, cacheable_features=("classifier",))

        g.spend = 0.9                              # past the soft threshold
        downgraded_text, downgraded = g.handle("classifier", PROMPT, model="big",
                                               now=1_000)
        self.assertEqual(downgraded["model"], "small")

        g.spend = 0.0                              # a new day: no downgrade now
        fresh_text, fresh = g.handle("classifier", PROMPT, model="big", now=1_001)

        self.assertFalse(fresh["cached"], "a small-model reply was served to a "
                                          "full-price request")
        self.assertEqual(fresh["model"], "big")
        self.assertIn("[big]", fresh_text)

    def test_a_better_cached_reply_is_served_to_a_downgraded_request(self):
        """The invariant is one-directional: a frontier reply is fine for a request about to be downgraded, and it is free."""
        b = Backend()
        g = gw(b, daily_budget=1.0, downgrade_at=0.8, hard_stop_at=10 ** 9,
               cache_ttl=3600, cacheable_features=("classifier",))

        g.spend = 0.0                              # no downgrade: answered by big
        first_text, first = g.handle("classifier", PROMPT, model="big", now=1_000)
        self.assertEqual(first["model"], "big")

        g.spend = 0.9                              # now past the threshold
        hit_text, hit = g.handle("classifier", PROMPT, model="big", now=1_001)

        self.assertTrue(hit["cached"])
        self.assertEqual(hit["model"], "big")
        self.assertEqual(hit["usd"], 0.0)
        self.assertIn("[big]", hit_text)


class BudgetControls(unittest.TestCase):

    def test_past_the_soft_threshold_a_big_request_is_answered_by_the_small_model(self):
        """The downgrade is the control that answers everyone, so it must actually switch model and actually cost less."""
        b = Backend()
        g = gw(b, daily_budget=1.0, downgrade_at=0.8, hard_stop_at=10 ** 9)
        g.spend = 0.80                             # exactly at the threshold

        text, meta = g.handle("classifier", PROMPT, model="big")

        self.assertEqual(meta["model"], "small")
        self.assertIn("[small]", text)
        self.assertEqual(b.calls[-1][1], "small")
        self.assertEqual(g.meter.rows[-1]["model"], "small")
        self.assertEqual(g.stats["downgraded"], 1)

        # same prompt, same output length, plenty of budget: the only difference
        # is the rate, so the downgraded call must be strictly cheaper
        full = gw(Backend())
        _, at_full_price = full.handle("classifier", PROMPT, model="big")
        self.assertEqual(at_full_price["model"], "big")
        self.assertLess(meta["usd"], at_full_price["usd"])

    def test_a_request_already_on_the_small_model_is_never_downgraded(self):
        """The downgrade has one step; a cheap feature past the threshold must be served, not degraded further or refused."""
        b = Backend()
        g = gw(b, daily_budget=1.0, downgrade_at=0.8, hard_stop_at=10 ** 9)
        g.spend = 0.95

        _, meta = g.handle("classifier", PROMPT, model="small")

        self.assertEqual(meta["model"], "small")
        self.assertEqual(b.calls[-1][1], "small")
        self.assertEqual(g.stats["downgraded"], 0)
        self.assertEqual(g.stats["served"], 1)

    def test_at_the_hard_ceiling_the_gateway_refuses_without_calling_the_backend(self):
        """The hard stop's only job is that the next dollar is not spent -- a refusal that still dispatched would be theatre."""
        b = Backend()
        g = gw(b, daily_budget=2.0, hard_stop_at=1.0)
        g.spend = 2.0                              # at the ceiling, not past it

        with self.assertRaises(Refused) as caught:
            g.handle("classifier", PROMPT, model="big")

        self.assertIn("$2.00", str(caught.exception))
        self.assertEqual(b.calls, [])
        self.assertEqual(g.spend, 2.0)
        self.assertEqual(g.meter.rows, [])
        self.assertEqual(g.stats["refused"], 1)
        self.assertEqual(g.stats["served"], 0)
        self.assertEqual(g.stats["downgraded"], 0)

    def test_the_hard_stop_is_checked_before_the_downgrade_when_both_are_passed(self):
        """If the thresholds are set the other way round, the ceiling must still win -- a cheaper call is still a call the budget cannot afford."""
        b = Backend()
        g = gw(b, daily_budget=1.0, downgrade_at=0.8, hard_stop_at=0.5)
        g.spend = 0.60                             # past the stop, below the downgrade

        with self.assertRaises(Refused):
            g.handle("classifier", PROMPT, model="big")

        self.assertEqual(b.calls, [])
        self.assertEqual(g.stats["downgraded"], 0)
        self.assertEqual(g.stats["refused"], 1)

    def test_a_cached_answer_is_still_served_free_after_the_hard_stop_has_fired(self):
        """A $0 answer cannot breach a spend ceiling, and the documented control order puts the cache first for exactly that reason."""
        b = Backend()
        g = gw(b, daily_budget=1.0, cache_ttl=3600, cacheable_features=("classifier",))
        g.handle("classifier", PROMPT, now=1_000)
        g.spend = 99.0                             # far past the ceiling

        text, meta = g.handle("classifier", PROMPT, now=1_001)

        self.assertTrue(meta["cached"])
        self.assertEqual(meta["usd"], 0.0)
        self.assertIn("answer to", text)
        self.assertEqual(g.stats["refused"], 0)
        self.assertEqual(g.spend, 99.0)
        # an uncached prompt in the same state is still refused
        with self.assertRaises(Refused):
            g.handle("classifier", PROMPT + " different", now=1_002)
        self.assertEqual(g.stats["refused"], 1)
        self.assertEqual(len(b.calls), 1)


class Metering(unittest.TestCase):

    def test_every_billed_call_lands_on_the_meter_attributed_to_its_feature(self):
        """Attribution is the precondition for every other control: an unattributed call is spend nobody owns."""
        b = Backend()
        g = gw(b)

        g.handle("classifier", PROMPT, model="big")
        g.handle("enrichment", PROMPT, model="small")
        g.handle("enrichment", PROMPT, model="small", batch=True)

        rows = g.meter.rows
        self.assertEqual([r["feature"] for r in rows],
                         ["classifier", "enrichment", "enrichment"])
        self.assertEqual([r["model"] for r in rows], ["big", "small", "small"])
        self.assertEqual([r["batch"] for r in rows], [0, 0, 1])
        for r in rows:
            self.assertEqual(r["outcome"], "solved")
            self.assertEqual(r["out_tok"], OUT_TOK)
            self.assertGreater(r["in_tok"], 0)
            self.assertEqual(r["cached_in_tok"], 0)   # a RESPONSE cache, not a prompt cache
            self.assertGreater(r["usd"], 0.0)
        # the gateway's running spend is the meter's total, not a parallel tally
        self.assertAlmostEqual(g.spend, sum(r["usd"] for r in rows), places=7)
        self.assertLess(rows[2]["usd"], rows[1]["usd"])   # batch tier is cheaper

    def test_an_unknown_model_name_raises_instead_of_pricing_the_call_at_zero(self):
        """A model with no rate card has no cost; silently metering it at $0 would hide real spend behind a typo."""
        b = Backend()
        g = gw(b)

        with self.assertRaises(KeyError):
            g.handle("classifier", PROMPT, model="gpt-made-up")

        self.assertEqual(g.spend, 0.0)
        self.assertEqual(g.meter.rows, [])
        self.assertEqual(g.stats["served"], 0)


class StackedControls(unittest.TestCase):

    def test_all_three_controls_compose_and_spend_halts_within_one_call_of_the_budget(self):
        """Stacked is how the gateway actually ships, and the guarantee it sells is that the day's spend cannot run away."""
        b = Backend()
        g = gw(b, daily_budget=0.05, downgrade_at=0.8, hard_stop_at=1.0,
               cache_ttl=3600, cacheable_features=("classifier",))

        requests = [f"{PROMPT} ref={i // 2}" for i in range(200)]   # every prompt twice
        refused = 0
        for p in requests:
            try:
                g.handle("classifier", p, model="big", now=1_000)
            except Refused:
                refused += 1

        self.assertGreater(g.stats["cache_hits"], 0, "duplicates were not cached")
        self.assertGreater(g.stats["downgraded"], 0, "the soft threshold never fired")
        self.assertGreater(refused, 0, "the ceiling never fired")
        self.assertEqual(refused, g.stats["refused"])
        self.assertEqual(g.stats["served"] + refused, len(requests))
        self.assertEqual(g.stats["served"], g.stats["cache_hits"] + len(g.meter.rows))

        models = {r["model"] for r in g.meter.rows}
        self.assertEqual(models, {"big", "small"})   # both sides of the downgrade ran

        # the ceiling is checked BEFORE dispatch, so the overshoot is bounded by
        # the single most expensive call the gateway let through -- never more
        dearest = max(r["usd"] for r in g.meter.rows)
        self.assertGreaterEqual(g.spend, g.budget)
        self.assertLess(g.spend, g.budget + dearest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
