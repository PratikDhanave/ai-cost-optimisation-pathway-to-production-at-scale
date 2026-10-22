#!/usr/bin/env python3
"""Pins the claims recipes 01-05 make in their own stdout.

These recipes EXECUTE on import and their names start with digits, so every one
of them is run as a subprocess here and the assertions read numbers back out of
the printed report. Each recipe's output is captured once and memoised.

What is pinned is the CLAIM, not the decimal: rates come from prices.py and are
overridable with PRICE_IN / PRICE_OUT / VOLUME, so a literal would break the
moment a reader prices these against their own card. The relationships are the
product -- "tokens fell further than cost", "cost fell further than tokens",
"break-even is one hit", "a price lever moves no tokens" -- and those survive
any rate card where output costs more than input.

The load-bearing invariant across the whole set: a recipe whose lever changes
the PRICE of a token must print a token change of exactly 0.0%. Recipe 05 is the
first of those, and borrowing its cost saving into the token column is how a
team double-counts the same prefix.
"""
import pathlib
import re
import subprocess
import sys
import unittest

# Works from either layout: tests/ beside the recipes (this repo), or tests/ at
# the root with the recipes under recipes/ (the published extract).
_UP = pathlib.Path(__file__).resolve().parent.parent
RECIPES = _UP if (_UP / "prices.py").exists() else _UP / "recipes"
TOOLSDIR = _UP / "tools" if (_UP / "tools").exists() else RECIPES / "tools"
sys.path.insert(0, str(RECIPES))
sys.path.insert(0, str(TOOLSDIR))

import prices as P                            # noqa: E402  (safe: no side effects)


_CACHE = {}


def run(stem):
    """Run one recipe as a subprocess and return its stdout, memoised per session."""
    if stem not in _CACHE:
        script = next(RECIPES.glob(stem + "_*.py"))
        p = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr[-800:]
        _CACHE[stem] = p.stdout
    return _CACHE[stem]


# --- readers: the report is text, so every figure is parsed back out of it ----

TOKEN_ROW = re.compile(r"^ {2}(\S.*?) {2,}([\d,]+) +([\d,]+) +([\d,]+) *([-+][\d.]+%)? *$")
COST_ROW = re.compile(
    r"^ {2}(\S.*?) {2,}(-?\$[\d.,]+)(?: +(-?\$[\d.,]+) +(-?\$[\d.,]+))?(?: +([-+][\d.]+%))? *$")
RESULT = re.compile(r"RESULT: TOKENS ([-+][\d.]+)% +\| +COST ([-+][\d.]+)%"
                    r"(?: +\| +SAVES (-?\$[\d.,]+)/mo)?")


def _num(tok):
    """'-$8,100.00' -> -8100.0 ; '+0.0%' -> 0.0 ; None -> None."""
    if tok is None:
        return None
    return float(tok.replace("$", "").replace(",", "").replace("%", "").replace("+", ""))


def _block(out, head):
    """The rows of the '  TOKENS' or '  COST' table, up to the blank line."""
    lines = out.splitlines()
    start = lines.index("  " + head) + 2          # skip the title and the column header
    rows = []
    for line in lines[start:]:
        if not line.strip():
            break
        rows.append(line)
    return rows


def token_rows(out):
    """[(label, in, out, total, change_pct_or_None)] in printed order."""
    rows = []
    for line in _block(out, "TOKENS"):
        m = TOKEN_ROW.match(line)
        assert m, f"unparsed TOKENS row: {line!r}"
        rows.append((m.group(1), int(_num(m.group(2))), int(_num(m.group(3))),
                     int(_num(m.group(4))), _num(m.group(5))))
    return rows


def cost_rows(out):
    """[(label, per_unit, per_day, per_month, change_pct_or_None)] in printed order."""
    rows = []
    for line in _block(out, "COST"):
        m = COST_ROW.match(line)
        assert m, f"unparsed COST row: {line!r}"
        rows.append((m.group(1), _num(m.group(2)), _num(m.group(3)),
                     _num(m.group(4)), _num(m.group(5))))
    return rows


def headline(out):
    """(token_change_pct, cost_change_pct, monthly_saving_or_None) from the RESULT line."""
    m = RESULT.search(out)
    assert m, "no RESULT line in output"
    return _num(m.group(1)), _num(m.group(2)), _num(m.group(3))


class OutputIsDearerThanInput(unittest.TestCase):
    """Shared precondition: several claims below only hold while output costs more."""

    def assert_output_premium(self):
        self.assertGreater(
            P.OUTPUT_PREMIUM, 1.0,
            "these recipes' claims assume output is billed above input; check PRICE_OUT")


# --- 01 -- the average is a lie ----------------------------------------------

class Recipe01TheUnit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = run("01")

    def test_01_optimises_nothing_so_both_headline_columns_are_zero(self):
        """01 is the baseline recipe: a non-zero saving here would make every later cut relative to a lever."""
        token_cut, cost_cut, saving = headline(self.out)
        self.assertEqual(0.0, abs(token_cut))
        self.assertEqual(0.0, abs(cost_cut))
        self.assertIsNone(saving, "the baseline recipe must not claim a monthly saving")

    def test_01_the_mean_is_skewed_above_the_median_by_a_dominant_tail(self):
        """A budget built on the mean is wrong for nearly every request AND for the ones that matter."""
        ratio = float(re.search(r"mean / median = ([\d.]+)x", self.out).group(1))
        self.assertGreater(ratio, 2.0, "the mean must be meaningfully above the median")
        m = re.search(r"median (-?\$[\d.,]+) +mean (-?\$[\d.,]+) +P99 (-?\$[\d.,]+)", self.out)
        median, mean, p99 = (_num(m.group(i)) for i in (1, 2, 3))
        self.assertLess(median, mean)
        self.assertGreaterEqual(p99, mean)
        self.assertAlmostEqual(ratio, mean / median, places=1)
        self.assertGreater(p99, 10 * median, "the tail must be an order of magnitude off the median")
        share = float(re.search(r"most expensive request is (\d+)% of total spend", self.out).group(1))
        self.assertGreater(share, 25.0, "one request must carry a large share of total spend")
        self.assertLess(share, 100.0)


# --- 02 -- the prompt diet ---------------------------------------------------

class Recipe02PromptDiet(OutputIsDearerThanInput):

    @classmethod
    def setUpClass(cls):
        cls.out = run("02")

    def test_02_the_diet_cuts_tokens_by_more_than_it_cuts_cost(self):
        """The recipe's point is that the cheap lever is the SMALL half of the bill; equal cuts would hide that."""
        self.assert_output_premium()
        token_cut, cost_cut, saving = headline(self.out)
        self.assertLess(token_cut, 0.0)
        self.assertLess(cost_cut, 0.0)
        self.assertGreater(abs(token_cut), abs(cost_cut))
        self.assertGreater(saving, 0.0)

    def test_02_the_output_column_is_untouched_by_the_prompt_diet(self):
        """Cost falls less than tokens ONLY because output is unchanged -- that is the mechanism, not a rounding artefact."""
        rows = token_rows(self.out)
        self.assertEqual(2, len(rows))
        before, after = rows
        self.assertEqual(before[2], after[2], "output tokens must be identical before and after")
        self.assertLess(after[1], before[1], "input tokens must fall")
        self.assertLess(after[3], before[3])

    def test_02_the_system_prompt_cut_is_larger_than_the_whole_request_cut(self):
        """Quoting the 83% prompt cut as the request cut is the overstatement this verdict exists to prevent."""
        m = re.search(r"token cut is (\d+)% on the system prompt but only\s+(\d+)% on the request", self.out)
        self.assertIsNotNone(m, "the verdict must state both percentages")
        on_prompt, on_request = float(m.group(1)), float(m.group(2))
        self.assertGreater(on_prompt, on_request)
        token_cut, _, _ = headline(self.out)
        self.assertAlmostEqual(on_request, abs(token_cut), delta=1.0,
                               msg="the headline must report the request cut, not the prompt cut")


# --- 03 -- output shape ------------------------------------------------------

class Recipe03OutputShape(OutputIsDearerThanInput):

    @classmethod
    def setUpClass(cls):
        cls.out = run("03")

    def test_03_prose_to_json_cuts_cost_by_more_than_it_cuts_tokens(self):
        """This inversion against recipe 02 is the set's main argument: the output side is where the money is."""
        self.assert_output_premium()
        token_cut, cost_cut, saving = headline(self.out)
        self.assertLess(cost_cut, 0.0)
        self.assertGreater(abs(cost_cut), abs(token_cut))
        self.assertGreater(saving, 0.0)

    def test_03_the_input_column_is_identical_across_the_three_output_contracts(self):
        """The claim is that only the output contract changed; a moving input would confound the comparison."""
        rows = token_rows(self.out)
        self.assertEqual(3, len(rows))
        self.assertEqual({rows[0][1]}, {r[1] for r in rows}, "input tokens must be the same in all three rows")
        outs = [r[2] for r in rows]
        self.assertEqual(outs, sorted(outs, reverse=True), "prose > JSON > enum on output tokens")

    def test_03_the_bare_enum_is_cheapest_and_is_still_flagged_as_risky(self):
        """The cheapest row is the one the recipe refuses to recommend; dropping that caution turns a cost note into bad advice."""
        rows = cost_rows(self.out)
        self.assertEqual(3, len(rows))
        per_request = [r[1] for r in rows]
        self.assertEqual(per_request, sorted(per_request, reverse=True))
        self.assertIn("enum row is cheapest and often wrong to ship", " ".join(self.out.split()))
        self.assertIn("No confidence score means no", " ".join(self.out.split()))


# --- 04 -- few-shot pruning --------------------------------------------------

class Recipe04FewShotPruning(OutputIsDearerThanInput):

    @classmethod
    def setUpClass(cls):
        cls.out = run("04")

    def test_04_each_dropped_example_cuts_both_columns_and_cuts_tokens_more_than_cost(self):
        """The 8/4/2/0 ladder is only a decision if it is monotonic, and examples sit in the prefix, so it must behave like recipe 02 and not 03."""
        self.assert_output_premium()
        trows, crows = token_rows(self.out), cost_rows(self.out)
        self.assertEqual(4, len(trows))
        self.assertEqual(4, len(crows))
        totals = [r[3] for r in trows]
        self.assertEqual(totals, sorted(totals, reverse=True))
        per_request = [r[1] for r in crows]
        self.assertEqual(per_request, sorted(per_request, reverse=True))
        changes = [r[4] for r in trows[1:]]
        self.assertEqual(changes, sorted(changes, reverse=True), "each step must report a deeper cut")
        self.assertTrue(all(c < 0 for c in changes))
        self.assertEqual({trows[0][2]}, {r[2] for r in trows}, "output tokens must be identical in all four rows")
        token_cut, cost_cut, _ = headline(self.out)
        self.assertGreater(abs(token_cut), abs(cost_cut), "an input-side lever cuts tokens harder than cost")

    def test_04_the_headline_is_the_eight_to_two_cut_not_the_zero_shot_cut(self):
        """Zero-shot is the cheapest row and the recipe will not headline it without an accuracy eval."""
        trows = token_rows(self.out)
        two_shot, zero_shot = trows[2][4], trows[3][4]
        token_cut, _, _ = headline(self.out)
        self.assertAlmostEqual(two_shot, token_cut, delta=0.05)
        self.assertNotAlmostEqual(zero_shot, token_cut, delta=0.05)
        flat = " ".join(self.out.split())
        self.assertIn("8 -> 2 examples", flat)
        self.assertIn("cost per CORRECT answer", flat)


# --- 05 -- cache break-even --------------------------------------------------

class Recipe05CacheBreakeven(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = run("05")

    def test_05_the_cache_break_even_is_exactly_one_hit(self):
        """A 'needs two hits' rule of thumb rejects workloads that are already profitable -- the integer has to be 1."""
        m = re.search(r"BREAK-EVEN: ([\d.]+) hits .*?integer answer is (\d+)", self.out, re.S)
        self.assertIsNotNone(m, "the note must print both the fractional and the integer break-even")
        fractional, integer = float(m.group(1)), int(m.group(2))
        self.assertLess(fractional, 1.0, "the premium must be repaid inside the first hit")
        self.assertEqual(1, integer)
        # and the cost table must agree: the minimum-hit row already beats no caching,
        # then amortises towards the read rate rather than improving without limit
        rows = cost_rows(self.out)
        self.assertEqual(4, len(rows))
        by_label = {r[0]: r for r in rows}
        one_hit = next(r for label, r in by_label.items() if label.startswith("1 hit per write"))
        self.assertLess(one_hit[4], 0.0, "one hit per write must already be cheaper than no caching")
        self.assertLess(one_hit[1], by_label["no caching"][1])
        per_request = [r[1] for r in rows]
        self.assertEqual(per_request, sorted(per_request, reverse=True))
        cuts = [abs(r[4]) for r in rows[1:]]
        self.assertEqual(cuts, sorted(cuts), "deeper cuts as hits per write rise")
        self.assertLess(cuts[2] - cuts[1], cuts[1] - cuts[0], "the gain per extra hit must shrink")

    def test_05_caching_reports_a_zero_percent_token_change_because_it_is_a_price_lever(self):
        """Load-bearing for the whole set: booking a price lever as a token cut double-counts the same prefix."""
        token_cut, cost_cut, saving = headline(self.out)
        self.assertEqual(0.0, abs(token_cut), "a PRICE lever must print exactly 0.0% token change")
        self.assertLess(cost_cut, 0.0, "the saving must land in the cost column instead")
        self.assertGreater(saving, 0.0)
        before, after = token_rows(self.out)
        self.assertEqual(before[1:4], after[1:4], "in/out/total must be identical row to row")
        self.assertEqual(0.0, abs(after[4]))
        self.assertIn("Caching is a PRICE lever, not a token lever", self.out)

    def test_05_a_request_gap_beyond_the_ttl_costs_more_than_not_caching_at_all(self):
        """Failure mode 2 is the only lever in the set that can LOSE money, so it must be printed as negative, not softened."""
        flat = " ".join(self.out.split())
        self.assertIn("cache EXPIRES", flat)
        m = re.search(r"(-?\$[\d.,]+) vs (-?\$[\d.,]+) uncached = (-?\$[\d.,]+)/month WORSE", flat)
        self.assertIsNotNone(m, "the expiry failure mode must print a monthly figure")
        cold, warm, monthly = (_num(m.group(i)) for i in (1, 2, 3))
        self.assertGreater(cold, warm, "paying the write premium with no read must cost more than no caching")
        self.assertGreater(monthly, 0.0, "the loss must be stated as a positive amount labelled WORSE")

    # NOTE -- NOT TESTABLE FROM STDOUT, and reported rather than asserted:
    # the module docstring promises three failure modes "all computed below
    # rather than asserted". Only failure mode 2 (TTL expiry) is computed. The
    # sub-minimum prefix (CACHE_MIN) and the unstable-prefix hit-rate collapse
    # appear only as prose in the verdict, with no arithmetic, so there is no
    # output for a test_a_prefix_under_the_minimum_caches_nothing to read.
    def test_05_names_the_minimum_prefix_and_the_vendor_that_breaks_the_arithmetic(self):
        """The two preconditions a reader would otherwise carry across providers; the paper is wrong the moment they are dropped."""
        flat = " ".join(self.out.split())
        self.assertIn(f"Prefix >= {P.CACHE_MIN:,} tokens", flat)
        self.assertIn("Google writes at STANDARD price", flat)
        self.assertIn("no break-even at all", flat)
        self.assertIn(f"Bedrock write at {P.CACHE_WRITE}x", flat)


if __name__ == "__main__":
    unittest.main(verbosity=2)
