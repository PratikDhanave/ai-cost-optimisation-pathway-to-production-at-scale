#!/usr/bin/env python3
"""Pins the claims recipes 06-10 print, from their stdout only.

These recipes EXECUTE on import and their filenames start with digits, so each
one is run as a subprocess once per test class and the claim is read back out of
the report. Figures are parsed and asserted as RELATIONSHIPS, never as literal
strings: every rate in prices.py is overridable with PRICE_IN / PRICE_OUT /
VOLUME, so a pinned decimal would pin the environment rather than the claim.

The load-bearing invariant across the set is the tokens/cost split: 07 and 08
are PRICE levers and must print a token change of exactly 0.0%, because
borrowing a cost saving into the token column is how a team double-counts its
own savings.
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

import prices as P                                     # noqa: E402  (no side effects)



def run(stem):
    p = subprocess.run([sys.executable, str(next(RECIPES.glob(stem + "_*.py")))],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-800:]
    return p.stdout


# --- readers -----------------------------------------------------------------

MONEY = re.compile(r"-?\$[\d,]+(?:\.\d+)?")
TOKEN_ROW = re.compile(
    r"^\s{2}(\S.*?)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)(?:\s+([+-]?[\d.]+)%)?\s*$")
RESULT = re.compile(
    r"RESULT: TOKENS ([+-][\d.]+)%\s+\|\s+COST ([+-][\d.]+)%"
    r"(?:\s+\|\s+SAVES (-?\$[\d,.]+)/mo)?")


def dollars(token):
    """'$1,234.50' / '-$0.0078' -> float. The report is text; figures come back out of it."""
    return (-1.0 if token.startswith("-") else 1.0) * float(
        token.replace("-", "").replace("$", "").replace(",", ""))


def _table(out, header):
    """The row lines of the first block titled `header` (TOKENS or COST)."""
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == header)
    rows = []
    for ln in lines[start + 2:]:               # +1 title, +2 column headings
        if not ln.strip():
            break
        rows.append(ln)
    return rows


def token_table(out):
    """label -> {'in','out','total','change'}; change is None on the baseline row."""
    table = {}
    for ln in _table(out, "TOKENS"):
        m = TOKEN_ROW.match(ln)
        assert m, f"unparsed TOKENS row: {ln!r}"
        label, i, o, t, ch = m.groups()
        table[label.strip()] = {"in": int(i.replace(",", "")),
                                "out": int(o.replace(",", "")),
                                "total": int(t.replace(",", "")),
                                "change": None if ch is None else float(ch)}
    return table


def cost_table(out):
    """label -> {'unit','day','month','change'}; day/month absent when no volume."""
    table = {}
    for ln in _table(out, "COST"):
        found = MONEY.findall(ln)
        assert found, f"unparsed COST row: {ln!r}"
        label = ln[:ln.index(found[0])].strip()
        row = {"unit": dollars(found[0]), "change": None}
        if len(found) > 1:
            row["day"], row["month"] = dollars(found[1]), dollars(found[2])
        pct = re.search(r"([+-][\d.]+)%\s*$", ln)
        if pct:
            row["change"] = float(pct.group(1))
        table[label] = row
    return table


def result(out):
    """The machine-readable RESULT line: (token_cut_pct, cost_cut_pct, monthly_saving)."""
    m = RESULT.search(out)
    assert m, "no RESULT line"
    return (float(m.group(1)), float(m.group(2)),
            None if m.group(3) is None else dollars(m.group(3)))


def one(table, needle):
    """The single row whose label contains `needle` -- labels carry alignment spaces."""
    hits = [v for k, v in table.items() if needle in k]
    assert len(hits) == 1, f"{needle!r} matched {len(hits)} rows in {list(table)}"
    return hits[0]


class Recipe(unittest.TestCase):
    """Runs its recipe once for the whole class -- 21 subprocesses per test is not free."""
    STEM = None

    @classmethod
    def setUpClass(cls):
        if cls.STEM is None:
            raise unittest.SkipTest("base class")
        cls.OUT = run(cls.STEM)

    def assertClose(self, got, want, rel=0.01, msg=None):
        """Printed money is rounded to 4 or 6 dp, so compare within a tolerance."""
        self.assertAlmostEqual(got, want, delta=max(abs(want) * rel, 1e-6), msg=msg)


# --- 06 -- conversation history ----------------------------------------------

class Recipe06HistoryWindow(Recipe):
    STEM = "06"

    def test_a_twenty_turn_conversation_bills_several_times_its_own_tokens(self):
        """The whole mechanism: each request looks reasonable while the conversation bills a multiple."""
        linear = int(re.search(r"if each turn cost only its own tokens\s+([\d,]+) tokens",
                               self.OUT).group(1).replace(",", ""))
        full, printed_x = re.search(
            r"what a full-history conversation bills\s+([\d,]+) tokens\s+([\d.]+)x",
            self.OUT).groups()
        full = int(full.replace(",", ""))
        self.assertGreater(full, 3 * linear,
                           "full history must bill several times the per-turn total")
        self.assertClose(float(printed_x), full / linear, rel=0.02)
        self.assertEqual(full, one(token_table(self.OUT), "full history")["in"],
                         "the note and the TOKENS table must quote the same figure")

    def test_windowing_history_cuts_input_tokens_and_leaves_output_untouched(self):
        """Windowing is a token lever, and it is an input-side one -- the reply length never moves."""
        toks = token_table(self.OUT)
        full, win = one(toks, "full history"), one(toks, "last 6 turns")
        self.assertEqual(full["out"], win["out"], "windowing must not change output tokens")
        self.assertLess(win["in"], full["in"])
        claimed = float(re.search(r"removes (\d+)% of input tokens", self.OUT).group(1))
        measured = (1 - win["in"] / full["in"]) * 100
        self.assertAlmostEqual(claimed, measured, delta=1.0,
                               msg="the verdict's input-side cut must match the table")
        self.assertLess(result(self.OUT)[0], -20.0)

    def test_window_before_cache_is_strictly_cheaper_than_window_alone(self):
        """The recipe's order-of-operations claim: composing the two levers must beat either one."""
        costs = cost_table(self.OUT)
        full = one(costs, "full history")["unit"]
        win = one(costs, "last 6 turns")["unit"]
        both = one(costs, "cached prefix")["unit"]
        self.assertLess(win, full)
        self.assertLess(both, win)
        self.assertClose(result(self.OUT)[2], (full - win) * 30 *
                         int(re.search(r"at ([\d,]+) conversations/day",
                                       self.OUT).group(1).replace(",", "")))


# --- 07 -- batch tier ---------------------------------------------------------

class Recipe07BatchAsync(Recipe):
    STEM = "07"

    def test_the_batch_tier_cuts_exactly_zero_percent_of_tokens(self):
        """Batch is a PRICE lever: a non-zero token column here would double-count the saving."""
        toks = token_table(self.OUT)
        live, batch = one(toks, "live tier"), one(toks, "batch tier")
        self.assertEqual((live["in"], live["out"]), (batch["in"], batch["out"]))
        self.assertAlmostEqual(batch["change"], 0.0, delta=0.05)
        self.assertAlmostEqual(result(self.OUT)[0], 0.0, delta=0.05,
                               msg="RESULT must print a 0.0% token change")

    def test_the_batch_rate_is_the_published_multiplier_on_both_directions(self):
        """The discount must come from P.BATCH, not from a figure hardcoded in the recipe."""
        costs = cost_table(self.OUT)
        live, batch = one(costs, "live tier")["unit"], one(costs, "batch tier")["unit"]
        self.assertClose(batch / live, P.BATCH, rel=0.005)

    def test_the_blended_saving_is_smaller_than_the_discount_because_live_traffic_stays(self):
        """Applying the rate to the whole bill instead of the batchable share is the standard overstatement."""
        share = re.search(r"([\d,]+) of ([\d,]+) requests", self.OUT).groups()
        batchable, total = (int(s.replace(",", "")) for s in share)
        self.assertLess(batchable, total, "some traffic must stay on the live tier")
        cost_cut = -result(self.OUT)[1]
        self.assertLess(cost_cut, (1 - P.BATCH) * 100,
                        "the blended cut cannot reach the batch discount itself")
        self.assertAlmostEqual(cost_cut, batchable / total * (1 - P.BATCH) * 100, delta=0.6)


# --- 08 -- model routing ------------------------------------------------------

class Recipe08ModelRouting(Recipe):
    STEM = "08"

    def test_routing_cuts_exactly_zero_percent_of_tokens(self):
        """Routing is the third PRICE lever in the set; same request, different rate card."""
        toks = token_table(self.OUT)
        big, small = one(toks, "big model"), one(toks, "small model")
        self.assertEqual((big["in"], big["out"]), (small["in"], small["out"]))
        self.assertAlmostEqual(small["change"], 0.0, delta=0.05)
        self.assertAlmostEqual(result(self.OUT)[0], 0.0, delta=0.05)

    def test_an_escalated_request_pays_the_small_model_and_the_big_one_on_top(self):
        """The term every routing estimate leaves out: escalation buys two inferences, not one."""
        costs = cost_table(self.OUT)
        big = one(costs, "all big")["unit"]
        small = one(costs, "all small")["unit"]
        for rate in (0.08, 0.25, 0.60):
            row = one(costs, f"{int(rate * 100)}% escalate")["unit"]
            self.assertClose(row, small + rate * big, rel=0.01,
                             msg=f"cascade at {rate:.0%} must bill small + {rate:.0%} x big")

    def test_the_cascade_stops_saving_above_the_printed_escalation_rate(self):
        """Past the break-even the cascade costs MORE than sending everything to the big model."""
        costs = cost_table(self.OUT)
        big = one(costs, "all big")["unit"]
        small = one(costs, "all small")["unit"]
        printed = float(re.search(r"escalation rate of\s+([\d.]+)%", self.OUT, re.S).group(1))
        self.assertAlmostEqual(printed, (big - small) / big * 100, delta=0.6)
        cascade = lambda r: small + r * big
        self.assertClose(cascade(printed / 100), big, rel=0.01)
        self.assertGreater(cascade(printed / 100 + 0.05), big,
                           "above break-even the cascade must be more expensive than all-big")
        self.assertLess(cascade(printed / 100 - 0.05), big)
        for rate in (0.08, 0.25, 0.60):      # each shown row must sit on the right side of it
            row = one(costs, f"{int(rate * 100)}% escalate")["unit"]
            if rate < printed / 100 - 0.01:
                self.assertLess(row, big, f"{rate:.0%} is below break-even and must save")
            elif rate > printed / 100 + 0.01:
                self.assertGreater(row, big, f"{rate:.0%} is above break-even and must cost more")


# --- 09 -- RAG context budget -------------------------------------------------

class Recipe09RagContextBudget(Recipe):
    STEM = "09"

    def test_cutting_top_k_from_twenty_to_five_removes_most_of_the_tokens(self):
        """top_k is a billed parameter: the demo default is paid on every request, forever."""
        toks = token_table(self.OUT)
        k20 = one(toks, "top_k=20")
        k5 = one(toks, "top_k=5,  full chunks")
        trimmed = one(toks, "reranked")
        self.assertGreater(k20["in"], 3 * k5["in"])
        self.assertLess(trimmed["in"], k5["in"], "reranking and trimming must cut further than k alone")
        self.assertLess(trimmed["change"], -70.0, "the headline claim is a huge token cut")
        self.assertLess(result(self.OUT)[0], -70.0)

    def test_the_token_cut_is_larger_than_the_cost_cut_because_output_is_untouched(self):
        """Input-only levers under-deliver on cost: the untouched output side bills at a premium."""
        toks = token_table(self.OUT)
        self.assertEqual(len({r["out"] for r in toks.values()}), 1,
                         "every row must answer with the same output budget")
        token_cut, cost_cut, _ = result(self.OUT)
        self.assertLess(token_cut, cost_cut,
                        "a cost cut at least as big as the token cut would mean output moved too")
        self.assertGreater(P.OUTPUT_PREMIUM, 1.0)


# --- 10 -- agent loops and the max_tokens trap --------------------------------

class Recipe10AgentLoops(Recipe):
    STEM = "10"

    def test_an_agent_run_bills_an_order_of_magnitude_more_than_one_call(self):
        """The quadratic growth of recipe 06 arrives multiplied by the step count."""
        one_shot = int(re.search(r"a single non-agentic call would bill\s+([\d,]+) input",
                                 self.OUT).group(1).replace(",", ""))
        full, printed_x = re.search(r"the agent run bills\s+([\d,]+) input tokens\s+([\d.]+)x",
                                    self.OUT).groups()
        full = int(full.replace(",", ""))
        self.assertGreater(full / one_shot, 10.0, "the agent multiplier is the point of the recipe")
        self.assertClose(float(printed_x), full / one_shot, rel=0.02)
        self.assertEqual(full, one(token_table(self.OUT), "full trace")["in"])

    def test_a_low_max_tokens_cap_leaves_the_bill_per_attempt_unchanged(self):
        """max_tokens saves nothing: a truncated turn is discarded and still billed in full."""
        attempt = dollars(re.search(r"cost per ATTEMPT\s+(\$[\d,.]+)", self.OUT).group(1))
        per_run = one(cost_table(self.OUT), "full trace")["unit"]
        self.assertClose(attempt, per_run, rel=0.001,
                         msg="capping max_tokens must not move the per-attempt cost")

    def test_a_low_max_tokens_cap_raises_cost_per_solved_task(self):
        """The cap makes it WORSE under the only honest denominator -- cost per completed task."""
        low, high = (dollars(t) for t in re.search(
            r"cost per SOLVED\s+(\$[\d,.]+)\s+vs\s+(\$[\d,.]+)", self.OUT).groups())
        attempt = dollars(re.search(r"cost per ATTEMPT\s+(\$[\d,.]+)", self.OUT).group(1))
        truncated = float(re.search(r"(\d+)% of attempts end on the cap", self.OUT).group(1)) / 100
        self.assertClose(high, attempt, rel=0.001, msg="the high cap truncates nothing")
        self.assertGreater(low, high, "a truncated share must raise cost per solved task")
        self.assertClose(low, attempt / (1 - truncated), rel=0.01)
        worse = float(re.search(r"\+(\d+)% per solved task", self.OUT).group(1))
        self.assertGreater(worse, 0.0)
        self.assertAlmostEqual(worse, (low / high - 1) * 100, delta=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
