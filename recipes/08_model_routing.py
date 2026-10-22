#!/usr/bin/env python3
"""RECIPE 08 - Route by difficulty, and pay twice when you are wrong.

Most traffic does not need the frontier model. The naive version of this lever
("send everything to the small one") is a quality decision disguised as a cost
decision. The honest version is a cascade: try small, detect low confidence,
escalate -- and the escalated requests cost BOTH models, which is the term every
routing estimate leaves out.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, scaled
import prices as P

banner(8, "Route by difficulty, with a cascade", "price lever - with an escalation cost")

IN_TOK, OUT_TOK = 1_800, 400
VOL = scaled(200_000)

big   = P.cost(IN_TOK, OUT_TOK, "big")
small = P.cost(IN_TOK, OUT_TOK, "small")

tokens([("big model",   IN_TOK, OUT_TOK),
        ("small model", IN_TOK, OUT_TOK)])
note("Identical tokens. Routing is a price lever -- the third in this set, "
     "after caching and batch.")

def cascade(escalation_rate):
    """Every request pays small; the escalated share pays big ON TOP."""
    return small + escalation_rate * big

rows = [("all big",              big),
        ("all small (no escalation)", small),
        ("cascade,  8% escalate", cascade(0.08)),
        ("cascade, 25% escalate", cascade(0.25)),
        ("cascade, 60% escalate", cascade(0.60))]
costs(rows, volume_per_day=VOL)

breakeven = (big - small) / big
note(f"""
THE TERM PEOPLE FORGET: the cascade stops saving money at an escalation rate of
{breakeven*100:.0f}%. Above that, routing costs MORE than sending everything to
the big model, because every escalated request has paid for two inferences.
Measure your real escalation rate before you promise a routing saving.
""")

chosen = cascade(0.08)
saving = (big - chosen) * VOL * 30

verdict(f"""
A cascade at a realistic 8% escalation rate: {(1-chosen/big)*100:.0f}% off, which
is {money(saving)}/month at {VOL:,} requests/day -- and it needs no prompt change.

WHAT MAKES IT WORK OR NOT. The router. A cheap, reliable difficulty signal is
the whole lever: self-reported confidence below a threshold, a schema validation
failure, a refusal, an output length outside the expected band. Classifying
difficulty with another model call is usually self-defeating -- you have added
an inference to save one.

THE DENOMINATOR, AGAIN: cost per CORRECT answer, not cost per request. A small
model that is 4x cheaper and wrong 6% more often may be more expensive once the
re-work, the escalations and the customer-visible errors are counted, and none of
those appear on the token bill. Build the eval set first (recipe 04), then set
the threshold from it.
""")
headline(0.0, -(1 - chosen / big) * 100, saving)
