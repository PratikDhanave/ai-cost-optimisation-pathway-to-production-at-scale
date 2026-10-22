#!/usr/bin/env python3
"""Pins the behaviour of recipes/tools/cost_gate.py -- the prompt token gate.

The tool's product is an exit code a CI job can trust: 0 when prompt tokens
stayed inside tolerance, non-zero when they did not, and an honest report of
templates that appeared or disappeared instead of a silent pass. These tests
pin that contract, the drift/cost framing, and the places where the tool
declines to produce a number at all.

Two tests are expected to FAIL against the tool as it stands. They are marked
DEFECT and they assert the tool's own documented contract; they are not
weakened to green. See the notes at each one.
"""
import contextlib
import io
import json
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

import cost_gate                              # noqa: E402
import prices as P                            # noqa: E402



def gate(current, baseline, tol=3.0, rpd=150_000):
    """Run check() with its output captured. Returns (ok, failures, text)."""
    lines = []
    ok, failures = cost_gate.check(current, baseline, tol, rpd, out=lines.append)
    return ok, failures, "\n".join(lines)


def drift_pct(text):
    m = re.search(r"TOKENS\s+[\d,]+ -> [\d,]+\s+\(([-+][\d.]+)%\)", text)
    return None if m is None else float(m.group(1))


def monthly_usd(text):
    m = re.search(r"COST\s+([-+][\d,.]+) USD/month", text)
    return None if m is None else float(m.group(1).replace(",", ""))


def cli(*argv):
    """Run main() as CI would. Returns (exit_code, stdout)."""
    saved = sys.argv
    out = io.StringIO()
    try:
        sys.argv = ["cost_gate.py", *argv]
        with contextlib.redirect_stdout(out):
            code = cost_gate.main()
        return code, out.getvalue()
    finally:
        sys.argv = saved


class ToleranceVerdict(unittest.TestCase):
    """The pass/fail decision is the only output CI reads."""

    def test_growth_inside_the_tolerance_passes_the_gate(self):
        """A gate that fires on every edit gets disabled in a week."""
        ok, failures, text = gate({"classify.txt": 1010}, {"classify.txt": 1000})
        self.assertTrue(ok)
        self.assertEqual(failures, [])
        self.assertIn("ok", text)

    def test_growth_past_the_tolerance_fails_and_names_the_offending_template(self):
        """A red build nobody can attribute to a file gets ignored like a flaky test."""
        ok, failures, text = gate(
            {"classify.txt": 1200, "summarise.txt": 500},
            {"classify.txt": 1000, "summarise.txt": 500},
        )
        self.assertFalse(ok)
        self.assertEqual(len(failures), 1)
        name, before, after, delta = failures[0]
        self.assertEqual((name, before, after), ("classify.txt", 1000, 1200))
        self.assertAlmostEqual(delta, 20.0, places=6)
        self.assertRegex(text, r"classify\.txt.*FAIL \(> 3%\)")

    def test_growth_of_exactly_the_tolerance_is_allowed(self):
        """The tool documents 3% as allowed drift, so the boundary itself must not block a PR."""
        # DEFECT -- FAILS TODAY, LEFT FAILING ON PURPOSE.
        # check() compares (c / b - 1) * 100 > tol_pct with no epsilon, and
        # (1030 / 1000 - 1) * 100 == 3.0000000000000027 in binary floating
        # point. Exactly the permitted drift is therefore reported as
        # "FAIL (> 3%)". The same arithmetic lands under the line at other
        # tolerances (2% passes), so identical drift blocks or passes depending
        # on the threshold chosen. The fix belongs in the tool, not here.
        ok, failures, _ = gate({"classify.txt": 1030}, {"classify.txt": 1000}, tol=3.0)
        self.assertTrue(ok, f"exactly 3.0% drift was blocked: {failures}")


class TemplateInventory(unittest.TestCase):
    """Appearing and disappearing templates are the easiest way to hide tokens."""

    def test_a_new_template_is_reported_as_new_and_with_no_baseline_at_all_no_drift_is_invented(self):
        """A prompt absent from the baseline is unreviewed tokens, not zero tokens."""
        ok, failures, text = gate(
            {"classify.txt": 1000, "triage.txt": 4000}, {"classify.txt": 1000}
        )
        self.assertRegex(text, r"triage\.txt.*NEW \(add to baseline\)")
        self.assertIn("4,000", text)
        # Pinned as reported-but-not-blocking: a new template cannot have a
        # percentage, so it is surfaced for a human instead of failing the gate.
        # Its tokens still land in the portfolio total.
        self.assertTrue(ok)
        self.assertEqual(failures, [])
        self.assertEqual(drift_pct(text), 400.0)

        # Refusal: with nothing in the baseline there is no ratio to state, and
        # the tool withholds the drift and cost lines rather than inventing one.
        ok, failures, text = gate({"classify.txt": 4000}, {})
        self.assertIsNone(drift_pct(text))
        self.assertIsNone(monthly_usd(text))
        self.assertNotIn("TOKENS", text)
        self.assertNotIn("COST", text)
        self.assertTrue(ok)
        self.assertEqual(failures, [])

    def test_a_removed_template_is_reported_as_removed_rather_than_silently_ignored(self):
        """A template that vanished may have been renamed, which would double-count a saving."""
        ok, failures, text = gate({"classify.txt": 1000}, {"classify.txt": 1000, "old.txt": 4000})
        self.assertRegex(text, r"old\.txt.*REMOVED")
        self.assertTrue(ok)
        self.assertEqual(failures, [])
        self.assertEqual(drift_pct(text), -80.0)

    def test_a_template_that_grew_from_zero_tokens_is_not_reported_as_ok(self):
        """An empty template filling up is unbounded growth, and the gate's whole job is to say so."""
        # DEFECT -- FAILS TODAY, LEFT FAILING ON PURPOSE.
        # check() guards the division with `if b else 0.0`, so a baseline of 0
        # tokens yields delta == 0.0 and the verdict "ok". A placeholder prompt
        # committed empty and later filled with 4,000 tokens is therefore
        # reported as "+0.0%  ok" and exits 0 -- a positive claim of safety
        # about the largest possible regression. A zero baseline needs the NEW
        # treatment (or a failure), not a fabricated 0.0%.
        ok, failures, text = gate({"classify.txt": 4000}, {"classify.txt": 0})
        self.assertNotRegex(
            text, r"classify\.txt.*\+0\.0%\s+ok",
            f"0 -> 4,000 tokens was reported as unchanged and ok (ok={ok}, failures={failures})",
        )


class DriftAndCostFraming(unittest.TestCase):
    """The totals line is what gets pasted into the PR, so it has to be right."""

    def test_the_drift_percentage_is_the_portfolio_total_not_the_worst_template(self):
        """Portfolio-flat drift must not excuse a single template's step change."""
        ok, failures, text = gate(
            {"a.txt": 1100, "b.txt": 900}, {"a.txt": 1000, "b.txt": 1000}
        )
        self.assertEqual(drift_pct(text), 0.0)      # totals cancel out
        self.assertFalse(ok)                        # but a.txt still blocks
        self.assertEqual([f[0] for f in failures], ["a.txt"])

    def test_the_cost_framing_scales_with_the_stated_request_volume(self):
        """The dollar line is a per-request delta times volume, so volume must actually move it."""
        current, baseline = {"a.txt": 2000}, {"a.txt": 1000}
        _, _, at_1k = gate(current, baseline, rpd=1_000)
        _, _, at_2k = gate(current, baseline, rpd=2_000)
        rate = P.MODELS["big"][0]
        self.assertAlmostEqual(monthly_usd(at_1k), 1000 / 1e6 * rate * 1_000 * 30, places=2)
        self.assertAlmostEqual(monthly_usd(at_2k), 2 * monthly_usd(at_1k), places=2)
        self.assertIn("1,000 requests/day", at_1k)
        self.assertIn(f"input rate ${rate:.2f}/1M", at_1k)

    def test_a_reduction_is_reported_as_improved_and_priced_as_a_saving(self):
        """Cutting a prompt must never be punished, or nobody will cut one."""
        ok, failures, text = gate({"a.txt": 1000}, {"a.txt": 2000}, rpd=1_000)
        self.assertTrue(ok)
        self.assertEqual(failures, [])
        self.assertIn("improved", text)
        self.assertNotIn("FAIL", text)
        self.assertLess(monthly_usd(text), 0)


class ScanAndCli(unittest.TestCase):
    """What counts as a template, and the exit code CI consumes."""

    def test_scan_counts_only_prompt_suffixes_and_keys_them_by_relative_path(self):
        """Counting source files or JSON baselines as prompts would make every number noise."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "classify.txt").write_text("Classify the ticket. Reply with JSON.\n")
            (root / "sub").mkdir()
            (root / "sub" / "summarise.md").write_text("Summarise in three bullets.\n")
            (root / "helper.py").write_text("print('not a prompt')\n")
            (root / "baseline.json").write_text("{}\n")

            scanned = cost_gate.scan(root)
            self.assertEqual(sorted(scanned), ["classify.txt", "sub/summarise.md"])
            self.assertTrue(all(v > 0 for v in scanned.values()))
            # A single file is keyed by its own name, so a file and a directory
            # scan produce the same key for the same template.
            self.assertEqual(
                sorted(cost_gate.scan(root / "classify.txt")), ["classify.txt"]
            )

    def test_comparing_without_a_baseline_refuses_rather_than_assuming_one(self):
        """Treating a missing baseline as "no change" would make the gate silently inert."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "classify.txt").write_text("Classify the ticket.\n")
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                cli(str(root))
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("--baseline is required", err.getvalue())

    def test_the_cli_writes_a_baseline_then_exits_nonzero_when_a_prompt_bloats(self):
        """The exit code is the product: green on the committed baseline, red after the bloat."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            prompt = root / "classify.txt"
            prompt.write_text("Classify the ticket. Reply with JSON: category, confidence.\n")
            baseline = root / "baseline.json"

            code, out = cli("--update", str(baseline), str(root))
            self.assertEqual(code, 0)
            self.assertIn("baseline written", out)
            self.assertEqual(list(json.loads(baseline.read_text())), ["classify.txt"])

            code, out = cli("--baseline", str(baseline), str(root))
            self.assertEqual(code, 0)
            self.assertIn("PASSED", out)

            prompt.write_text(
                prompt.read_text()
                + "Please be very careful and thorough. Think step by step about which\n"
                  "category fits best before you answer. It is very important to be accurate.\n"
            )
            code, out = cli("--baseline", str(baseline), str(root))
            self.assertEqual(code, 1)
            self.assertIn("FAILED", out)
            self.assertIn("FAIL (> 3%)", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
