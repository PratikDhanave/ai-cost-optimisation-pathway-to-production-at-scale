# LLM cost recipes

21 runnable Python recipes for reducing LLM API spend, and 6 tools that
go with them. Each one prints **tokens reduced first, cost reduced second**, in that
order, every time.

```bash
python3 run_all.py              # every recipe, full output
python3 run_all.py --summary    # the summary table
python3 05_cache_breakeven.py   # or run any one on its own
```

No install, no API key, no network. Python 3 standard library only. `tiktoken` is used
if it happens to be importable; otherwise a vendored estimator runs and the banner says
which.

## Why tokens first

Tokens are what an engineer changes. Dollars are tokens multiplied by someone else's
price list. A recipe that opens with a dollar figure has hidden the mechanism behind a
rate it does not control.

**Several of these reduce no tokens at all.** Caching, the batch tier, model routing and
committed-use rates change what a token *costs*. Their token column prints `0%` honestly
rather than borrowing the cost saving into it, because conflating the two is how a team
ends up counting the same prefix twice.

## What is measured and what is assumed

- **Measured when you run it.** Every token count and every percentage. The prompts are
  in the files; change one and the result changes.
- **Published provider mechanics.** Cache read/write multipliers, the 1,024-token
  minimum, the batch discount, the long-context step, the 5x output premium. These live
  in `prices.py` and drive every result.
- **Illustrative rates.** `$3/$15` per 1M for the big model, `$0.80/$4.00` for the small
  one. **Not a quote.** Confirm against live pricing before putting a dollar figure in
  front of anyone.
- **Stated assumptions.** Volumes, growth rates, quality penalties and truncation shares
  are assumptions, labelled as such in the file that uses them.

Monthly figures use a **different volume per recipe** and **do not add up**. Recipe 11 is
the only one that composes levers against a single base.

## Rules these files keep

- **No savings percentage is quoted as achievable.** Recipe 11 computes 94% off from its
  own inputs and then says, in the file, not to repeat it.
- **Every lever names what it costs you.** Pruned examples cost accuracy, windowed
  history costs recall, routing costs escalations, batch costs latency, semantic caching
  costs correctness.
- **Caching arithmetic is vendor-specific.** Some providers bill a cache write at a
  premium; at least one bills it at standard price and charges storage instead.
- **Cost per *completed task*** is the denominator throughout, never cost per request.
  It is the only one under which `max_tokens` ranks correctly as a non-lever.
- **Two recipes report no saving at all** and are among the most useful in the set.

## Tools

| | |
|---|---|
| `tools/meter.py` | per-feature token and cost metering, with cost per *solved* call |
| `tools/cost_gate.py` | CI gate that fails a build when prompt tokens grow past a tolerance |
| `tools/prefix_lint.py` | finds the interpolation that silently broke your cache prefix |
| `tools/gateway.py` | response cache, budget, model downgrade and hard stop at the proxy |
| `tools/instrument.py` | decides whether a saving is real, and refuses to certify when it is not |
| `tools/bill_estimate.py` | ranks the levers by reach x discount against a CSV of your own usage |

Each carries a `--demo`.

## Licence

No licence has been chosen yet, so default copyright applies: all rights reserved.
Add a LICENSE file before sharing this outside the people who already have access.
