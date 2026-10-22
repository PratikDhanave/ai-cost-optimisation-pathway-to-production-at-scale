"""Tests for the ADK glue. Skips entirely when google-adk is absent.

These build a real LlmRequest with real tools and assert the callbacks do what
they claim to the actual objects ADK passes. No API key and no model call is
involved -- what cannot be verified without a key is a live turn, and that is
stated in the README rather than faked here.

    pip install google-adk && python3 recipes/agent/test_adk.py
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    from google.adk.agents import LlmAgent
    from google.adk.models import LlmRequest, LlmResponse
    from google.adk.tools import FunctionTool
    HAVE_ADK = True
except Exception:
    HAVE_ADK = False

from cost_plugin import CostPlugin, _declaration_names


def search_docs(query: str) -> str:
    """Search the documentation for a query."""
    return "result"


def send_email(to: str, body: str) -> str:
    """Send an email to a recipient."""
    return "sent"


def delete_everything(confirm: bool) -> str:
    """Delete all records."""
    return "done"


def _request(model="gemini-2.5-pro"):
    r = LlmRequest(model=model)
    r.append_tools([FunctionTool(func=f) for f in
                    (search_docs, send_email, delete_everything)])
    return r


@unittest.skipUnless(HAVE_ADK, "google-adk not installed")
class TestToolPruning(unittest.TestCase):
    def test_all_declarations_are_present_to_begin_with(self):
        self.assertEqual(sorted(_declaration_names(_request())),
                         ["delete_everything", "search_docs", "send_email"])

    def test_nothing_is_pruned_when_pruning_is_off(self):
        p = CostPlugin()
        r = _request()
        for _ in range(20):
            p.before_model(None, r)
            p.tracker.end_turn()
        self.assertEqual(len(_declaration_names(r)), 3)

    def test_unused_declarations_are_removed_from_the_real_request(self):
        p = CostPlugin(prune_unused_after=3)
        for turn in range(4):
            r = _request()
            p.before_model(None, r)
            p.before_tool(tool=FunctionTool(func=search_docs))
            p.tracker.end_turn()
        r = _request()
        p.before_model(None, r)
        names = _declaration_names(r)
        self.assertIn("search_docs", names)
        self.assertNotIn("send_email", names)
        self.assertNotIn("delete_everything", names)


@unittest.skipUnless(HAVE_ADK, "google-adk not installed")
class TestBudgetBehaviour(unittest.TestCase):
    def test_downgrade_rewrites_the_model_on_the_request(self):
        p = CostPlugin(budget_usd=1.00, cheap_model="gemini-2.5-flash")
        p.budget.spent_usd = 0.90
        r = _request(model="gemini-2.5-pro")
        self.assertIsNone(p.before_model(None, r))
        self.assertEqual(r.model, "gemini-2.5-flash")
        self.assertEqual(p.downgrades, 1)

    def test_downgrade_cannot_happen_without_a_cheap_model_configured(self):
        p = CostPlugin(budget_usd=1.00)
        p.budget.spent_usd = 0.90
        r = _request(model="gemini-2.5-pro")
        p.before_model(None, r)
        self.assertEqual(r.model, "gemini-2.5-pro")
        self.assertEqual(p.downgrades, 0)

    def test_stop_short_circuits_with_a_response_instead_of_calling_the_model(self):
        p = CostPlugin(budget_usd=1.00, stop_message="no more budget")
        p.budget.spent_usd = 1.50
        out = p.before_model(None, _request())
        self.assertIsInstance(out, LlmResponse)
        self.assertIn("no more budget", out.content.parts[0].text)


@unittest.skipUnless(HAVE_ADK, "google-adk not installed")
class TestMetering(unittest.TestCase):
    def test_usage_from_a_response_lands_on_the_budget(self):
        p = CostPlugin(budget_usd=10.0)
        p._last_model = "gemini-2.5-pro"

        class U:
            prompt_token_count = 1_000_000
            candidates_token_count = 0
            cached_content_token_count = 0

        p.after_model(None, LlmResponse(usage_metadata=U()))
        self.assertAlmostEqual(p.budget.spent_usd, 1.25, places=4)
        self.assertEqual(p.turns, 1)

    def test_an_unrecognised_model_is_counted_as_uncosted(self):
        p = CostPlugin(budget_usd=10.0)
        p._last_model = "some-local-llama"

        class U:
            prompt_token_count = 1_000_000
            candidates_token_count = 0

        p.after_model(None, LlmResponse(usage_metadata=U()))
        self.assertEqual(p.budget.spent_usd, 0.0)
        self.assertEqual(p.budget.unknown_turns, 1)
        self.assertIn("UNRECOGNISED", p.report())


@unittest.skipUnless(HAVE_ADK, "google-adk not installed")
class TestInstall(unittest.TestCase):
    def test_install_wires_all_three_callbacks(self):
        agent = LlmAgent(name="a", model="gemini-2.5-pro")
        CostPlugin().install(agent)
        for attr in ("before_model_callback", "after_model_callback",
                     "before_tool_callback"):
            self.assertIsNotNone(getattr(agent, attr), attr)

    def test_install_preserves_a_callback_that_was_already_set(self):
        seen = []

        def mine(callback_context=None, llm_request=None):
            seen.append(1)
            return None

        agent = LlmAgent(name="a", model="gemini-2.5-pro",
                         before_model_callback=mine)
        CostPlugin().install(agent)
        agent.before_model_callback(None, _request())
        self.assertEqual(seen, [1])


if __name__ == "__main__":
    if not HAVE_ADK:
        print("google-adk is not installed: ADK glue tests skipped.")
    unittest.main(verbosity=2)
