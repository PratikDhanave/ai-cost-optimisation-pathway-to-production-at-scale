#!/usr/bin/env python3
"""A minimal ADK agent with cost control wired in.

Runs the wiring without a key so you can see the shape; an actual turn needs
whatever credentials your model requires.

    python3 example_agent.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cost_plugin import CostPlugin


def search_docs(query: str) -> str:
    """Search the documentation for a query."""
    return f"(results for {query})"


def send_email(to: str, body: str) -> str:
    """Send an email to a recipient."""
    return "sent"


def main():
    try:
        from google.adk.agents import LlmAgent
        from google.adk.tools import FunctionTool
    except ImportError:
        print("google-adk is not installed.  pip install -r requirements.txt")
        return 1

    plugin = CostPlugin(
        budget_usd=5.00,                 # 0 would disable the budget
        cheap_model="gemini-2.5-flash",  # None means a downgrade cannot happen
        prune_unused_after=5,            # 0 would disable pruning
    )
    agent = LlmAgent(
        name="assistant",
        model="gemini-2.5-pro",
        instruction="Answer concisely. Use a tool only when it is needed.",
        tools=[FunctionTool(func=search_docs), FunctionTool(func=send_email)],
    )
    plugin.install(agent)

    print(f"  agent     : {agent.name} on {agent.model}")
    print(f"  tools     : {len(agent.tools)}")
    print(f"  callbacks : before_model, after_model, before_tool  -> installed")
    print()
    print(plugin.report())
    print()
    print("  Run it with: adk web   (from this directory, with model credentials set)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
