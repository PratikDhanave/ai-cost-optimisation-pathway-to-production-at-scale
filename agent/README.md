# Cost control for ADK agents

Model-agnostic cost control as ADK callbacks: **metering, tool pruning and budget
enforcement**. The recipes in the parent directory explain these mechanisms; this is them
running against real traffic.

**This folder is opt-in and is the only thing here with a dependency.** The recipes stay
Python 3.9+ and standard library only, and their CI job installs nothing. This needs
`google-adk` and Python 3.11+.

```bash
pip install -r requirements.txt
python3 example_agent.py        # shows the wiring; needs a model key to actually run
python3 test_cost.py            # 20 tests, no dependencies at all
python3 test_adk.py             # 10 more, needs google-adk, no key
```

## What it does

```python
from cost_plugin import CostPlugin

plugin = CostPlugin(
    budget_usd=5.00,                   # 0 disables the budget entirely
    cheap_model="gemini-2.5-flash",    # None means a downgrade cannot happen
    prune_unused_after=5,              # 0 disables pruning
)
agent = LlmAgent(name="assistant", model="gemini-2.5-pro", tools=[...])
plugin.install(agent)
...
print(plugin.report())
```

**Every mechanism is off unless you configure it.** A cost tool whose defaults silently
change an agent's behaviour is not one you can safely add to somebody else's stack.

| Callback | What happens | Recipe |
|---|---|---|
| `before_model_callback` | drop declarations for tools gone unused; check the budget and downgrade or refuse | 19, 13 |
| `after_model_callback` | read usage and meter it, cache-aware | 01, 05 |
| `before_tool_callback` | record that a tool was actually called — the data pruning needs | 19 |

`install()` chains onto callbacks you already had rather than replacing them.

## What "model-agnostic" actually required

Not hardcoding rates is the easy half. The half that matters:

**Cache mechanics differ between providers in ways that change the arithmetic, not just the
rate.** Several bill a cache write at a premium over the standard input rate, so there is a
break-even to clear. At least one bills the write at the standard rate and charges
**time-based storage** instead — which removes the break-even entirely and introduces a cost
for a cache nobody reads. A single "generic" cache multiplier would be wrong for somebody no
matter which number you picked.

So `cost_core.py` keeps a provider registry with the mechanics, matched by pattern against
whatever model string the agent was given. **An unrecognised model is not priced at a
default** — it is reported as uncosted, and those turns are counted separately instead of
being added to the budget as zero:

```
  budget       $2.4100 of $5.00 (48%) -> proceed; 3 turn(s) not costed and NOT counted
  model        some-local-llama (UNRECOGNISED - turns not costed)
```

Guessing a rate produces a confident number that is wrong, which is worse than no number.

**`None` and `0` cached tokens are not the same thing.** Zero means the provider said nothing
was cached; `None` means it did not say. Collapsing them overstates the uncached share and
makes caching look like it did nothing — so an absent field is reported as an **upper bound**
rather than silently treated as zero.

## What each mechanism costs you

- **Tool pruning**: a pruned tool cannot be called, so a task needing it late will fail.
  Prune conservatively and read the log — every removal is announced.
- **Budget downgrade**: every request is still served, at lower quality for the rest of the
  window.
- **Budget stop**: protects the budget absolutely and refuses real users. Right for a
  backfill, wrong for a checkout flow.

The two budget responses are different promises, which is why they are configured separately.

## What is tested, and what is not

| | |
|---|---|
| `test_cost.py` — **20 tests, no dependencies** | rate resolution, refusal to price unknown models, cache-aware pricing, the `None`/`0` distinction, per-provider cache mechanics, usage extraction across differing SDK field names, pruning thresholds, budget thresholds, uncosted turns |
| `test_adk.py` — **10 tests, needs `google-adk`, no key** | declarations actually removed from a real `LlmRequest`, the model string actually rewritten on downgrade, stop returning an `LlmResponse` instead of calling the model, usage landing on the budget, `install()` preserving existing callbacks |

**Not tested: a live model turn.** Everything above runs against real ADK objects with no API
key, which covers every decision this plugin makes. What it does not cover is a real request
reaching a real provider and the usage coming back in that provider's actual shape. The
extractor is written defensively for several field namings, but until it has seen your
provider's response, treat the metering as unverified for that provider and check the first
few turns against your bill.
