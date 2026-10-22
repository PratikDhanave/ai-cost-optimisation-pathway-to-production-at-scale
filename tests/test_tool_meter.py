#!/usr/bin/env python3
"""Pins the public behaviour of recipes/tools/meter.py.

meter.py is the take-home artifact: it is the thing a reader runs against their
own traffic, so its arithmetic and its refusals are the product. These tests
pin the four claims the module's own docstring makes -- cached input kept as a
separate field and billed at the read rate, cost per SOLVED call, the waste
figure, and per-feature attribution shares -- plus the paths where it declines
to produce a number.

Two tests are left FAILING on purpose. They are marked DEFECT and they pin
figures the tool currently gets wrong; weakening them would ship the wrong
number. See the module summary at the bottom of this file.
"""
import csv
import io
import pathlib
import re
import sys
import tempfile
import unittest

# Works from either layout: tests/ beside the recipes (this repo), or tests/ at
# the root with the recipes under recipes/ (the published extract).
_UP = pathlib.Path(__file__).resolve().parent.parent
RECIPES = _UP if (_UP / "prices.py").exists() else _UP / "recipes"
TOOLSDIR = _UP / "tools" if (_UP / "tools").exists() else RECIPES / "tools"
sys.path.insert(0, str(RECIPES))
sys.path.insert(0, str(TOOLSDIR))

import meter                                       # noqa: E402
import prices as P                                 # noqa: E402
from _harness import money                         # noqa: E402


IN_BIG, OUT_BIG = P.MODELS["big"]
IN_SMALL, OUT_SMALL = P.MODELS["small"]


def report_lines(m):
    out = []
    m.report(out=out.append)
    return out


def find_line(lines, needle):
    for line in lines:
        if needle in line:
            return line
    raise AssertionError(f"no line containing {needle!r} in:\n" + "\n".join(lines))


def dollars(text):
    """Every dollar figure on a report line, as floats."""
    return [float(x.replace(",", "")) for x in re.findall(r"\$([\d,]+\.\d+)", text)]


class CachedInputBilling(unittest.TestCase):
    """The split between cached and uncached input cannot be reconstructed later."""

    def test_cached_input_tokens_are_billed_at_the_read_rate_not_the_full_rate(self):
        """Summing raw input tokens overstates any cached workload and makes caching look free."""
        m = meter.Meter()
        with m.call(feature="support_chat", model="big") as c:
            c.record(in_tok=10_000, out_tok=1_000, cached_in_tok=8_000, outcome="solved")
        expected = (2_000 / 1e6 * IN_BIG            # uncached remainder at full rate
                    + 1_000 / 1e6 * OUT_BIG
                    + 8_000 / 1e6 * IN_BIG * P.CACHE_READ)
        self.assertAlmostEqual(m.rows[0]["usd"], expected, places=8)
        # and the discount is real, not cosmetic: the same call with no cache hit
        full = (10_000 / 1e6 * IN_BIG + 1_000 / 1e6 * OUT_BIG)
        self.assertLess(m.rows[0]["usd"], full)

    def test_the_cached_count_is_kept_as_its_own_column_in_the_csv(self):
        """Attribution is only auditable if the per-call cache split survives to disk."""
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "spend.csv"
            m = meter.Meter(path)
            with m.call(feature="support_chat", model="big") as c:
                c.record(in_tok=9_000, out_tok=200, cached_in_tok=7_500, outcome="solved")
            # a second Meter on the same file must append, not re-header
            m2 = meter.Meter(path)
            with m2.call(feature="ticket_classifier", model="small") as c:
                c.record(in_tok=900, out_tok=30, outcome="solved")

            text = path.read_text()
            self.assertEqual(text.count("cached_in_tok"), 1, "header rewritten on reopen")
            rows = list(csv.DictReader(io.StringIO(text)))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["cached_in_tok"], "7500")
            self.assertEqual(rows[0]["in_tok"], "9000")      # NOT reduced by the cache
            self.assertEqual(rows[1]["cached_in_tok"], "0")
            self.assertEqual(rows[0]["batch"], "0")
            self.assertEqual(list(rows[0]), meter.FIELDS)

    def test_a_cached_count_larger_than_in_tok_clamps_uncached_to_zero(self):
        """A provider convention mismatch must not produce negative input billing."""
        m = meter.Meter()
        with m.call(feature="f", model="big") as c:
            c.record(in_tok=500, out_tok=0, cached_in_tok=4_000, outcome="solved")
        # meter's convention is that in_tok INCLUDES the cached tokens, so
        # cached > in_tok is a data inconsistency, and the cached leg is
        # clamped to the input that actually existed. Billing 4,000 cached
        # tokens on a 500-token request -- which this previously asserted --
        # charges for reads the request could not have made.
        # (If your provider reports in_tok EXCLUDING cache hits, add them
        # together before calling record().)
        self.assertAlmostEqual(m.rows[0]["usd"],
                               500 / 1e6 * IN_BIG * P.CACHE_READ, places=8)
        self.assertGreater(m.rows[0]["usd"], 0.0)

    def test_batch_halves_the_cached_leg_as_well_as_the_uncached_leg(self):
        """The batch discount applies to both directions; a half-applied discount under-reports savings."""
        rows = {}
        for flag in (False, True):
            m = meter.Meter()
            with m.call(feature="f", model="big", batch=flag) as c:
                c.record(in_tok=1_000, out_tok=1_000, cached_in_tok=500, outcome="solved")
            rows[flag] = m.rows[0]
        self.assertAlmostEqual(rows[True]["usd"] / rows[False]["usd"], P.BATCH, places=8)
        self.assertEqual(rows[True]["batch"], 1)


class SolvedDenominator(unittest.TestCase):
    """Cost per request is the wrong denominator: a failed call costs full price."""

    def test_cost_per_solved_call_excludes_the_calls_that_solved_nothing(self):
        """The whole reason outcome is required: 50% failures double the real unit cost."""
        m = meter.Meter()
        for outcome in ("solved", "truncated"):
            with m.call(feature="alpha", model="big") as c:
                c.record(in_tok=1_000, out_tok=1_000, outcome=outcome)
        line = find_line(report_lines(m), "alpha")
        spend, per_solved = dollars(line)
        total = 2 * (1_000 / 1e6 * IN_BIG + 1_000 / 1e6 * OUT_BIG)
        self.assertAlmostEqual(spend, round(total, 4), places=4)
        self.assertAlmostEqual(per_solved, round(total, 4), places=4)   # 1 solved, not 2 calls
        self.assertAlmostEqual(per_solved / (spend / 2), 2.0, places=3)
        self.assertRegex(line, r"\balpha\b\s+2\s+1\b")                  # calls=2, solved=1

    def test_a_feature_with_no_solved_calls_reports_n_a_not_a_number(self):
        """A dollars-per-solved figure for zero solved calls would be infinity dressed as a price."""
        m = meter.Meter()
        with m.call(feature="beta", model="big") as c:
            c.record(in_tok=1_000, out_tok=1_000, outcome="failed")
        line = find_line(report_lines(m), "beta")
        self.assertIn("n/a", line)
        self.assertNotIn("inf", line)
        self.assertEqual(len(dollars(line)), 1, "a per-solved price was printed anyway")


class WasteAndShares(unittest.TestCase):
    """The two aggregate numbers a reader is meant to act on."""

    def test_waste_counts_every_outcome_that_is_not_solved(self):
        """Truncated, failed and unrecorded calls all cost full price and solve nothing."""
        m = meter.Meter()
        for outcome in ("solved", "truncated", "failed", "unknown"):
            with m.call(feature="f", model="big") as c:
                c.record(in_tok=1_000, out_tok=1_000, outcome=outcome)
        per_call = 1_000 / 1e6 * IN_BIG + 1_000 / 1e6 * OUT_BIG
        line = find_line(report_lines(m), "WASTE")
        wasted, = dollars(line)
        self.assertAlmostEqual(wasted, round(3 * per_call, 4), places=4)
        self.assertIn("75.0%", line)

    def test_a_call_that_raises_is_still_recorded_as_unknown_and_charged_to_waste(self):
        """A provider blowing up mid-call is the most expensive kind of waste; it must not vanish."""
        m = meter.Meter()
        with m.call(feature="good", model="big") as c:
            c.record(in_tok=1_000, out_tok=1_000, outcome="solved")
        with self.assertRaises(RuntimeError):
            with m.call(feature="crashy", model="big") as c:
                raise RuntimeError("provider blew up")
        self.assertEqual(len(m.rows), 2, "the crashed call was not recorded")
        self.assertEqual(m.rows[1]["outcome"], "unknown")
        self.assertEqual(m.rows[1]["feature"], "crashy")
        lines = report_lines(m)
        self.assertIn("crashy", "\n".join(lines))
        self.assertIn("n/a", find_line(lines, "crashy"))

    def test_per_feature_shares_partition_the_total_spend(self):
        """Attribution that does not sum to the bill cannot tell you which lever has reach."""
        m = meter.Meter()
        with m.call(feature="support_chat", model="big") as c:      # 2 units of spend
            c.record(in_tok=2_000, out_tok=2_000, outcome="solved")
        with m.call(feature="ticket_classifier", model="big") as c:  # 1 unit
            c.record(in_tok=1_000, out_tok=1_000, outcome="solved")
        lines = report_lines(m)
        shares = [float(x) for x in re.findall(r"(\d+\.\d)%", "\n".join(
            [find_line(lines, "support_chat"), find_line(lines, "ticket_classifier")]))]
        self.assertEqual(len(shares), 2)
        self.assertAlmostEqual(sum(shares), 100.0, places=1)
        self.assertAlmostEqual(shares[0], 66.7, places=1)
        total, = dollars(find_line(lines, "TOTAL"))
        self.assertAlmostEqual(total, round(sum(r["usd"] for r in m.rows), 4), places=4)


class Refusals(unittest.TestCase):
    """Declining to produce a number is the behaviour under test, not an edge case."""

    def test_an_unknown_model_raises_and_records_no_row(self):
        """Pricing an unrecognised model at $0 would silently hide a whole feature's spend."""
        m = meter.Meter()
        with self.assertRaises(KeyError) as ctx:
            with m.call(feature="f", model="medium") as c:
                c.record(in_tok=1_000, out_tok=1_000, outcome="solved")
        self.assertIn("medium", str(ctx.exception))
        self.assertEqual(m.rows, [], "an unpriceable call was recorded anyway")

    def test_a_report_with_no_calls_prints_no_numbers(self):
        """An empty meter must say so rather than render a $0.00 bill that looks measured."""
        lines = report_lines(meter.Meter())
        self.assertEqual(lines, ["  no calls recorded"])
        self.assertNotIn("$", "".join(lines))

    def test_a_report_whose_whole_spend_is_zero_currently_crashes(self):
        """DEFECT (pinned, not endorsed): the recorded-but-free path is reachable and kills report()."""
        # One call that raises before record() leaves a legitimate row at $0. If it
        # is the ONLY row, report() divides by a zero total. Pinned with assertRaises
        # so the suite's signal stays on the two wrong-number defects below; the
        # correct behaviour is to report the row with a 0% share, not to raise.
        m = meter.Meter()
        with self.assertRaises(ValueError):
            with m.call(feature="crashy", model="big"):
                raise ValueError("boom")
        self.assertEqual(len(m.rows), 1)
        self.assertEqual(m.rows[0]["usd"], 0)
        with self.assertRaises(ZeroDivisionError):
            m.report(out=lambda *a: None)


class PinnedDefects(unittest.TestCase):
    """Both of these FAIL. The tool prints the wrong number; the test is right."""

    def test_the_cache_saving_line_prices_at_the_model_that_served_the_tokens(self):
        """DEFECT: the saving is hardcoded to the big-model rate, so a small-model cache reads 3.75x too good."""
        # meter.py:126  money(cached/1e6*P.MODELS['big'][0]*(1-P.CACHE_READ))
        # Every cached token here was served by "small". Do not relax this to the
        # big rate: the fix is to accumulate the saving per row using r["model"].
        m = meter.Meter()
        with m.call(feature="doc_enrichment", model="small") as c:
            c.record(in_tok=10_000, out_tok=100, cached_in_tok=9_000, outcome="solved")
        line = find_line(report_lines(m), "CACHE:")
        printed, = dollars(line)
        expected = 9_000 / 1e6 * IN_SMALL * (1 - P.CACHE_READ)
        self.assertAlmostEqual(printed, float(money(expected).lstrip("$")), places=6,
                               msg=f"cache saving priced at the big-model rate: {line.strip()}")

    def test_the_long_context_cliff_applies_even_when_most_of_the_request_was_cached(self):
        """DEFECT: splitting the request into two cost() calls hides the 2x cliff, under-billing long cached contexts."""
        # meter.py:57-59 calls P.cost() twice, so context_multiplier() never sees the
        # real request size. prices.py is explicit that past the threshold EVERY token
        # in the request bills at the higher rate. Do not lower the expectation: the
        # fix is to apply context_multiplier(self.in_tok) to the whole call.
        in_tok, out_tok, cached = 250_000, 1_000, 210_000
        self.assertEqual(P.context_multiplier(in_tok), P.CONTEXT_MULTIPLIER)
        m = meter.Meter()
        with m.call(feature="rag", model="big") as c:
            c.record(in_tok=in_tok, out_tok=out_tok, cached_in_tok=cached, outcome="solved")
        bare = ((in_tok - cached) / 1e6 * IN_BIG
                + out_tok / 1e6 * OUT_BIG
                + cached / 1e6 * IN_BIG * P.CACHE_READ)
        self.assertAlmostEqual(m.rows[0]["usd"], bare * P.CONTEXT_MULTIPLIER, places=6,
                               msg="a 250K-token request was billed below the context threshold "
                                   "because 210K of it came from cache")


if __name__ == "__main__":
    unittest.main(verbosity=2)
