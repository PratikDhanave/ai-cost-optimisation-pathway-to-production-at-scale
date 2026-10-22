#!/usr/bin/env python3
"""Pins the refusals and the attribution arithmetic of tools/bill_estimate.py.

The tool's own promise is in its docstring: a missing REQUIRED column is an
error naming the column and never a default, and an absent OPTIONAL column
downgrades the levers that depend on it to "needs a human" instead of being
guessed into the headline. Those two refusals are the product, so they are
tested harder here than the happy path.

One test is EXPECTED TO FAIL against the current code -- see
test_the_cache_lever_cannot_be_worth_more_than_the_input_spend_it_discounts
and the defect note above it. Do not relax it; fix the tool.
"""
import csv
import io
import contextlib
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

# Works from either layout: tests/ beside the recipes (this repo), or tests/ at
# the root with the recipes under recipes/ (the published extract).
_UP = pathlib.Path(__file__).resolve().parent.parent
RECIPES = _UP if (_UP / "prices.py").exists() else _UP / "recipes"
TOOLSDIR = _UP / "tools" if (_UP / "tools").exists() else RECIPES / "tools"
sys.path.insert(0, str(RECIPES))
sys.path.insert(0, str(TOOLSDIR))

import bill_estimate                              # noqa: E402
import prices as P                                # noqa: E402


REQ = ["feature", "model", "input_tokens", "output_tokens", "requests"]


def _money(token):
    """'$1,234.50' -> 1234.5 ; the report is text, so figures are read back out of it."""
    return float(token.replace("$", "").replace(",", ""))


def _pct(token):
    return float(token.replace("%", "").replace("+", ""))


class Base(unittest.TestCase):
    def csv_at(self, header, rows):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = pathlib.Path(d.name) / "usage.csv"
        with path.open("w", newline="", encoding="utf8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        return path

    def run_tool(self, header, rows):
        """load -> analyse -> report, returning everything a test might assert on."""
        loaded, present = bill_estimate.load(self.csv_at(header, rows))
        by_feature, total = bill_estimate.analyse(loaded, present)
        lines = []
        bill_estimate.report(by_feature, total, present, out=lines.append)
        return lines, by_feature, total, present

    # --- report readers ---------------------------------------------------
    def block(self, lines, marker):
        """The contiguous non-blank lines after the line containing `marker`."""
        for i, line in enumerate(lines):
            if marker in line:
                out = []
                for nxt in lines[i + 1:]:
                    if not nxt.strip():
                        break
                    out.append(nxt)
                return out
        self.fail(f"no section headed {marker!r} in:\n" + "\n".join(lines))

    def lever(self, lines, name):
        """(reach_pct, discount_pct, worth) for one row of the ranked lever table."""
        for line in self.block(lines, "LEVERS RANKED BY REACH"):
            if line.strip().startswith(name):
                cells = line.split()
                return _pct(cells[-3]), _pct(cells[-2]), _money(cells[-1])
        return None

    def lever_names(self, lines):
        """Just the lever labels, in ranked order, with the figures sliced off."""
        rows = [ln for ln in self.block(lines, "LEVERS RANKED BY REACH")
                if not ln.strip().startswith("basis:")][1:]   # drop the column header
        return [" ".join(ln.split()[:-3]) for ln in rows]

    def cannot_tell(self, lines):
        return self.block(lines, "WHAT THIS DATA CANNOT TELL YOU")


class Refusals(Base):

    def test_a_missing_required_column_is_an_error_naming_the_column(self):
        """A silently defaulted required column would change every dollar below it."""
        path = self.csv_at(["feature", "model", "input_tokens"], [("f", "small", 100)])
        with self.assertRaises(bill_estimate.SchemaError) as caught:
            bill_estimate.load(path)
        msg = str(caught.exception)
        self.assertIn("missing required column(s)", msg)
        for column in ("output_tokens", "requests"):
            self.assertIn(column, msg)                       # every missing one named
            self.assertIn(bill_estimate.REQUIRED[column], msg)   # and what it means
        self.assertIn("No defaults are assumed", msg)
        self.assertNotIn("feature", msg.split("Run --schema")[0])  # present ones not blamed

    def test_a_file_with_only_a_header_refuses_instead_of_reporting_a_zero_bill(self):
        """An empty export is a broken export; a $0.00 report would read as good news."""
        with self.assertRaises(bill_estimate.SchemaError) as caught:
            bill_estimate.load(self.csv_at(REQ, []))
        self.assertIn("no data rows", str(caught.exception))

    def test_the_cli_exits_nonzero_and_prints_no_lever_table_on_a_bad_schema(self):
        """The refusal has to reach the shell: a 0 exit code gets scripted over."""
        path = self.csv_at(["feature", "model", "input_tokens", "output_tokens"],
                           [("f", "small", 100, 10)])
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["bill_estimate.py", str(path)]):
            with contextlib.redirect_stdout(buf):
                rc = bill_estimate.main()
        printed = buf.getvalue()
        self.assertEqual(1, rc)
        self.assertIn("CANNOT READ", printed)
        self.assertIn("requests", printed)
        self.assertNotIn("LEVERS RANKED", printed)
        self.assertNotIn("worth at most", printed)

    def test_an_absent_latency_sensitive_column_downgrades_batch_to_needs_a_human(self):
        """Guessing which traffic has nobody waiting would invent savings out of nothing."""
        lines, _, _, present = self.run_tool(REQ, [("chat", "big", 4000, 300, 500)])
        self.assertNotIn("latency_sensitive", present)
        self.assertIsNone(self.lever(lines, "move async work to the batch tier"))
        downgrade = [ln for ln in self.cannot_tell(lines) if "batch tier" in ln]
        self.assertEqual(1, len(downgrade))
        self.assertIn("no latency_sensitive column", downgrade[0])

        # nothing unmeasured leaks into the headline: the one measured lever is the total
        headline = [ln for ln in lines if "worth at most" in ln][0]
        self.assertEqual(["route the easy share to a cheaper model"], self.lever_names(lines))
        self.assertAlmostEqual(self.lever(lines, "route the easy share")[2],
                               _money(headline.split("worth at most")[1].split()[0]), places=2)
        # DEFECT (pinned, not endorsed): the prose says "three" even when one lever
        # was measurable. The figure is right; the sentence counting it is not.
        self.assertIn("Those three together", headline)

    def test_an_absent_prefix_tokens_column_downgrades_caching_and_names_the_next_tool(self):
        """Cache headroom depends on prefix STABILITY, which a usage export cannot show."""
        lines, _, _, present = self.run_tool(REQ, [("chat", "big", 4000, 300, 500)])
        self.assertNotIn("prefix_tokens", present)
        self.assertIsNone(self.lever(lines, "cache the stable prefix"))
        downgrade = [ln for ln in self.cannot_tell(lines) if "prompt caching" in ln]
        self.assertEqual(1, len(downgrade))
        self.assertIn("no prefix_tokens column", downgrade[0])
        self.assertIn("prefix_lint.py", downgrade[0])

    def test_a_prefix_under_the_cache_minimum_caches_nothing(self):
        """Under the per-breakpoint minimum there is no cache to hit, so reach is zero."""
        header = REQ + ["prefix_tokens"]
        lines, by_feature, total, _ = self.run_tool(
            header, [("chat", "big", 4000, 300, 500, P.CACHE_MIN - 1)])
        self.assertEqual(0.0, by_feature["chat"]["cacheable"])
        reach, _, worth = self.lever(lines, "cache the stable prefix")
        self.assertEqual(0.0, reach)
        self.assertEqual(0.0, worth)
        rest = [ln for ln in self.cannot_tell(lines) if "caching the rest" in ln]
        self.assertEqual(1, len(rest))
        self.assertIn(f"{P.CACHE_MIN:,}-token", rest[0])      # the minimum is quoted
        self.assertIn("recovers nothing", rest[0])

    def test_a_prefix_at_the_minimum_is_reachable_but_an_already_cached_row_is_not(self):
        """Headroom means spend a cache could still move, not spend a cache already moved."""
        header = REQ + ["prefix_tokens", "cached_input_tokens"]
        _, by_feature, _, _ = self.run_tool(header, [
            ("fresh",  "big", 4000, 300, 100, P.CACHE_MIN, 0),
            ("cached", "big", 4000, 300, 100, 8192, 3500),
        ])
        # Caching discounts INPUT only, so headroom is the input share of the
        # row, not the whole row. This previously asserted the whole row --
        # the defect the docstring above already described.
        fresh = by_feature["fresh"]
        self.assertLess(fresh["cacheable"], fresh["spend"])
        self.assertAlmostEqual(fresh["cacheable"],
                               P.cost(4000, 0, "big") * 100, places=8)
        self.assertEqual(0.0, by_feature["cached"]["cacheable"])

    def test_an_unknown_model_name_is_priced_at_frontier_rates_without_saying_so(self):
        """A reader's own tier silently becomes 'big' -- frontier spend, and routable."""
        _, by_feature, total, _ = self.run_tool(
            REQ, [("local", "my_own_llama_box", 1000, 100, 1)])
        # DEFECT (pinned, not endorsed): REQUIRED documents "or your own tier name",
        # but the fallback is invisible in the report -- the row is billed at $3/$15
        # AND counted as frontier spend the routing lever offers to move away from.
        self.assertAlmostEqual(P.cost(1000, 100, "big"), total, places=9)
        self.assertAlmostEqual(total, by_feature["local"]["big"], places=9)


class Attribution(Base):

    def test_spend_is_attributed_to_the_feature_that_incurred_it(self):
        """Ranking levers by reach is meaningless if the reach is on the wrong feature."""
        lines, by_feature, total, _ = self.run_tool(REQ, [
            ("classify", "small", 900, 30, 1000),
            ("chat",     "big", 9800, 420, 200),
            ("classify", "small", 900, 30, 500),      # second row, same feature
        ])
        classify = P.cost(900, 30, "small") * 1500
        chat = P.cost(9800, 420, "big") * 200
        self.assertAlmostEqual(classify, by_feature["classify"]["spend"], places=9)
        self.assertAlmostEqual(chat, by_feature["chat"]["spend"], places=9)
        self.assertAlmostEqual(classify + chat, total, places=9)
        self.assertAlmostEqual(1500.0, by_feature["classify"]["reqs"], places=9)

        rows = {ln.split()[0]: ln.split() for ln in self.block(lines, "YOUR SPEND, BY FEATURE")}
        self.assertEqual(["chat", "classify"],
                         sorted(set(rows) - {"feature", "TOTAL"}))
        self.assertAlmostEqual(chat / total * 100, _pct(rows["chat"][-2]), places=1)
        self.assertAlmostEqual(chat / 200, _money(rows["chat"][-1]), places=4)
        self.assertEqual("chat", lines[3].split()[0])         # biggest spender ranks first

    def test_cost_per_solved_is_reported_and_a_never_solving_feature_is_not_a_zero_divide(self):
        """Cost per request flatters a workload that fails; cost per solved is the real unit."""
        header = REQ + ["outcome"]
        lines, by_feature, total, present = self.run_tool(header, [
            ("chat",  "small", 1000, 100, 50, "solved"),
            ("chat",  "small", 1000, 100, 50, "truncated"),
            ("agent", "big", 2000, 400, 10, "failed"),
        ])
        self.assertIn("outcome", present)
        solved_rows = {ln.split()[0]: ln for ln in self.block(lines, "COST PER SOLVED REQUEST")}

        chat = solved_rows["chat"].split()
        per_request, per_solved = _money(chat[-3]), _money(chat[-2])
        self.assertAlmostEqual(2 * per_request, per_solved, places=4)   # half solved -> 2x
        self.assertAlmostEqual(100.0, _pct(chat[-1]), places=0)

        self.assertIn("never solved", solved_rows["agent"])
        self.assertIn("infinite", solved_rows["agent"])

        wasted = sum(f["wasted"] for f in by_feature.values())
        self.assertAlmostEqual(by_feature["agent"]["spend"] + by_feature["chat"]["spend"] / 2,
                               wasted, places=9)
        self.assertIn(f"{wasted / total * 100:.0f}% of spend", "\n".join(lines))
        self.assertIn("bought nothing", "\n".join(lines))

    def test_an_absent_outcome_column_flags_every_figure_as_cost_per_request(self):
        """Without outcomes the headline is per REQUEST, and the report has to say so."""
        text = "\n".join(self.run_tool(REQ, [("chat", "big", 4000, 300, 500)])[0])
        self.assertIn("BIGGEST GAP", text)
        self.assertIn("no outcome column", text)
        self.assertNotIn("COST PER SOLVED REQUEST", text)

    # ------------------------------------------------------------------ DEFECT
    # FAILING ON PURPOSE. analyse() puts the WHOLE row spend into f["cacheable"],
    # and report() multiplies that base by (1 - CACHE_READ) = 90%. Prompt caching
    # discounts cached INPUT only -- never output tokens, and never the variable
    # suffix after the prefix breakpoint. On the fixture below the tool reports
    # ~$0.81 of cache headroom against an input bill of $0.096, i.e. it offers to
    # save 8x the money it is theoretically possible to save, inside a line
    # labelled "worth at most". The overstatement grows with the output share, so
    # an output-heavy workload is where it is worst. Fix the base (prefix-token
    # input spend), not this assertion.
    def test_the_cache_lever_cannot_be_worth_more_than_the_input_spend_it_discounts(self):
        """A lever that claims more than 100% of the bill it acts on is not an estimate."""
        header = REQ + ["prefix_tokens"]
        lines, _, _, _ = self.run_tool(
            header, [("summarise", "small", 1200, 2000, 100, P.CACHE_MIN)])
        _, _, worth = self.lever(lines, "cache the stable prefix")
        input_side = P.cost(1200, 0, "small") * 100       # generous: ALL input, not the prefix
        self.assertLessEqual(worth, (1 - P.CACHE_READ) * input_side + 1e-9,
            "cache lever must not exceed the input spend it discounts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
