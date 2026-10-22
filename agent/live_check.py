#!/usr/bin/env python3
"""Verify the usage extractor against a REAL provider response.

The one thing the offline tests cannot prove: that a live provider reports
usage in the shape cost_core expects. This runs a couple of cheap turns and
prints the raw usage object beside what the extractor made of it, so any
mismatch is visible rather than silently costing nothing.

    GOOGLE_API_KEY=$(cat ~/.gemini_key) python3 live_check.py
"""
import asyncio, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cost_core import price, read_usage, resolve
from cost_plugin import CostPlugin

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool
from google.genai import types

MODEL = os.environ.get("LIVE_MODEL", "gemini-2.5-flash")


def get_weather(city: str) -> str:
    """Return the current weather for a city."""
    return f"{city}: 18C, clear."


async def main():
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        print("  no key in the environment"); return 1

    captured = []
    plugin = CostPlugin(budget_usd=1.00, prune_unused_after=0)
    orig = plugin.after_model

    def spy(callback_context=None, llm_response=None):
        um = getattr(llm_response, "usage_metadata", None)
        if um is not None:
            captured.append(um)
        return orig(callback_context, llm_response)

    plugin.after_model = spy

    agent = LlmAgent(name="live", model=MODEL,
                     instruction="Answer in one short sentence.",
                     tools=[FunctionTool(func=get_weather)])
    plugin.install(agent)
    runner = InMemoryRunner(agent=agent, app_name="live")
    s = await runner.session_service.create_session(app_name="live", user_id="u")

    print(f"  model: {MODEL}   provider match: "
          f"{(resolve(MODEL).name if resolve(MODEL) else 'UNRECOGNISED')}")
    for q in ("Say hello in five words.", "What is the weather in Bengaluru?"):
        msg = types.Content(role="user", parts=[types.Part(text=q)])
        async for _ in runner.run_async(user_id="u", session_id=s.id,
                                        new_message=msg):
            pass

    print(f"\n  {len(captured)} usage object(s) returned by the live provider\n")
    ok = True
    for i, um in enumerate(captured, 1):
        fields = {k: v for k, v in (um.model_dump().items()
                  if hasattr(um, "model_dump") else vars(um).items())
                  if isinstance(v, int)}
        u = read_usage(um)
        c = price(MODEL, u)
        print(f"  turn {i}")
        print(f"    raw integer fields : {fields}")
        if u is None:
            print("    EXTRACTOR FAILED: no usable fields found"); ok = False; continue
        print(f"    extractor read     : in={u.in_tokens} out={u.out_tokens} "
              f"cached={u.cached_in}")
        print(f"    costed             : "
              f"{'$%.6f' % c.usd if c.known else 'NOT COSTED - ' + c.reason}")
        raw_in = fields.get("prompt_token_count")
        if raw_in is not None and raw_in != u.in_tokens:
            print(f"    MISMATCH: provider said {raw_in}, extractor read {u.in_tokens}")
            ok = False
    print()
    print(plugin.report())
    print()
    print("  VERDICT:", "extractor matches this provider's shape" if ok
          else "EXTRACTOR NEEDS FIXING for this provider")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
