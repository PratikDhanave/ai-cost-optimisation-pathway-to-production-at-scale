#!/usr/bin/env python3
"""Pins the CLAIMS that recipes 16-21 make in their own printed output.

These recipes run their arithmetic at import time, and their filenames start
with digits, so nothing here imports them: each is executed once as a
subprocess and every assertion is read back out of its stdout.

Numbers are parsed and asserted as RELATIONSHIPS or RANGES, never as literal
strings, because every rate in recipes/prices.py is overridable by environment
variable (PRICE_IN, PRICE_OUT, VOLUME, VOLUME_SCALE ...). A test that pinned
"$0.0360" would fail the moment a reader priced the set against their own rate
card, which is the one thing the repo explicitly invites them to do.

The load-bearing cross-recipe test is at the bottom: a recipe whose lever moves
the PRICE of a token and not the NUMBER of tokens must report a 0.0% token
change. The whole set exists to keep those two columns separate, and a recipe
that borrowed its cost saving into the token column would be double-counting.
"""
import os
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




_CACHE = {}


def run(stem):
    """Execute one recipe as a subprocess, once per session, and cache stdout."""
    if stem not in _CACHE:
        matches = sorted(RECIPES.glob(stem + "_*.py"))
        assert matches, f"no recipe matching {stem}_*.py in {RECIPES}"
        p = subprocess.run([sys.executable, str(matches[0])],
                           capture_output=True, text=True, timeout=120,
                           env=os.environ.copy())
        assert p.returncode == 0, p.stderr[-800:]
        _CACHE[stem] = p.stdout
    return _CACHE[stem]


# --- readers -----------------------------------------------------------------

def money(token):
    """'-$1,234.50' -> -1234.5 ; every figure in these recipes is text first."""
    t = token.strip()
    sign = -1 if t.startswith("-") else 1
    return sign * float(t.lstrip("-").replace("$", "").replace(",", ""))


def num(token):
    return float(token.replace(",", "").replace("%", "").replace("+", ""))


def block(text, header):
    """The lines of one printed table: everything after `header` up to a blank."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == header:
            out = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    break
                out.append(nxt)
            return out
    raise AssertionError(f"table {header!r} not printed")


# label is non-greedy so a label containing digits ("199,999 tokens",
# "one layer, 3 attempts") does not swallow the first column.
_TOKEN_ROW = re.compile(
    r"^\s{2}(\S.*?)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)(?:\s+([+-][\d.]+)%)?\s*$")
_COST_ROW = re.compile(
    r"^\s{2}(\S.*?)\s+(-?\$[\d,.]+)(?:\s+(-?\$[\d,.]+)\s+(-?\$[\d,.]+))?"
    r"(?:\s+([+-][\d.]+)%)?\s*$")


def token_rows(text):
    """[(label, in, out, total, change_pct_or_None)] from the TOKENS table."""
    rows = []
    for line in block(text, "TOKENS"):
        m = _TOKEN_ROW.match(line)
        if m:
            rows.append((m.group(1).strip(), int(num(m.group(2))),
                         int(num(m.group(3))), int(num(m.group(4))),
                         None if m.group(5) is None else float(m.group(5))))
    assert rows, "no rows parsed out of the TOKENS table"
    return rows


def cost_rows(text):
    """[(label, per_unit, change_pct_or_None)] from the COST table."""
    rows = []
    for line in block(text, "COST"):
        m = _COST_ROW.match(line)
        if m:
            rows.append((m.group(1).strip(), money(m.group(2)),
                         None if m.group(5) is None else float(m.group(5))))
    assert rows, "no rows parsed out of the COST table"
    return rows


def result_line(text):
    """The machine-readable RESULT line: (token_pct, cost_pct)."""
    m = re.search(r"RESULT: TOKENS ([+-][\d.]+)%\s+\|\s+COST ([+-][\d.]+)%", text)
    assert m, "no RESULT headline printed"
    return float(m.group(1)), float(m.group(2))


# --- 16 ----------------------------------------------------------------------

class ContextCliff(unittest.TestCase):
    """16 - the long-context price cliff."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("16")
        m = re.search(r"Threshold here: ([\d,]+) input tokens", cls.out)
        assert m, "the recipe must state the threshold it is using"
        cls.threshold = int(num(m.group(1)))
        cls.cliff = []
        for line in block(cls.out, "COST AS CONTEXT GROWS"):
            m = re.match(r"^\s*([\d,]+)\s+([\d.]+)x\s+(\$[\d,.]+)"
                         r"(?:\s+([+-][\d]+)%)?", line)
            if m:
                cls.cliff.append((int(num(m.group(1))), float(m.group(2)),
                                  money(m.group(3)),
                                  None if m.group(4) is None else float(m.group(4))))
        assert len(cls.cliff) >= 4, "the cliff table needs rows either side of the line"

    def test_the_price_multiplier_steps_at_the_threshold_and_nowhere_else(self):
        """A gradient would make this lever uninteresting; the claim is a step function."""
        below = [m for n, m, _, _ in self.cliff if n < self.threshold]
        at_or_above = [m for n, m, _, _ in self.cliff if n >= self.threshold]
        self.assertTrue(below and at_or_above,
                        "table must straddle the threshold")
        self.assertEqual(set(below), {1.0},
                         "every request under the line must bill at 1.0x")
        self.assertEqual(len(set(at_or_above)), 1,
                         "the multiplier is a step, not a ramp: one value above the line")
        self.assertGreater(at_or_above[0], 1.0,
                           "at the threshold the whole request must re-price upward")

    def test_one_token_over_the_line_roughly_doubles_the_bill(self):
        """The headline claim: the smallest possible token increase is the largest price jump."""
        m = re.search(r"ONE extra input token -- ([\d.]+)% more tokens -- "
                      r"for ([\d]+)% more money", self.out)
        self.assertIsNotNone(m, "the one-token comparison must be stated")
        more_tokens, more_money = float(m.group(1)), float(m.group(2))
        self.assertLess(more_tokens, 0.01, "one token is a rounding error in the token column")
        self.assertGreaterEqual(more_money, 80, "but it must roughly double the money")
        self.assertLessEqual(more_money, 120)

        # and the same step, read off the cost table rather than the prose
        idx = next(i for i, (n, *_) in enumerate(self.cliff) if n >= self.threshold)
        self.assertGreater(idx, 0, "the table must show a row below the line first")
        ratio = self.cliff[idx][2] / self.cliff[idx - 1][2]
        self.assertGreater(ratio, 1.9)
        self.assertLess(ratio, 2.1)

        # the biggest jump in the table comes from the smallest token increase
        steps = [(s, n - self.cliff[i - 1][0])
                 for i, (n, _, _, s) in enumerate(self.cliff) if s is not None]
        biggest = max(steps, key=lambda p: p[0])
        self.assertEqual(biggest[0], steps[idx - 1][0],
                         "the largest price step must be the one at the threshold")
        self.assertEqual(biggest[1], min(d for _, d in steps),
                         "and it must be bought with the smallest token increase in the table")

    def test_the_few_requests_over_the_line_carry_a_disproportionate_share_of_spend(self):
        """Why you plot the distribution and not the mean: a 7% tail is not 7% of the bill."""
        m = re.search(r"(\d+)% of requests are over the line and they are "
                      r"(\d+)% of the spend", self.out)
        self.assertIsNotNone(m, "the recipe must quantify the over-threshold tail")
        traffic, spend = float(m.group(1)), float(m.group(2))
        self.assertLess(traffic, 15, "the tail is meant to be a minority of traffic")
        self.assertGreater(spend, traffic * 1.5,
                           "the tail must cost far more than its share of traffic")

        rows = cost_rows(self.out)
        today, trimmed = rows[0][1], rows[-1][1]
        self.assertLess(trimmed, today, "trimming under the line must reduce the blended bill")
        self.assertIsNotNone(rows[-1][2], "the trimmed row must print a change")
        self.assertLess(rows[-1][2], 0.0)


# --- 17 ----------------------------------------------------------------------

class SemanticCache(unittest.TestCase):
    """17 - semantic caching and the wrong-answer tax."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("17")
        cls.levels = []
        for line in block(cls.out, "WHAT THE SAVING COSTS YOU"):
            m = re.match(r"^\s{2}(\S.*?)\s+(\d+)%\s+(\$[\d,.]+)\s+([\d,]+)\s*$", line)
            if m:
                cls.levels.append((m.group(1).strip(), float(m.group(2)),
                                   money(m.group(3)), int(num(m.group(4)))))
        assert len(cls.levels) >= 3, "need several thresholds to show the trade"

    def test_loosening_the_threshold_buys_more_saving_and_more_wrong_answers_together(self):
        """The one lever here that can be wrong: the dial moves both numbers the same way."""
        hits = [h for _, h, _, _ in self.levels]
        spend = [s for _, _, s, _ in self.levels]
        wrong = [w for _, _, _, w in self.levels]

        self.assertEqual(hits, sorted(hits), "hit rate must rise as the threshold loosens")
        self.assertEqual(spend, sorted(spend, reverse=True),
                         "every loosening must reduce spend")
        self.assertEqual(wrong, sorted(wrong),
                         "and every loosening must increase wrong answers")
        self.assertEqual(wrong[0], 0, "the first row is the cache switched off")
        self.assertGreater(wrong[-1], wrong[1] * 10,
                           "the loosest setting must be dramatically wronger than the strictest")
        self.assertLess(spend[-1], spend[0] * 0.5,
                        "and dramatically cheaper, which is the whole temptation")

    def test_a_cache_hit_sends_no_tokens_because_the_call_never_happens(self):
        """This is the only lever in the set that removes the request rather than repricing it."""
        rows = {label: (i, o, total, change) for label, i, o, total, change
                in token_rows(self.out)}
        self.assertIn("cache miss", rows)
        self.assertIn("cache hit", rows)
        self.assertGreater(rows["cache miss"][2], 0)
        self.assertEqual(rows["cache hit"][:3], (0, 0, 0),
                         "a hit must send nothing at all, in or out")
        self.assertAlmostEqual(rows["cache hit"][3], -100.0, delta=0.05,
                               msg="a hit is a 100% token removal, not a discount")

        token_pct, cost_pct = result_line(self.out)
        self.assertLess(token_pct, 0.0,
                        "because the call disappears, this recipe legitimately reports "
                        "a token cut -- unlike the pure price levers")


# --- 18 ----------------------------------------------------------------------

class PromptCompression(unittest.TestCase):
    """18 - prompt compression and who pays the compressor."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("18")
        cls.costs = cost_rows(cls.out)
        assert len(cls.costs) >= 3, "need uncompressed, per-request and reused rows"
        # the three-line note above the tables: the GROSS saving the token cut
        # buys, and the compressor call that is billed against it
        m = re.search(r"inference, compressed\s+-?\$[\d,.]+\s+saves (-?\$[\d,.]+)", cls.out)
        assert m, "the recipe must state what one compression saves"
        cls.gross = money(m.group(1))
        m = re.search(r"the compressor call\s+(-?\$[\d,.]+)", cls.out)
        assert m, "the compressor call must be its own line item"
        cls.compressor = money(m.group(1))

    def test_compressing_every_request_cuts_tokens_far_more_than_it_cuts_cost(self):
        """The arithmetic people skip: the compressor is itself a billed inference."""
        token_pct, cost_pct = result_line(self.out)
        self.assertLess(token_pct, -50.0, "the token cut is real and large")
        self.assertGreater(cost_pct, token_pct / 2,
                           "cost must not follow tokens even half way; that gap IS the "
                           "compressor's own bill, and it holds for any rate pair where "
                           "the compressor is actually billed")

        # net of the compressor, almost none of the gross saving survives. Stated
        # against the recipe's own gross figure rather than against a dollar
        # literal, because the big/small rate pair is env-overridable and the
        # recipe itself prints "A LOSS" when the pair makes it one.
        uncompressed, per_request = self.costs[0][1], self.costs[1][1]
        net = uncompressed - per_request
        self.assertLess(net, self.gross * 0.5,
                        "the compressor must consume at least half of what compression "
                        "saves, so per-request compression is near-pointless")

    def test_the_compressor_call_costs_about_what_one_compression_saves(self):
        """If the break-even is one use, the lever is free money only on reuse."""
        m = re.search(r"the compressor costs ([\d.]+)x what", self.out)
        self.assertIsNotNone(m, "the recipe must print its break-even multiple")
        multiple = float(m.group(1))
        self.assertGreater(multiple, 0.5,
                           "the compressor must eat most of the gross saving")
        self.assertLess(multiple, 1.5,
                        "and roughly all of it: compress once, use once, break even")
        self.assertAlmostEqual(self.compressor / self.gross, multiple, delta=0.02,
                               msg="the printed multiple must be the printed line items")
        self.assertIn("the line people omit", self.out,
                      "the compressor call must be flagged as the omitted line")

    def test_the_saving_only_arrives_when_the_compressed_prompt_is_reused(self):
        """The recipe's actual advice: amortise the compressor or do not run it."""
        uncompressed, per_request, reused = (r[1] for r in self.costs[:3])
        self.assertIn("reused", self.costs[2][0])
        self.assertLess(reused, per_request,
                        "reuse must beat compressing on every request")
        self.assertLess(reused, uncompressed * 0.75,
                        "and must be a saving worth the engineering, unlike per-request")
        self.assertIsNotNone(self.costs[2][2])
        self.assertLess(self.costs[2][2], -25.0)


# --- 19 ----------------------------------------------------------------------

class ToolSchemas(unittest.TestCase):
    """19 - tool schemas: the tax paid on every call, used or not."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("19")
        cls.shares = []
        for line in block(cls.out, "WHAT SHARE OF THE REQUEST IS SCHEMA"):
            m = re.match(r"^\s{2}(\S.*?)\s+([\d,]+)\s+([\d.]+)%\s+(\$[\d,.]+)\s*$", line)
            if m:
                cls.shares.append((m.group(1).strip(), int(num(m.group(2))),
                                   float(m.group(3)), money(m.group(4))))
        assert len(cls.shares) >= 3, "need a progression of tool counts"

    def test_tool_schemas_become_nearly_all_of_the_input_at_scale(self):
        """Adding a tool is a pricing change for every request, including the ones that never call it."""
        pcts = [p for _, _, p, _ in self.shares]
        self.assertEqual(pcts, sorted(pcts),
                         "schema share of input must rise with every tool added")
        self.assertAlmostEqual(pcts[0], 0.0, delta=0.05,
                               msg="the no-tools baseline must carry no schema")
        self.assertGreater(pcts[-1], 90.0,
                           "at the largest setup the request must be overwhelmingly schema")

        rows = token_rows(self.out)
        self.assertGreater(rows[-1][3], rows[0][3] * 10,
                           "the fully loaded request must dwarf the toolless one")
        self.assertEqual(rows[-1][2], rows[0][2],
                         "output is unchanged: this is purely an input-side tax")

        costs = [c for _, c in ((r[0], r[1]) for r in cost_rows(self.out))]
        self.assertEqual(costs, sorted(costs),
                         "and cost per request must rise monotonically with the toolset")

    def test_an_agent_resends_the_entire_schema_on_every_step(self):
        """The multiplier that turns a tolerable overhead into the dominant line item."""
        m = re.search(r"([\d,]+) tokens x (\d+) steps = ([\d,]+) tokens", self.out)
        self.assertIsNotNone(m, "the agent multiplier must be spelled out")
        schema, steps, total = (int(num(g)) for g in m.groups())
        self.assertGreater(steps, 1)
        self.assertEqual(total, schema * steps,
                         "the arithmetic must be the schema re-sent once per step")

        one = re.search(r"adding ONE heavy tool costs (\$[\d,.]+)/month", self.out)
        agent = re.search(r"In an agent it is (\$[\d,.]+)/month", self.out)
        self.assertIsNotNone(one, "the cost of one added tool must be stated")
        self.assertIsNotNone(agent)
        self.assertAlmostEqual(money(agent.group(1)) / money(one.group(1)), steps,
                               delta=0.01,
                               msg="the agent cost of one tool must be exactly steps x the "
                                   "single-call cost")


# --- 20 ----------------------------------------------------------------------

class WastePaths(unittest.TestCase):
    """20 - retries, timeouts and abandoned streams."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("20")
        cls.where = []
        for line in block(cls.out, "WHERE THE MONEY GOES, PER REQUEST"):
            m = re.match(r"^\s{2}(\S.*?)\s+(\$[\d,.]+)\s+([\d.]+)%\s*$", line)
            if m:
                cls.where.append((m.group(1).strip(), money(m.group(2)),
                                  float(m.group(3))))
        cls.retries = []
        for line in block(cls.out, "STACKED RETRY LAYERS, on a request that "
                                   "keeps timing out"):
            m = re.match(r"^\s{2}(\S.*?)\s+(\d+)\s+(\$[\d,.]+)\s*$", line)
            if m:
                cls.retries.append((m.group(1).strip(), int(m.group(2)),
                                    money(m.group(3))))
        assert cls.where and cls.retries, "both tables must print"

    def test_a_tenth_of_spend_buys_nothing_and_every_waste_path_is_named(self):
        """Waste is the only lever with no quality trade, and it is invisible on a success dashboard."""
        m = re.search(r"(\$[\d,.]+) of every (\$[\d,.]+) -- (\d+)% -- buys nothing",
                      self.out)
        self.assertIsNotNone(m, "the recipe must quantify the share that buys nothing")
        waste, blended, pct = money(m.group(1)), money(m.group(2)), float(m.group(3))
        self.assertGreater(pct, 2.0, "the claim is a material share, not a rounding error")
        self.assertLess(pct, 30.0)
        self.assertAlmostEqual(waste / blended * 100, pct, delta=0.6,
                               msg="the stated percentage must be the stated dollars")

        labels = [lbl for lbl, _, _ in self.where]
        good = [lbl for lbl in labels if "actually got" in lbl]
        self.assertEqual(len(good), 1, "the useful work must be one named row")
        waste_rows = [(lbl, d, s) for lbl, d, s in self.where if "actually got" not in lbl]
        self.assertGreaterEqual(len(waste_rows), 4,
                                "hard failures, timeouts, the retry and abandoned streams "
                                "must each be itemised")
        for lbl, dollars, share in waste_rows:
            self.assertGreater(dollars, 0.0, f"{lbl} must carry a real cost")
        self.assertAlmostEqual(sum(s for _, _, s in waste_rows), pct, delta=1.5,
                               msg="the itemised waste must reconcile to the headline share")

    def test_two_layers_of_three_retries_bill_nine_attempts(self):
        """Nobody configures nine; two teams configure three each and the layers multiply."""
        single = self.retries[0]
        stacked = next(r for r in self.retries if "x" in r[0])
        self.assertEqual(stacked[1], single[1] ** 2,
                         "SDK 3 x app 3 must bill 9 attempts, not 3")
        self.assertAlmostEqual(stacked[2] / single[2], stacked[1] / single[1],
                               delta=0.02,
                               msg="billing must scale linearly with attempts")
        self.assertGreater(self.retries[-1][1], stacked[1],
                           "a third layer must multiply again, not add")

        # the discarded answer and its retry cost the same: you paid twice for one answer
        discarded = next(d for lbl, d, _ in self.where if "discarded" in lbl)
        retry = next(d for lbl, d, _ in self.where if "retry of that same work" in lbl)
        self.assertAlmostEqual(retry, discarded, delta=discarded * 0.01,
                               msg="a timeout on completed work converts one bill into two")


# --- 21 ----------------------------------------------------------------------

class UnitEconomics(unittest.TestCase):
    """21 - cost per user and the unprofitable tail."""

    @classmethod
    def setUpClass(cls):
        cls.out = run("21")
        m = re.search(r"([\d,]+) subscribers at (\$[\d,.]+)/month flat", cls.out)
        assert m, "the subscriber count and flat price must be stated"
        cls.users, cls.price = int(num(m.group(1))), money(m.group(2))
        cls.bands = []
        for line in block(cls.out, "PER USER, PER MONTH"):
            m = re.match(r"^\s{2}(\w+)\s+([\d.]+)%\s+([\d,]+)\s+(-?\$[\d,.]+)\s+"
                         r"(-?\$[\d,.]+)\s*(LOSS)?\s*$", line)
            if m:
                cls.bands.append((m.group(1), float(m.group(2)), int(num(m.group(3))),
                                  money(m.group(4)), money(m.group(5)),
                                  m.group(6) == "LOSS"))
        assert len(cls.bands) >= 4, "need a usage distribution with a tail"

    def test_a_healthy_looking_gross_margin_hides_accounts_sold_below_cost(self):
        """The P&L question: a per-request dashboard cannot show you an unprofitable customer."""
        m = re.search(r"gross margin\s+(-?\$[\d,.]+)/month\s+(\d+)%", self.out)
        self.assertIsNotNone(m, "the P&L block must print a gross margin percentage")
        margin_pct = float(m.group(2))
        self.assertGreater(margin_pct, 50.0,
                           "the headline margin must look healthy -- that is the trap")

        # the LOSS flag must agree with the arithmetic, in both directions, and
        # each band's margin must be the flat price less that band's cost
        for name, share, reqs, cost, band_margin, flagged in self.bands:
            self.assertAlmostEqual(cost + band_margin, self.price, delta=0.02,
                                   msg=f"{name}: margin must be the subscription less cost")
            self.assertEqual(flagged, band_margin < 0.0,
                             f"{name}: the LOSS flag must mean exactly 'margin below zero'")

        losses = [b for b in self.bands if b[5]]
        self.assertGreaterEqual(len(losses), 1, "at least one band must be sold below cost")
        self.assertLess(sum(b[1] for b in losses), 10.0,
                        "the loss-making accounts must be a small minority of users")
        self.assertEqual(losses, self.bands[-len(losses):],
                         "the loss must sit in the heaviest bands -- it is a tail, not a spread")

        tail = re.search(r"([\d,]+) accounts \(([\d.]+)%\) are sold below\s+"
                         r"cost and together destroy (-?\$[\d,.]+)/month", self.out)
        self.assertIsNotNone(tail, "the recipe must quantify the destroyed margin")
        accounts, pct_users, destroyed = (int(num(tail.group(1))),
                                          float(tail.group(2)), money(tail.group(3)))
        self.assertLess(pct_users, 10.0)
        self.assertGreater(destroyed, 0.0,
                           "below-cost accounts must destroy a positive amount of margin")
        # the prose figure must be the loss bands in the table above it, not a
        # separate claim that could drift away from them
        self.assertAlmostEqual(accounts, sum(self.users * b[1] / 100 for b in losses),
                               delta=max(1.0, accounts * 0.01),
                               msg="the below-cost account count must be the LOSS bands")
        self.assertAlmostEqual(
            destroyed, sum(-b[4] * self.users * b[1] / 100 for b in losses),
            delta=destroyed * 0.02,
            msg="the destroyed margin must reconcile to the LOSS bands' own margins")

    def test_the_median_user_is_far_cheaper_than_the_mean_user(self):
        """Usage is a power law; any average-based cost model prices the wrong customer."""
        m = re.search(r"median user\s+([\d,]+) requests\s+mean user\s+([\d,]+) requests",
                      self.out)
        self.assertIsNotNone(m, "median and mean must be printed side by side")
        median, mean = int(num(m.group(1))), int(num(m.group(2)))
        self.assertGreater(mean, median * 2,
                           "the mean must be dragged well above the median by the tail")
        self.assertLess(median, self.bands[-1][2],
                        "the median user must be nowhere near the heaviest band")


# --- the column that must stay honest ---------------------------------------

class PriceLeversReportZeroTokenChange(unittest.TestCase):
    """Tokens and cost are separate columns; a price lever must not borrow from the other."""

    # 16 re-prices an unchanged request at a threshold, 20 removes billed work
    # nobody received, 21 caps how many requests an account may make. None of
    # the three makes an individual request smaller.
    PRICE_LEVERS = ("16", "21")

    @classmethod
    def setUpClass(cls):
        cls.outs = {stem: run(stem) for stem in cls.PRICE_LEVERS}

    def test_a_price_lever_reports_a_zero_percent_token_change(self):
        """Conflating a cost saving with a token saving is how a team double-counts itself."""
        for stem in self.PRICE_LEVERS:
            with self.subTest(recipe=stem):
                token_pct, cost_pct = result_line(self.outs[stem])
                self.assertAlmostEqual(
                    token_pct, 0.0, delta=0.05,
                    msg=f"recipe {stem} changes the price of a token, not the number of "
                        f"them, so its token column must read 0.0%")
                self.assertLess(cost_pct, 0.0,
                                f"recipe {stem} must still show a cost saving")


if __name__ == "__main__":
    unittest.main(verbosity=2)
