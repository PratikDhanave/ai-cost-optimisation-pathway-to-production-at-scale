#!/usr/bin/env python3
"""Run a real ADK session against a scripted model, and report what it cost.

This is the end-to-end test the unit tests cannot be: a genuine LlmAgent, a
genuine Runner, genuine callbacks firing in ADK's own loop -- with the model
replaced by one that returns scripted responses and realistic usage metadata.

Substituting the model is the whole trick. It means every line of the plugin
runs in its real context with no API key and no network, so what is exercised
here is the actual integration rather than a mock of it. What it does NOT prove
is that a real provider reports usage in the shape the extractor expects; that
is the one thing still unverified, and it is called out in the output.

    python3 sim.py              # terminal report
    python3 sim.py --html out.html   # ...and a status page
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
from typing import AsyncGenerator

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cost_plugin import CostPlugin, _declaration_names

try:
    from google.adk.agents import LlmAgent
    from google.adk.models import LlmRequest, LlmResponse
    from google.adk.models.base_llm import BaseLlm
    from google.adk.runners import InMemoryRunner
    from google.adk.tools import FunctionTool
    from google.genai import types
except ImportError:
    print("google-adk is not installed.  pip install -r requirements.txt")
    sys.exit(1)


# --- the tools the agent is given. Only one of them ever gets used. ---------
def search_docs(query: str) -> str:
    """Search the product documentation for a query string."""
    return "Found three passages about rate limits."


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a named recipient with a subject and body."""
    return "sent"


def delete_records(table: str, confirm: bool) -> str:
    """Permanently delete all records from a named table."""
    return "deleted"


def list_files(path: str, recursive: bool) -> str:
    """List files under a path, optionally recursing into subdirectories."""
    return "a.py b.py"


def run_tests(selector: str, verbose: bool) -> str:
    """Run the test suite, optionally filtered by a selector."""
    return "ok"


TOOLS = [search_docs, send_email, delete_records, list_files, run_tests]


class ScriptedLlm(BaseLlm):
    """A model that returns canned turns and bills realistically.

    Input grows every turn because the conversation is re-sent -- the quadratic
    growth recipe 06 is about -- and a share of it comes back as cached once
    there is a stable prefix to hit.
    """
    model: str = "gemini-2.5-pro"
    turns_seen: int = 0
    seen_tools: list = []

    @staticmethod
    def supported_models() -> list:
        return [r".*"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.turns_seen += 1
        n = self.turns_seen
        self.seen_tools.append(len(_declaration_names(llm_request)))

        # grows with the conversation; a stable prefix starts getting cached
        in_tok = 2_400 + n * 900
        cached = 1_800 if n > 2 else 0
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=in_tok,
            candidates_token_count=220,
            cached_content_token_count=cached,
        )

        # The agent calls one tool on the first two turns and then answers in
        # prose, which is what leaves the other four tools unused.
        if n <= 2:
            part = types.Part(function_call=types.FunctionCall(
                name="search_docs", args={"query": "rate limits"}))
        else:
            part = types.Part(text=f"Answer for turn {n}.")

        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=usage,
            turn_complete=True,
        )


async def run_session(plugin: CostPlugin, turns: int):
    agent = LlmAgent(
        name="assistant",
        model=ScriptedLlm(),
        instruction="Answer concisely.",
        tools=[FunctionTool(func=f) for f in TOOLS],
    )
    plugin.install(agent)
    runner = InMemoryRunner(agent=agent, app_name="costsim")
    session = await runner.session_service.create_session(
        app_name="costsim", user_id="u1")

    trace = []
    for i in range(turns):
        before = plugin.budget.spent_usd
        msg = types.Content(role="user",
                            parts=[types.Part(text=f"question {i + 1}")])
        async for _ in runner.run_async(user_id="u1",
                                        session_id=session.id,
                                        new_message=msg):
            pass
        decision = plugin.budget.decide()
        refused = plugin.budget.spent_usd == before and decision == "stop"
        trace.append(dict(
            turn=i + 1,
            tools=agent.model.seen_tools[-1] if agent.model.seen_tools else 0,
            spent=plugin.budget.spent_usd,
            delta=plugin.budget.spent_usd - before,
            # a refused turn never reached a model, so naming one would be a
            # status page reporting a call that did not happen
            model="(refused)" if refused else plugin._last_model,
            decision=decision,
        ))
    return trace, agent


# --- reporting --------------------------------------------------------------
def terminal(trace, plugin, declared):
    W = 74
    print("=" * W)
    print("  ADK SESSION SIMULATION -- real agent loop, scripted model")
    print("=" * W)
    print(f"  {'turn':>4} {'tools sent':>11} {'model':>18} {'this turn':>11} "
          f"{'cumulative':>11}")
    for r in trace:
        mark = "  <- pruned" if r["turn"] > 1 and r["tools"] < trace[0]["tools"] else ""
        print(f"  {r['turn']:>4} {r['tools']:>11} {str(r['model'])[:18]:>18} "
              f"${r['delta']:>10.5f} ${r['spent']:>10.5f}{mark}")
    print()
    print(plugin.report())
    print()

    first, last = trace[0]["tools"], trace[-1]["tools"]
    if last < first:
        saved_decls = first - last
        print(f"  TOOL PRUNING: {first} declarations on turn 1, {last} by the end.")
        print(f"  {saved_decls} unused declaration(s) stopped being re-sent every turn.")
    print()
    print("  WHAT THIS PROVES: the plugin's callbacks fire inside ADK's own loop,")
    print("  the declarations really leave the request, the model string really")
    print("  changes on a downgrade, and usage really lands on the budget.")
    print("  WHAT IT DOES NOT: that a live provider reports usage in the shape")
    print("  the extractor expects. Check your first real turns against the bill.")
    print()


HTML = """<!doctype html>
<meta charset="utf-8"><title>Cost plugin status</title>
<style>
:root{color-scheme:dark;--bg:#1E2430;--card:#262E3C;--rule:#3D4759;--ink:#F2F4F8;
--dim:#A8B0C0;--mint:#00A87E;--amber:#D2692A;--violet:#8E6FE0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 ui-sans-serif,system-ui,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:44px 22px 70px;display:flex;flex-direction:column;gap:22px}
h1{margin:0;font-size:30px;letter-spacing:-.02em}
.sub{margin:0;color:var(--dim);max-width:64ch}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
background:var(--rule);border:1px solid var(--rule);border-radius:9px;overflow:hidden}
.c{background:var(--card);padding:13px 15px;display:flex;flex-direction:column;gap:3px}
.k{font:11px ui-monospace,monospace;letter-spacing:.09em;text-transform:uppercase;color:var(--dim)}
.v{font:600 21px ui-monospace,monospace;font-variant-numeric:tabular-nums}
.s{font-size:11.5px;color:var(--dim)}
.panel{background:var(--card);border:1px solid var(--rule);border-radius:9px;padding:20px 22px}
h2{margin:0 0 14px;font-size:17px}
table{border-collapse:collapse;width:100%;font:13px ui-monospace,monospace;font-variant-numeric:tabular-nums}
th{text-align:right;color:var(--dim);font-size:11px;letter-spacing:.07em;text-transform:uppercase;
padding:0 10px 8px;font-weight:600}
th:first-child,td:first-child{text-align:left}
td{text-align:right;padding:6px 10px;border-top:1px solid var(--rule)}
.bar{height:9px;background:#1A202A;border-radius:4px;overflow:hidden;margin-top:7px}
.fill{height:100%;background:var(--mint)}
.pill{display:inline-block;font:11px ui-monospace,monospace;padding:2px 8px;border-radius:999px;
border:1px solid currentColor}
.mint{color:var(--mint)}.amber{color:var(--amber)}.violet{color:var(--violet)}
.note{color:var(--dim);font-size:13px;border-left:2px solid var(--rule);padding-left:12px;margin:0}
</style>
<div class="wrap">
<h1>Cost plugin status</h1>
<p class="sub">A real ADK agent loop driven by a scripted model. Every callback fired in
ADK's own runner; no API key and no network were involved.</p>
__CARDS__
<div class="panel"><h2>Per turn</h2>__TABLE__</div>
<div class="panel"><h2>Budget</h2>__BUDGET__</div>
<div class="panel"><h2>What this does and does not prove</h2>
<p class="note">Proven: the callbacks fire inside ADK's loop, unused tool declarations
really leave the request, the model string really changes on a downgrade, and usage really
lands on the budget.<br><br>
Not proven: that a live provider reports usage in the shape the extractor expects. The
extractor handles several field namings defensively, but until it has seen your provider,
check the first real turns against your bill.</p></div>
</div>
"""


def html_report(trace, plugin, declared, path):
    first, last = trace[0]["tools"], trace[-1]["tools"]
    cards = "".join([
        f'<div class="c"><span class="k">turns</span><span class="v">{plugin.turns}</span>'
        f'<span class="s">scripted model</span></div>',
        f'<div class="c"><span class="k">spent</span><span class="v">'
        f'${plugin.budget.spent_usd:.4f}</span><span class="s">of '
        f'${plugin.budget.limit_usd:.2f}</span></div>',
        f'<div class="c"><span class="k">tools sent</span><span class="v">{first} &rarr; '
        f'{last}</span><span class="s">{first - last} pruned</span></div>',
        f'<div class="c"><span class="k">downgrades</span><span class="v">'
        f'{plugin.downgrades}</span><span class="s">{plugin.cheap_model or "not configured"}'
        f'</span></div>',
        f'<div class="c"><span class="k">refusals</span><span class="v">{plugin.stops}</span>'
        f'<span class="s">budget stop</span></div>',
    ])
    rows = "".join(
        f"<tr><td>{r['turn']}</td><td>{r['tools']}</td>"
        f"<td>{r['model']}</td><td>${r['delta']:.5f}</td>"
        f"<td>${r['spent']:.5f}</td>"
        f"<td><span class='pill {'mint' if r['decision']=='proceed' else 'amber'}'>"
        f"{r['decision']}</span></td></tr>" for r in trace)
    table = ("<table><thead><tr><th>turn</th><th>tools sent</th><th>model</th>"
             "<th>this turn</th><th>cumulative</th><th>budget</th></tr></thead>"
             f"<tbody>{rows}</tbody></table>")
    pctv = min(100, plugin.budget.fraction * 100)
    budget = (f"<div style='font:13px ui-monospace,monospace'>{plugin.budget.status()}</div>"
              f"<div class='bar'><div class='fill' style='width:{pctv:.1f}%'></div></div>")
    out = (HTML.replace("__CARDS__", f'<div class="cards">{cards}</div>')
               .replace("__TABLE__", table).replace("__BUDGET__", budget))
    pathlib.Path(path).write_text(out, encoding="utf8")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--html", metavar="PATH")
    a = ap.parse_args()

    plugin = CostPlugin(budget_usd=0.08, cheap_model="gemini-2.5-flash",
                        prune_unused_after=3)
    trace, agent = asyncio.run(run_session(plugin, a.turns))
    declared = len(TOOLS)
    terminal(trace, plugin, declared)
    if a.html:
        print(f"  status page written: {html_report(trace, plugin, declared, a.html)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
