#!/usr/bin/env python3
"""Pins the CLAIMS printed by recipes 11-15.

These recipes execute on import and their filenames start with digits, so each
one is run as a subprocess and its stdout is parsed. Numbers are pinned as
RELATIONSHIPS (sums, ratios, orderings) rather than literals, because every
rate in prices.py is overridable with PRICE_IN / PRICE_OUT / VOLUME and a
literal would break the moment a reader prices these against their own card.
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





def run(stem):
    """Execute one recipe as a subprocess and hand back its stdout."""
    p = subprocess.run([sys.executable, str(next(RECIPES.glob(stem + "_*.py")))],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-800:]
    return p.stdout


def num(s):
    """'$1,912.50' / '-5.6' / '12,800' -> float."""
    s = s.strip().replace("$", "").replace(",", "").replace("%", "")
    return float(s)


def result_line(out):
    """The machine-readable RESULT line: (token_cut_pct, cost_cut_pct)."""
    m = re.search(r"RESULT:\s*TOKENS\s*([+-][\d.]+)%\s*\|\s*COST\s*([+-][\d.]+)%", out)
    assert m, "no RESULT headline found"
    return float(m.group(1)), float(m.group(2))


def token_row(out, label):
    """A row of the harness TOKENS table, matched on its label prefix."""
    pat = re.compile(r"^\s*" + re.escape(label) + r"\s{2,}([\d,]+)\s+([\d,]+)"
                     r"(?:\s+([\d,]+))?\s*([+-][\d.]+)?%?\s*$")
    for line in out.splitlines():
        m = pat.match(line)
        if m:
            change = float(m.group(4)) if m.group(4) else None
            return num(m.group(1)), num(m.group(2)), change
    raise AssertionError("no TOKENS row labelled %r" % label)


def cost_row(out, label):
    """(dollars_per_unit, change_pct_or_None) from a harness COST table row."""
    pat = re.compile(r"^\s*" + re.escape(label) + r"\s{2,}\$([\d,.]+)"
                     r"(?:\s+\$[\d,.]+)*\s*([+-][\d.]+)?%?\s*$")
    for line in out.splitlines():
        m = pat.match(line)
        if m:
            return num(m.group(1)), (float(m.group(2)) if m.group(2) else None)
    raise AssertionError("no COST row labelled %r" % label)


# ---------------------------------------------------------------- recipe 11 --

class Recipe11TheStack(unittest.TestCase):
    """11 - composing four levers, and refusing to let the result be quoted."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("11")

    def marginal_table(self):
        rows = {}
        for m in re.finditer(r"^\s*(trunc|cache|route|batch)\s+\$([\d,.]+)/req\s+"
                             r"\$([\d,.]+)/req\s+([\d.]+)x\s*$",
                             self.out, re.M):
            rows[m.group(1)] = (num(m.group(2)), num(m.group(3)), float(m.group(4)))
        self.assertEqual(set(rows), {"trunc", "cache", "route", "batch"},
                         "marginal-value table did not parse")
        return rows

    def test_four_solo_percentages_sum_to_more_than_the_composed_cut(self):
        """Non-additivity is the whole recipe: adding solo savings double counts."""
        solo = re.search(r"Add the four solo percentages up and you get ([\d.]+)% off",
                         self.out)
        real = re.search(r"Run all four together and the real number is ([\d.]+)%",
                         self.out)
        self.assertTrue(solo and real, "non-additivity note missing from output")
        solo_sum, composed = float(solo.group(1)), float(real.group(1))
        self.assertGreater(solo_sum, composed)
        self.assertGreater(solo_sum, 100.0,
                           "the solo sum must be absurd (>100%) for the point to land")
        self.assertLess(composed, 100.0, "a composed cut can never reach 100%")

    def test_every_lever_is_worth_less_added_last_than_it_is_alone(self):
        """Each lever shrinks the base the next works on, so marginal < solo always."""
        for lever, (alone, last, ratio) in self.marginal_table().items():
            self.assertLess(last, alone, "%s is worth more added last than alone" % lever)
            self.assertLess(ratio, 1.0, "%s ratio should be sub-1x" % lever)
            self.assertGreater(ratio, 0.0, "%s should still be worth something" % lever)

    def test_the_headline_cost_cut_outruns_the_token_cut_and_is_not_quotable(self):
        """Most of the money is in what a token costs -- and the recipe still won't quote it."""
        token_cut, cost_cut = result_line(self.out)
        self.assertLess(cost_cut, 0.0)
        self.assertLess(token_cut, 0.0)
        self.assertGreater(abs(cost_cut), abs(token_cut))
        self.assertIn("DO NOT QUOTE THAT PERCENTAGE AT ANYONE", self.out)
        self.assertIn("The MECHANISM transfers. The number does not.", self.out)

    # KNOWN DEFECT -- left failing on purpose, do not relax this assertion.
    #
    # recipes/models.py:stack_request() folds the cache discount into the BILLED
    # TOKEN COUNT (`prefix = STACK["prefix"] * P.CACHE_READ if cache`) instead of
    # into the price. So recipe 11 prints "cache the prefix ... -5.6%" in its
    # TOKENS column, while:
    #   - its own table header says "only ONE of the four levers touches tokens
    #     at all", and
    #   - its own note two lines below says "Routing, caching and the batch tier
    #     remove none -- they change what a token costs".
    # Recipes 05 and 08 print 0.0% for the same price levers ("Zero token change.
    # Caching is a PRICE lever, not a token lever."), so recipe 11 is the odd one
    # out. The conflation also inflates the RESULT headline token cut to -68.1%
    # when truncation -- the only token lever -- accounts for -62.5%.
    # The fix belongs in models.py (price the cached prefix, do not discount the
    # token count), not here.
    def test_caching_a_prefix_is_a_price_lever_and_must_show_zero_token_change(self):
        """Keeping tokens and cost separate is the invariant the whole set exists for."""
        base_in, _, _ = token_row(self.out, "nothing on")
        cache_in, _, change = token_row(self.out, "cache the prefix")
        self.assertEqual(cache_in, base_in,
                         "caching is a price lever: it must not move the token count")
        self.assertAlmostEqual(change or 0.0, 0.0, places=1)


# ---------------------------------------------------------------- recipe 12 --

class Recipe12SelfHostBreakeven(unittest.TestCase):
    """12 - self-hosting is a staircase, and optimising first can close the door."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("12")

    def staircase(self):
        rows = []
        for m in re.finditer(r"^\s*([\d,]+)\s+(\d+)\s+([\d.]+)%\s+\$([\d,.]+)\s+"
                             r"\$([\d,.]+)\s+\$([\d,.]+)\s+(managed API|self-host)\s*$",
                             self.out, re.M):
            rows.append(dict(rpd=num(m.group(1)), gpus=int(m.group(2)),
                             util=float(m.group(3)), fixed=num(m.group(4)),
                             selfhost=num(m.group(5)), managed=num(m.group(6)),
                             winner=m.group(7)))
        self.assertGreaterEqual(len(rows), 5, "staircase table did not parse")
        return rows

    def test_self_hosting_changes_no_tokens_at_all(self):
        """A change of cost MODEL is a price lever: it must claim no token saving."""
        managed = token_row(self.out, "managed API")
        hosted = token_row(self.out, "self-hosted")
        self.assertEqual(managed[:2], hosted[:2])
        self.assertAlmostEqual(hosted[2] or 0.0, 0.0, places=1)
        token_cut, cost_cut = result_line(self.out)
        self.assertAlmostEqual(token_cut, 0.0, places=1)
        self.assertAlmostEqual(cost_cut, 0.0, places=1)

    def test_cost_per_request_rises_when_demand_crosses_a_gpu_boundary(self):
        """The staircase is the finding: growing just past a boundary costs you more."""
        rows = self.staircase()
        jumps = [(a, b) for a, b in zip(rows, rows[1:])
                 if b["gpus"] > a["gpus"] and b["selfhost"] > a["selfhost"]]
        self.assertTrue(jumps, "no row where more demand bought a GPU and raised $/req")
        a, b = jumps[0]
        self.assertGreater(b["rpd"], a["rpd"])
        self.assertLess(b["util"], a["util"], "the new GPU should be barely used")

    def test_self_hosting_never_breaks_even_once_the_managed_price_is_halved(self):
        """Optimise first or you buy GPUs to serve a bill you could have deleted."""
        self.assertRegex(self.out, r"break-even after optimisation\s+never requests/day")
        m = re.search(r"cannot serve a request below\s+\$([\d,]+(?:\.\d+)?)"
                      r" at this throughput\.\s*The optimised managed price is "
                      r"\$([\d,]+(?:\.\d+)?)", self.out, re.S)
        self.assertTrue(m, "the structural floor-vs-optimised-price note is missing")
        floor, optimised = num(m.group(1)), num(m.group(2))
        self.assertGreater(floor, optimised,
                           "a flat-out GPU with zero ops must still lose for 'never' "
                           "to be structural rather than a scale problem")


# ---------------------------------------------------------------- recipe 13 --

class Recipe13GovernanceBudgets(unittest.TestCase):
    """13 - a per-request cut does not stop the bill climbing."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("13")

    def growth(self):
        rows = []
        for m in re.finditer(r"^\s*(\d+)\s+([\d,]+)\s+\$([\d,.]+)\s+\$([\d,.]+)\s+"
                             r"([\d.]+)x\s*$", self.out, re.M):
            rows.append(dict(month=int(m.group(1)), rpd=num(m.group(2)),
                             per=num(m.group(3)), bill=num(m.group(4)),
                             ratio=float(m.group(5))))
        self.assertGreaterEqual(len(rows), 4, "growth table did not parse")
        return rows

    def test_a_banked_per_request_cut_still_leaves_the_bill_higher_under_growth(self):
        """Efficiency is not cost control: the cut held and the bill still doubled."""
        rows = self.growth()
        start, end = rows[0], rows[-1]
        self.assertAlmostEqual(start["ratio"], 1.0, places=2)
        self.assertLess(rows[1]["per"], start["per"], "the cut must actually land")
        self.assertLess(rows[1]["ratio"], 1.0, "month 1 should dip below the baseline")
        self.assertGreater(end["ratio"], 1.0,
                           "growth must eat the gain by the end of the table")
        self.assertGreater(end["rpd"], start["rpd"])
        # the per-request cut holds for every month after it lands
        held = {r["per"] for r in rows[1:]}
        self.assertEqual(len(held), 1, "the per-request cut should not drift")

    def test_downgrading_at_the_budget_cuts_cost_while_refusing_nobody(self):
        """Swapping the model is a price lever; refusing requests is not a saving."""
        none_tok = token_row(self.out, "no controls")
        down_tok = token_row(self.out, "downgrade at 80%")
        stop_tok = token_row(self.out, "hard stop at 100%")
        self.assertEqual(down_tok[:2], none_tok[:2],
                         "the downgrade policy must serve every request, tokens intact")
        self.assertAlmostEqual(down_tok[2] or 0.0, 0.0, places=1)
        none_cost, _ = cost_row(self.out, "no controls")
        down_cost, down_change = cost_row(self.out, "downgrade at 80%")
        self.assertLess(down_cost, none_cost, "the downgrade must be cheaper")
        self.assertLess(down_change, 0.0)
        # only the hard stop moves tokens, and it does it by refusing people
        self.assertLess(stop_tok[0], none_tok[0], "the hard stop refuses requests")
        self.assertLess(stop_tok[1], none_tok[1])
        self.assertLess(stop_tok[2], 0.0)
        token_cut, cost_cut = result_line(self.out)
        self.assertAlmostEqual(token_cut, 0.0, places=1,
                               msg="the headline lever is the downgrade: zero tokens")
        self.assertLess(cost_cut, 0.0)


# ---------------------------------------------------------------- recipe 14 --

class Recipe14CommitAndForecast(unittest.TestCase):
    """14 - optimisation attacks volume, a commitment attacks rate."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("14")

    def cost_table(self):
        want = ("list rate, unoptimised", "optimised volume only",
                "committed rate only", "both")
        return {label: cost_row(self.out, label) for label in want}

    def test_volume_and_rate_discounts_compose_multiplicatively(self):
        """The one clean stack in the set: the two levers act on different factors."""
        t = self.cost_table()
        base = t["list rate, unoptimised"][0]
        vol = t["optimised volume only"][0]
        rate = t["committed rate only"][0]
        both = t["both"][0]
        self.assertAlmostEqual(both, vol * rate / base, delta=base * 0.005,
                               msg="both-levers cost must be the product of the two")
        for label in ("optimised volume only", "committed rate only", "both"):
            self.assertLess(t[label][0], base)
        vol_pct = abs(t["optimised volume only"][1])
        rate_pct = abs(t["committed rate only"][1])
        both_pct = abs(t["both"][1])
        self.assertGreater(both_pct, max(vol_pct, rate_pct),
                           "stacking must beat either lever alone")
        self.assertLess(both_pct, vol_pct + rate_pct,
                        "and must still fall short of the additive sum")

    def test_a_committed_use_discount_is_a_price_lever_with_zero_token_change(self):
        """A commitment is a price, not a payload: the token column must stay flat."""
        listed = token_row(self.out, "list rate")
        committed = token_row(self.out, "committed-use rate")
        self.assertEqual(listed[:2], committed[:2])
        self.assertAlmostEqual(committed[2] or 0.0, 0.0, places=1)
        token_cut, cost_cut = result_line(self.out)
        self.assertAlmostEqual(token_cut, 0.0, places=1)
        self.assertLess(cost_cut, 0.0, "but the cost must fall")

    def test_modelling_the_three_growth_components_separately_forecasts_higher(self):
        """Commit against a user-growth curve alone and you under-buy every quarter."""
        rows = []
        for m in re.finditer(r"^\s*(\d+)\s+\$([\d,.]+)\s+\$([\d,.]+)\s+\$([\d,.]+)\s*$",
                             self.out, re.M):
            rows.append((int(m.group(1)), num(m.group(2)),
                         num(m.group(3)), num(m.group(4))))
        self.assertGreaterEqual(len(rows), 4, "forecast table did not parse")
        first, last = rows[0], rows[-1]
        self.assertAlmostEqual(first[1], first[2], delta=0.01)
        self.assertAlmostEqual(first[1], first[3], delta=0.01,
                               msg="all three forecasts must start from one bill")
        self.assertLess(last[1], last[2], "behavioural intensity must add to organic")
        self.assertLess(last[2], last[3], "feature steps must add again")
        self.assertGreater(last[3] / last[1], 1.5,
                           "the under-forecast must be large enough to matter")


# ---------------------------------------------------------------- recipe 15 --

class Recipe15ReasoningBudget(unittest.TestCase):
    """15 - thinking tokens are billed on the output side and never returned."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("15")

    LEVELS = ("off", "low", "medium", "high", "maximum")

    def test_thinking_lands_entirely_on_the_output_side_and_outruns_token_growth(self):
        """An input-shaped request with an output-shaped bill is the whole mechanic."""
        prem = re.search(r"which is\s*([\d.]+)x the input rate", self.out, re.S)
        self.assertTrue(prem, "the output-premium statement is missing")
        premium = float(prem.group(1))
        self.assertGreater(premium, 1.0, "output must cost more than input")

        toks = [token_row(self.out, "effort " + n) for n in self.LEVELS]
        for i, (tin, tout, _) in enumerate(toks):
            self.assertEqual(tin, toks[0][0],
                             "input must not move: only invisible thinking changes")
            if i:
                self.assertGreater(tout, toks[i - 1][1],
                                   "more effort must mean more output-side tokens")
                tok_change = toks[i][2]
                cost_change = cost_row(self.out, "effort " + self.LEVELS[i])[1]
                self.assertIsNotNone(tok_change)
                self.assertIsNotNone(cost_change)
                self.assertGreater(cost_change, tok_change,
                                   "cost must grow faster than tokens at effort %s"
                                   % self.LEVELS[i])

    def test_the_cheapest_effort_setting_moves_once_a_failure_is_priced(self):
        """Cost per solved task prices a wrong answer at zero; nothing else does."""
        rows = []
        for m in re.finditer(r"^\s*\$([\d,.]+)\s+(off|low|medium|high|maximum)\s+"
                             r"\$([\d,.]+)\s*$", self.out, re.M):
            rows.append((num(m.group(1)), m.group(2), num(m.group(3))))
        self.assertGreaterEqual(len(rows), 3, "failure-pricing table did not parse")
        self.assertAlmostEqual(rows[0][0], 0.0, places=6,
                               msg="the table must start from a free failure")
        idx = {n: i for i, n in enumerate(self.LEVELS)}
        self.assertNotEqual(rows[0][1], rows[-1][1],
                            "pricing a failure must move the optimum")
        self.assertGreater(idx[rows[-1][1]], idx[rows[0][1]],
                           "a costlier failure must buy MORE effort, not less")
        chosen = [idx[name] for _, name, _ in rows]
        self.assertEqual(chosen, sorted(chosen),
                         "the chosen effort must rise monotonically with failure cost")
        self.assertIn("prices a FAILURE AT ZERO", self.out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
