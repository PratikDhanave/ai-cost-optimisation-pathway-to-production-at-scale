#!/usr/bin/env python3
"""Pins the public behaviour of recipes/tools/prefix_lint.py.

The tool's product is partly its REFUSALS: it declines to quote a saving when
the whole template is under the cache minimum, when the stranded tail is small
enough to be where it belongs, and when it cannot tell whether a placeholder
varies per request. Those paths are tested at least as hard as the one path
that does produce a number.

Token counts come from `prefix_lint.count` (tiktoken when importable, the
vendored estimator otherwise), so every fixture here is sized by asking the
tool's own counter rather than by hardcoding a number that would flip when
tiktoken appears or disappears.
"""
import pathlib, sys, unittest

# Works from either layout: tests/ beside the recipes (this repo), or tests/ at
# the root with the recipes under recipes/ (the published extract).
_UP = pathlib.Path(__file__).resolve().parent.parent
RECIPES = _UP if (_UP / "prices.py").exists() else _UP / "recipes"
TOOLSDIR = _UP / "tools" if (_UP / "tools").exists() else RECIPES / "tools"
sys.path.insert(0, str(RECIPES))
sys.path.insert(0, str(TOOLSDIR))

import prefix_lint
import prices as P
from _harness import money



# --- fixtures ----------------------------------------------------------------

# Filler with no placeholder syntax in it: no braces, no "$", no "<".
FILLER = "Be professional and concise in every reply to the customer.\n"


def pad(min_tokens):
    """Stable filler of at least `min_tokens` tokens, measured by the tool."""
    text = ""
    while prefix_lint.count(text) < min_tokens:
        text += FILLER
    return text


def pad_under(limit):
    """Stable filler that stops just short of `limit` tokens."""
    text = ""
    while prefix_lint.count(text + FILLER) < limit:
        text += FILLER
    return text


def run(text, rpd=150_000, path="prompts/t.txt"):
    """Call lint() with a collector instead of print; return (report, returned)."""
    lines = []
    returned = prefix_lint.lint(path, text, rpd, out=lines.append)
    return "\n".join(lines), returned


def sub_minimum_template():
    """A short prompt with the date on line 1 -- nothing here can ever cache."""
    return ("Current date: {today}. Session: {session_id}.\n"
            "You are a support assistant for an online retailer.\n"
            "Be professional and concise.\n"
            "Now classify this ticket: {ticket_text}\n")


def broken_prefix_template():
    """Stable block just under the minimum, then the variable, then a short tail.

    prefix < CACHE_MIN (so nothing caches) but the tail is small enough that the
    HEALTHY rule would fire if the BROKEN rule did not take precedence.
    """
    head = pad_under(P.CACHE_MIN)
    tail = pad(40)
    return head + "Ticket from {user_id}:\n" + tail


# --- what the tool finds -----------------------------------------------------

class FindsTheFirstPerRequestVariable(unittest.TestCase):

    def test_the_first_volatile_placeholder_and_its_line_are_named(self):
        """The whole fix is "move THAT variable", so naming the wrong one sends the reader to the wrong line."""
        text = ("You are a support assistant for an online retailer.\n"
                "Brand voice: {brand}.\n"
                "Never invent order numbers, tracking numbers or amounts.\n"
                "Ticket from {user_id}:\n")
        report, _ = run(text)
        self.assertIn("line 4: {user_id} is the first per-request variable", report)
        # {brand} comes first in the file but is a build-time substitution, not
        # a cache break; blaming it would hide the variable that matters.
        self.assertNotIn("{brand} is the first per-request variable", report)

    def test_every_documented_placeholder_syntax_is_recognised(self):
        """The docstring promises six syntaxes; one unparsed syntax means a silent miss, not an error."""
        text = "A {one} B {{two}} C %(three)s D ${four} E $five F <six>"
        found = list(prefix_lint.placeholders(text))
        self.assertEqual([n for _, n, _ in found],
                         ["one", "two", "three", "four", "five", "six"])
        offsets = [i for i, _, _ in found]
        self.assertEqual(offsets, sorted(offsets))

    def test_volatility_is_guessed_from_the_placeholder_name(self):
        """The verdict rests entirely on this guess, so the name list is the tool's real decision boundary."""
        def volatile(name):
            (_, got, flag), = prefix_lint.placeholders("{%s}" % name)
            self.assertEqual(got, name)
            return flag

        for name in ("user_id", "today", "session", "chat_history",
                     "ticket_text", "query", "timestamp", "uuid",
                     "order_number", "nonce", "random_seed", "input"):
            self.assertTrue(volatile(name), f"{name} should read as per-request")

        for name in ("brand", "tone", "company_policy", "schema",
                     "examples", "rules", "format"):
            self.assertFalse(volatile(name), f"{name} should read as stable")

        # Documented limitation, not a bug to work around: the match is a plain
        # substring, so "candidate" trips the "date" rule. The tool's docstring
        # says the verdict is a prompt to go and look, not a proof.
        self.assertTrue(volatile("candidate"))


# --- the refusals ------------------------------------------------------------

class RefusesToQuoteASaving(unittest.TestCase):

    def test_a_template_under_the_cache_minimum_refuses_and_returns_zero(self):
        """Pricing a reorder that cannot clear the minimum is how a linter invents a saving."""
        text = sub_minimum_template()
        self.assertLess(prefix_lint.count(text), P.CACHE_MIN)
        report, returned = run(text)
        self.assertIn("VERDICT: TOO SHORT TO CACHE", report)
        self.assertIn("Moving the variable changes NOTHING", report)
        self.assertEqual(returned, 0.0)
        # The refusal must not leak a dollar figure anywhere in the report.
        self.assertNotIn("FIX:", report)
        self.assertNotIn("/month at", report)
        self.assertNotIn("$", report)

    def test_a_small_stranded_tail_reports_healthy_and_quotes_nothing(self):
        """Variables below the stable block are correct, not a finding; quoting one would manufacture work."""
        text = pad(2_000) + "Ticket from {user_id}:\n" + pad(20)
        report, returned = run(text)
        self.assertIn("VERDICT: HEALTHY", report)
        self.assertEqual(returned, 0.0)
        self.assertNotIn("FIX:", report)

    def test_placeholders_with_no_obvious_volatility_are_handed_back_for_review(self):
        """The tool cannot see the data, so an unknown placeholder is a question for the reader, not a verdict."""
        text = pad(1_500) + "Brand voice: {brand}. Tone: {tone}.\n"
        report, returned = run(text)
        self.assertIn("none obviously per-request: brand, tone", report)
        self.assertIn("CONFIRM by hand", report)
        self.assertEqual(returned, 0.0)
        self.assertNotIn("VERDICT", report)

    def test_a_template_with_no_placeholders_is_judged_only_against_the_minimum(self):
        """With nothing interpolated there is no reorder to sell; the only live question is size."""
        long_report, long_returned = run(pad(P.CACHE_MIN + 200))
        self.assertIn("whole template is a stable prefix", long_report)
        self.assertIn("CACHEABLE", long_report)
        self.assertEqual(long_returned, 0.0)

        short_report, short_returned = run("Be professional and concise.\n")
        self.assertIn("too short to cache", short_report)
        self.assertEqual(short_returned, 0.0)
        self.assertNotIn("FIX:", short_report)


# --- the one path that produces a number -------------------------------------

class PricesTheReorder(unittest.TestCase):

    def test_a_cacheable_prefix_with_a_large_tail_reports_partial(self):
        """This is the only shape where a reorder genuinely recovers money, so it must be the only one priced."""
        text = pad(1_500) + "Ticket from {user_id}:\n" + pad(1_500)
        report, returned = run(text)
        self.assertIn("VERDICT: partial", report)
        self.assertIn("FIX: move {user_id}", report)
        self.assertGreater(returned, 0.0)

    def test_a_prefix_under_the_minimum_reports_broken_not_healthy(self):
        """A sub-minimum prefix caches nothing and still pays the write premium; calling that HEALTHY inverts the advice."""
        report, returned = run(broken_prefix_template())
        self.assertIn("VERDICT: BROKEN", report)
        self.assertIn("strictly worse than leaving caching switched off", report)
        self.assertNotIn("HEALTHY", report)
        self.assertGreater(returned, 0.0)

    def test_the_returned_figure_is_the_monthly_one_the_report_prints(self):
        """A caller summing return values must be adding the same number the reader was shown."""
        text = pad(1_500) + "Ticket from {user_id}:\n" + pad(1_500)
        report, returned = run(text, rpd=150_000)
        quoted = [ln for ln in report.splitlines() if "/month at" in ln]
        self.assertEqual(len(quoted), 1)
        self.assertIn(money(returned), quoted[0])
        self.assertIn("150,000 req/day", quoted[0])

    def test_the_monthly_figure_scales_linearly_with_requests_per_day(self):
        """Volume is the reader's only input; a non-linear response would mean the per-request gain moved."""
        text = pad(1_500) + "Ticket from {user_id}:\n" + pad(1_500)
        _, at_1k = run(text, rpd=1_000)
        _, at_2k = run(text, rpd=2_000)
        self.assertGreater(at_1k, 0.0)
        self.assertAlmostEqual(at_2k, at_1k * 2, places=6)

    # ---------------------------------------------------------------- DEFECT
    # THIS TEST FAILS AGAINST THE CURRENT CODE AND SHOULD STAY FAILING.
    #
    # prefix_lint.lint() sets `recoverable = stranded` for BOTH the BROKEN and
    # the partial branch (lines 100-101). That is right for `partial`, where
    # prefix_tok already caches and only the tail is recovered. It is wrong for
    # BROKEN: the report itself says "NOTHING caches", so the reorder recovers
    # the whole stable template, not just the tail behind the variable.
    #
    # The two templates below are the same stable content with the same
    # variable, both BROKEN, both caching nothing today and both caching
    # ~everything after the advised reorder -- so they must be priced the same.
    # The tool prices them an order of magnitude apart, because one has its
    # variable on line 1 (stranded == total) and the other has it just past a
    # sub-minimum prefix (stranded == a few dozen tokens). The bug is invisible
    # in --demo precisely because the demo puts the variable on line 1.
    #
    # Fix: in the BROKEN branch, recoverable should be `total`, not `stranded`.
    def test_a_broken_prefix_prices_the_whole_template_not_just_the_tail(self):
        """When nothing caches at all, the reorder recovers the whole stable block, so pricing only the tail understates the fix."""
        late = broken_prefix_template()                 # variable just past a sub-minimum prefix
        body = late.replace("Ticket from {user_id}:\n", "")
        early = "Ticket from {user_id}:\n" + body       # same content, variable on line 1

        late_report, late_value = run(late)
        early_report, early_value = run(early)
        self.assertIn("VERDICT: BROKEN", late_report)
        self.assertIn("VERDICT: BROKEN", early_report)

        self.assertAlmostEqual(
            late_value, early_value, delta=early_value * 0.15,
            msg="identical content, identical caching before and after the fix, "
                "but the quoted saving differs by where the variable sits")


if __name__ == "__main__":
    unittest.main(verbosity=2)
