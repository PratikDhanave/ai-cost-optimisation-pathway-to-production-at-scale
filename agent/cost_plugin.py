"""Cost control for ADK agents, as callbacks. Thin glue over cost_core.

Every decision this file makes lives in cost_core.py, which has no dependency
on ADK and is tested without it. What is here is only the wiring: where ADK
hands you a request you may mutate, and where it hands you the usage it billed.

    from cost_plugin import CostPlugin

    plugin = CostPlugin(budget_usd=5.00, cheap_model="gemini-2.5-flash")
    agent = LlmAgent(name="assistant", model="gemini-2.5-pro", tools=[...])
    plugin.install(agent)
    ...
    print(plugin.report())

MODEL-AGNOSTIC BY CONSTRUCTION. Nothing here names a provider. The model string
is whatever the agent was given, cost_core decides whether it recognises it,
and an unrecognised model is reported as uncosted rather than priced at a
default. That matters more than it sounds: cache mechanics differ between
providers in ways that change the arithmetic, not just the rate.

THE THREE MECHANISMS, and what each one costs you:

  TOOL PRUNING drops declarations for tools that have gone unused. Tool schemas
  are re-sent on every turn whether called or not, so an unused tool is a fixed
  tax on the whole session. The cost: a pruned tool cannot be called, so a task
  that needed it late will fail. Prune conservatively and log every removal.

  BUDGET DOWNGRADE swaps the model once spend crosses a threshold. Every
  request is still served, at lower quality for the rest of the window.

  BUDGET STOP refuses. It protects the budget absolutely and refuses real
  users, which is right for a backfill and wrong for a checkout flow.

The two budget responses are different promises, so they are configured
separately and neither is on by default.
"""
from __future__ import annotations

import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cost_core import Budget, Cost, ToolTracker, price, read_usage, resolve

log = logging.getLogger("cost_plugin")


def _declaration_names(llm_request) -> list:
    """Every function name currently advertised to the model."""
    names = []
    for tool in (getattr(llm_request.config, "tools", None) or []):
        for d in (getattr(tool, "function_declarations", None) or []):
            if getattr(d, "name", None):
                names.append(d.name)
    return names


def _drop_declarations(llm_request, drop: set) -> list:
    """Remove named declarations in place. Returns what was actually removed."""
    removed = []
    for tool in (getattr(llm_request.config, "tools", None) or []):
        decls = getattr(tool, "function_declarations", None)
        if not decls:
            continue
        keep = []
        for d in decls:
            if getattr(d, "name", None) in drop:
                removed.append(d.name)
            else:
                keep.append(d)
        tool.function_declarations = keep
    return removed


class CostPlugin:
    def __init__(self, *, budget_usd: float = 0.0, cheap_model: str | None = None,
                 prune_unused_after: int = 0, rates: dict | None = None,
                 stop_message: str = "Budget reached for this session."):
        """All three mechanisms are OFF unless configured.

        prune_unused_after=0 disables pruning; budget_usd=0 disables both budget
        responses; cheap_model=None means a downgrade cannot happen even if the
        threshold is crossed. A cost tool whose defaults silently change an
        agent's behaviour is not one you can safely add to someone else's stack.
        """
        self.budget = Budget(limit_usd=budget_usd)
        self.cheap_model = cheap_model
        self.rates = rates
        self.stop_message = stop_message
        self.prune_enabled = prune_unused_after > 0
        self.tracker = ToolTracker(unused_after=prune_unused_after or 10 ** 9)
        self.turns = 0
        self.pruned: list = []
        self.downgrades = 0
        self.stops = 0
        self._last_model: str | None = None

    # --- callbacks ---------------------------------------------------------
    def before_model(self, callback_context=None, llm_request=None):
        """Mutates llm_request. Returning an LlmResponse short-circuits the call."""
        if llm_request is None:
            return None
        self._last_model = getattr(llm_request, "model", None)
        self.tracker.observe_tools(_declaration_names(llm_request))

        if self.prune_enabled:
            drop = set(self.tracker.prunable())
            if drop:
                removed = _drop_declarations(llm_request, drop)
                if removed:
                    self.pruned.extend(removed)
                    log.info("pruned unused tool declarations: %s",
                             ", ".join(sorted(set(removed))))

        decision = self.budget.decide()
        if decision == "stop":
            self.stops += 1
            log.warning("budget stop: %s", self.budget.status())
            return self._refusal()
        if decision == "downgrade" and self.cheap_model:
            if llm_request.model != self.cheap_model:
                self.downgrades += 1
                log.info("budget downgrade: %s -> %s", llm_request.model,
                         self.cheap_model)
                llm_request.model = self.cheap_model
                self._last_model = self.cheap_model
        return None

    def after_model(self, callback_context=None, llm_response=None):
        """Meters what the turn actually billed. Never mutates the response."""
        if llm_response is None:
            return None
        usage = read_usage(getattr(llm_response, "usage_metadata", None))
        model = getattr(llm_response, "model_version", None) or self._last_model
        cost = price(model, usage, rates=self.rates)
        self.budget.add(cost)
        if not cost.known and usage is not None:
            log.debug("turn not costed: %s", cost.reason)
        self.turns += 1
        self.tracker.end_turn()
        return None

    def before_tool(self, tool=None, args=None, tool_context=None, **kw):
        """Records that a tool was actually called -- the data pruning needs."""
        name = getattr(tool, "name", None) or (tool if isinstance(tool, str) else None)
        if name:
            self.tracker.record_call(name)
        return None

    # --- wiring ------------------------------------------------------------
    def install(self, agent) -> None:
        """Attach to an LlmAgent, preserving any callbacks already set."""
        for attr, mine in (("before_model_callback", self.before_model),
                           ("after_model_callback", self.after_model),
                           ("before_tool_callback", self.before_tool)):
            existing = getattr(agent, attr, None)
            setattr(agent, attr, _chain(existing, mine) if existing else mine)

    def _refusal(self):
        from google.adk.models import LlmResponse
        from google.genai import types
        return LlmResponse(content=types.Content(
            role="model", parts=[types.Part(text=self.stop_message)]))

    # --- reporting ---------------------------------------------------------
    def report(self) -> str:
        lines = [
            "cost plugin",
            f"  turns        {self.turns}",
            f"  budget       {self.budget.status()}",
        ]
        if self._last_model is None:
            lines.append("  model        no turns yet")
        else:
            p = resolve(self._last_model)
            lines.append(f"  model        {self._last_model} "
                         f"({p.name if p else 'UNRECOGNISED - turns not costed'})")
        if self.pruned:
            lines.append(f"  pruned       {len(set(self.pruned))} tool "
                         f"declaration(s): {', '.join(sorted(set(self.pruned)))}")
        if self.downgrades:
            lines.append(f"  downgrades   {self.downgrades} turn(s) moved to "
                         f"{self.cheap_model}")
        if self.stops:
            lines.append(f"  refusals     {self.stops} turn(s) refused")
        return "\n".join(lines)


def _chain(first, second):
    """Run an existing callback, then ours; the first non-None result wins."""
    def chained(*a, **kw):
        out = first(*a, **kw)
        if out is not None:
            return out
        return second(*a, **kw)
    return chained
