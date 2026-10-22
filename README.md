# LLM cost recipes

21 runnable Python recipes for reducing LLM API spend, and 6 tools that go with
them. Each prints **tokens reduced first, cost reduced second**, in that order, every
time.

**Python 3.9+. No dependencies, no install, no API key, no network.** Standard library
only -- `tiktoken` is used if it happens to be importable, otherwise a vendored
estimator runs and the banner says which.

```bash
python3 run_all.py                        # every recipe, full output
python3 run_all.py --summary              # the table below
python3 run_all.py --check                # CI gate: every recipe runs and reports
python3 recipes/05_cache_breakeven.py     # or run any one on its own
python3 tools/meter.py --demo             # each tool carries a --demo
```

## What it prints

```
==============================================================================
SUMMARY -- tokens first, cost second, for all 21 recipes
==============================================================================
  recipe                                tokens      cost   illustrative saving
  Tokens are the unit                     0.0%      0.0%                    --
  Put the system prompt on a diet       -61.9%    -34.0%             $4,401.00
  Shape the output, not just the inp    -23.3%    -52.5%             $7,222.50
  Prune the few-shot examples           -52.4%    -43.9%             $3,199.50
  Prompt caching and its break-even       0.0%    -37.7%            $25,434.00
  Window the conversation history       -39.6%    -35.2%            $45,864.00
  Move async work to the batch tier       0.0%    -41.1%           $161,460.00
  Route by difficulty, with a cascad      0.0%    -65.3%            $44,688.00
  Give retrieval a token budget         -81.8%    -72.5%            $48,438.00
  Agent loops, and the max_tokens tr    -46.8%    -38.2%            $13,459.50
  Compose the levers; stop adding pe    -68.1%    -94.3%           $194,706.00
  Self-hosting break-even                 0.0%      0.0%                    --
  Budgets, quotas and circuit breake     -0.0%    -61.6%            $35,343.00
  Committed use and forecasting           0.0%    -60.0%            $38,880.00
  Reasoning tokens and the effort di    -94.2%    -97.9%           $504,000.00
  The long-context price cliff            0.0%     -9.1%            $17,766.00
  Semantic caching and the wrong-ans    -18.0%    -18.0%             $6,557.18
  Prompt compression and who pays th    -64.5%     -0.3%               $208.80
  Tool schemas and the per-call tax     -85.5%    -80.7%           $130,680.00
  Retries, timeouts and abandoned st      0.0%     -6.8%             $5,657.71
  Cost per user and the unprofitable      0.0%    -46.9%            $67,767.00

  10 recipes cut ~0% of tokens. That is not a bug: caching, batch, routing,
  committed-use rates and self-hosting change what a token COSTS, not the count.
  The monthly figures use different volumes per recipe and DO NOT ADD UP --
  recipe 11 is the only one that composes levers against a single base.

  TOOLS: tools/bill_estimate.py, tools/cost_gate.py, tools/gateway.py, tools/instrument.py, tools/meter.py, tools/prefix_lint.py
  Each carries a --demo; cost_gate and prefix_lint are meant for CI.
```

## Why tokens first

Tokens are what an engineer changes. Dollars are tokens multiplied by someone else's
price list. A recipe that opens with a dollar figure has hidden the mechanism behind a
rate it does not control.

**Several of these reduce no tokens at all.** Caching, the batch tier, routing,
committed-use rates and the context cliff change what a token *costs*. Their token
column prints `0%` honestly rather than borrowing the cost saving into it, because
conflating the two is how a team counts the same prefix twice.

## The recipes

| # | |
|---|---|
| [01](recipes/01_the_unit.py) | Tokens are the unit, and the average is a lie. |
| [02](recipes/02_prompt_diet.py) | Put the system prompt on a diet. |
| [03](recipes/03_output_shape.py) | Shape the output, not just the input. |
| [04](recipes/04_few_shot_pruning.py) | Prune the few-shot examples. |
| [05](recipes/05_cache_breakeven.py) | Prompt caching, and the three ways it pays nothing. |
| [06](recipes/06_history_window.py) | Conversation history grows quadratically. Window it. |
| [07](recipes/07_batch_async.py) | Move what nobody is waiting for to the batch tier. |
| [08](recipes/08_model_routing.py) | Route by difficulty, and pay twice when you are wrong. |
| [09](recipes/09_rag_context_budget.py) | Give retrieval a token budget. |
| [10](recipes/10_agent_loops.py) | Agent loops multiply everything, and max_tokens is not a lever. |
| [11](recipes/11_the_stack.py) | Compose the levers, and stop adding their percentages up. |
| [12](recipes/12_selfhost_breakeven.py) | Self-hosting: the break-even moves when you optimise first. |
| [13](recipes/13_governance_budgets.py) | Governance: every optimisation gain gets eaten by growth. |
| [14](recipes/14_commit_and_forecast.py) | Optimisation reduces volume; negotiation reduces rate. |
| [15](recipes/15_reasoning_budget.py) | Reasoning tokens: billed as output, and you never see them. |
| [16](recipes/16_context_cliff.py) | The long-context price cliff: one token, double the bill. |
| [17](recipes/17_semantic_cache.py) | Semantic caching: 100% off, and the only lever that can be wrong. |
| [18](recipes/18_prompt_compression.py) | Automated prompt compression, and the call that does the work. |
| [19](recipes/19_tool_schemas.py) | Tool schemas: the tax you pay on every call, used or not. |
| [20](recipes/20_waste_paths.py) | Retries, timeouts and abandoned streams: paying for nothing. |
| [21](recipes/21_unit_economics.py) | Cost per user, and the ones who cost more than they pay. |

## The tools

| | |
|---|---|
| [`meter.py`](tools/meter.py) | per-feature token and cost metering, reporting cost per *solved* call |
| [`cost_gate.py`](tools/cost_gate.py) | CI gate that fails a build when prompt tokens grow past a tolerance |
| [`prefix_lint.py`](tools/prefix_lint.py) | finds the interpolation that silently broke your cache prefix |
| [`gateway.py`](tools/gateway.py) | response cache, budget, model downgrade and hard stop at the proxy |
| [`instrument.py`](tools/instrument.py) | decides whether a saving is real, and refuses to certify when it is not |
| [`bill_estimate.py`](tools/bill_estimate.py) | ranks the levers by reach x discount against a CSV of your own usage |

## What is measured and what is assumed

- **Measured when you run it.** Every token count and every percentage. The prompts are
  in the files; change one and the result changes.
- **Published provider mechanics.** Cache read/write multipliers, the 1,024-token
  minimum, the batch discount, the long-context step, the 5x output premium. These live
  in `recipes/prices.py` and drive every result.
- **Illustrative rates.** `$3/$15` per 1M for the big model, `$0.80/$4.00` for the small
  one. **Not a quote.** Confirm against live pricing before quoting a dollar figure.
- **Stated assumptions.** Volumes, growth rates, quality penalties and truncation shares
  are assumptions, labelled in the file that uses them.

Monthly figures use a **different volume per recipe** and **do not add up**. Recipe 11 is
the only one that composes levers against a single base.

## Rules these files keep

- **No savings percentage is quoted as achievable.** Recipe 11 computes 94% off from its
  own inputs and then says, in the file, not to repeat it.
- **Every lever names what it costs you** -- accuracy, recall, escalations, latency,
  correctness.
- **Caching arithmetic is vendor-specific.** Some providers bill a cache write at a
  premium; at least one bills it at standard price and charges storage instead.
- **Cost per *completed task*** is the denominator throughout, never cost per request.
- **Two recipes report no saving at all** and are among the most useful in the set.

## Licence

Copyright (c) 2026 ClearRoute. All rights reserved. Proprietary; no licence is
granted. See [LICENSE](LICENSE).
