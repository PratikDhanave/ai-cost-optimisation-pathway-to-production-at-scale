#!/usr/bin/env python3
"""instrument.py - the measurement instrument, runnable.

The thing that decides whether a saving is real. Most cost work is referenced
everywhere and defined nowhere: teams claim percentages with no stated rule for
what counts. This is a rule you can run, and most of its value is in what it
refuses to certify.

Five rules, each one guarding against a specific way a saving gets overstated:

  1. SUCCESSFUL-OUTPUT DENOMINATOR. Cost per solved task, never per request.
     A truncated or failed call costs full price and solves nothing, so a
     "saving" that comes from failing more often is not a saving.
  2. NORMALISATION. Compare unit cost, never total spend. A period where volume
     fell is not a period where you optimised.
  3. COUNTERFACTUAL. Value = (baseline unit cost - current unit cost) x CURRENT
     volume. This is the only number that survives a growing service, and it is
     what year_one.py shows the invoice failing to report in both directions.
  4. INCREMENTAL ATTRIBUTION. When several levers land together, each is
     credited with its MARGINAL contribution against the stack as it stands.
     The credits must sum to the measured total -- that identity is what stops
     four teams claiming the same saving.
  5. QUALITY EXCLUSION. A period whose quality fell below the agreed floor
     claims nothing. Cheapness bought by degrading output is not a saving; it
     is a cost moved somewhere the token bill cannot see.

Layers are reported separately and never summed into one figure. The test is
PROVENANCE: a change in the client's own code is APPLICATION; a commitment or a
negotiated discount is RATE. Caching and batching are application even though
their token counts do not fall, because somebody restructured a prompt or a
schedule to get them. Conflating the two is how a procurement discount gets
reported as engineering work -- and how the largest levers land on the wrong
share of the gain.

    python3 recipes/tools/instrument.py --demo
"""
import argparse, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "recipes"))
from _harness import money, pct
import models as M

# THE TEST IS PROVENANCE, NOT MECHANISM. Application-layer reduction comes from
# a change in the client's own code; rate-layer reduction comes from a
# commitment, provisioned capacity, or a negotiated/aggregated discount.
#
# All four levers below are code changes, so all four are APPLICATION -- including
# caching and batching, whose consumption does not fall. Classifying those two as
# rate is a common mistake with a price tag: if the two layers are shared or
# charged differently, it moves the two largest levers onto the wrong side.
#
# Nothing in this lever set is rate-layer. The committed-use discount in
# recipe 14 is, and the demo below adds it separately so both layers appear.
LAYER = {"trunc": "application", "cache": "application",
         "route": "application", "batch": "application"}
RATE_DISCOUNT = 0.20     # illustrative committed-use rate, NOT a quoted term
COMMIT_COVER  = 0.70     # a commitment covers a committed base, not every token


class Instrument:
    def __init__(self, quality_floor=0.95):
        self.floor = quality_floor
        self.baseline = None

    def set_baseline(self, unit_cost, quality, label="baseline"):
        self.baseline = dict(unit_cost=unit_cost, quality=quality, label=label)

    # --- rule 1 and 2 --------------------------------------------------------
    @staticmethod
    def unit_cost(total_spend, solved):
        """Rule 1: the denominator is SOLVED work, not requests attempted."""
        if solved <= 0:
            raise ValueError("no successful outputs: unit cost is undefined, "
                             "and a period that solved nothing saved nothing")
        return total_spend / solved

    def assess(self, unit_cost, volume, quality, levers_on):
        """Returns the claim for one period, or a refusal with the reason."""
        b = self.baseline
        if quality < self.floor:                              # rule 5
            return dict(claimable=False,
                        reason=f"quality {quality:.3f} is below the agreed floor "
                               f"{self.floor:.3f} -- nothing is claimed for this period",
                        value=0.0)
        if unit_cost >= b["unit_cost"]:
            return dict(claimable=False,
                        reason=f"unit cost {money(unit_cost)} is not below baseline "
                               f"{money(b['unit_cost'])} -- nothing to claim",
                        value=0.0)
        # rule 3: counterfactual at CURRENT volume
        value = (b["unit_cost"] - unit_cost) * volume
        return dict(claimable=True, value=value,
                    unit_reduction=pct(b["unit_cost"], unit_cost),
                    counterfactual=b["unit_cost"] * volume,
                    attribution=self.attribute(levers_on, value))

    # --- rule 4 --------------------------------------------------------------
    @staticmethod
    def attribute(levers_on, certified_value):
        """Credit per lever, summing EXACTLY to the value actually certified.

        Marginal contributions do not naturally sum to the total they jointly
        produce -- each is measured against a different base, so their raw sum
        overstates. The instrument apportions the CERTIFIED value in proportion
        to the marginal figures and reports the scaling factor, so the
        adjustment is visible rather than buried.

        The identity is asserted, not asserted-in-prose: credits must sum to
        the certified value. A tool that printed "sums by construction" without
        checking would be making exactly the kind of unverified claim it exists
        to refuse.
        """
        on = {l: (l in levers_on) for l in M.LEVERS}
        marginal = {}
        for l in levers_on:
            without = dict(on); without[l] = False
            marginal[l] = M.stack_request(**without)[1] - M.stack_request(**on)[1]
        raw = sum(marginal.values()) or 1e-12
        credits = {l: v / raw * certified_value for l, v in marginal.items()}
        assert abs(sum(credits.values()) - certified_value) < 1e-6, \
            "attribution does not reconcile to the certified value"
        # Dimensionless, both measured per request. Mixing a monthly total with
        # a per-request figure here would print a meaningless number.
        #
        # The ratio is normally BELOW 1: marginal contributions UNDERSTATE the
        # joint effect, because each lever's marginal value excludes what the
        # others already captured. That is the mirror image of the solo
        # percentages, which overstate by double counting. Neither sums to the
        # truth, which is why the certified total is apportioned rather than
        # assembled from per-lever measurements.
        joint = M.stack_request()[1] - M.stack_request(**on)[1]
        return dict(credits=credits, marginal=marginal,
                    overstatement=raw / joint if joint else 1.0,
                    by_layer=_by_layer(credits))


def _by_layer(credits):
    out = {"application": 0.0, "rate": 0.0}
    for l, v in credits.items():
        out[LAYER[l]] += v
    return out


def _demo():
    VOL_BASE, VOL_NOW = 150_000 * 30, 420_000 * 30
    W = 78
    print("=" * W)
    print("instrument.py --demo   four teams, one workload, one honest total")
    print("=" * W)

    inst = Instrument(quality_floor=0.95)
    base_unit = M.stack_request()[1] / 0.97          # 3% of attempts solve nothing
    inst.set_baseline(unit_cost=base_unit, quality=0.971)
    print(f"  BASELINE  {money(base_unit)} per SOLVED task "
          f"({money(M.stack_request()[1])} per request at a 97% solve rate)")
    print(f"            volume {VOL_BASE:,}/month, quality 0.971, floor 0.950\n")

    # --- the overclaim ------------------------------------------------------
    print("  WHAT THE FOUR TEAMS REPORTED, each measuring its own lever alone:")
    solo_total, solo_pct = 0.0, 0.0
    for l in M.LEVERS:
        alone = M.stack_request()[1] - M.stack_request(**{l: True})[1]
        solo_total += alone * VOL_NOW
        solo_pct += pct(M.stack_request()[1], M.stack_request(**{l: True})[1])
        print(f"    {l:22} {money(alone * VOL_NOW):>14}/month  "
              f"({pct(M.stack_request()[1], M.stack_request(**{l:True})[1]):.0f}% off)")
    print(f"    {'SUM OF CLAIMS':22} {money(solo_total):>14}/month  ({solo_pct:.0f}% off)\n")

    # --- what actually happened ---------------------------------------------
    on = list(M.LEVERS)
    now_unit = M.stack_request(**{l: True for l in on})[1] / 0.97
    r = inst.assess(unit_cost=now_unit, volume=VOL_NOW, quality=0.968, levers_on=on)

    print("  WHAT THE INSTRUMENT CERTIFIES:")
    print(f"    unit cost        {money(inst.baseline['unit_cost'])} -> {money(now_unit)} "
          f"per solved task  ({r['unit_reduction']:.0f}%)")
    print(f"    counterfactual   {money(r['counterfactual'])}/month at today's volume")
    print(f"    CLAIMABLE        {money(r['value'])}/month")
    print(f"    overclaim        {money(solo_total - r['value'])}/month "
          f"({solo_total/r['value']:.1f}x) was double counted\n")

    a = r["attribution"]
    print("  ATTRIBUTION -- each lever's marginal contribution against the stack as it")
    gap = (a["overstatement"] - 1) * 100
    word = "overstates" if gap > 0 else "understates"
    print("  stands, apportioned to the certified value. The raw marginal sum")
    print(f"  {word} the joint effect by {abs(gap):.0f}%, so it is scaled to reconcile")
    print("  and the factor is shown rather than buried:")
    for l in on:
        print(f"    {l:22} {money(a['credits'][l]):>14}/month  [{LAYER[l]}]")
    print(f"    {'SUM':22} {money(sum(a['credits'].values())):>14}/month  "
          f"= the certified value, asserted\n")
    print("  BOTH NAIVE METHODS ARE WRONG, IN OPPOSITE DIRECTIONS. Measured alone,")
    print(f"  the four levers claim {solo_pct:.0f}% off -- double counting. Measured")
    print(f"  marginally, they sum to {a['overstatement']*100:.0f}% of the joint effect --")
    print("  each one excludes what the others already took. Only the certified")
    print("  total is real; per-lever figures are an apportionment OF it, never an")
    print("  independent measurement that happens to add up.\n")

    # A rate-layer claim on what is LEFT after the application work. It is
    # computed on the residual, never on the original bill -- otherwise the two
    # layers overlap and the same dollar is claimed twice.
    residual = now_unit * VOL_NOW
    rate_value = residual * RATE_DISCOUNT * COMMIT_COVER

    print("  BY LAYER -- reported separately, never summed into one share:")
    print(f"    {'application':22} {money(a['by_layer']['application']):>14}/month   "
          f"[changes in the client's own code]")
    print(f"    {'rate':22} {money(rate_value):>14}/month   "
          f"[a {RATE_DISCOUNT:.0%} commitment over {COMMIT_COVER:.0%} of the residual]")
    print()
    print("    Every lever in the stack above is a CODE change, so every one of them")
    print("    is application-layer -- including caching and batching, whose token")
    print("    counts do not fall. The test is where the saving came from, not")
    print("    whether consumption dropped. Booking those two as rate moves the two")
    print("    largest levers onto the wrong share.")
    print("    The rate claim is computed on the RESIDUAL, after the application work.")
    print("    Taking it against the original bill would claim the same dollar twice.\n")

    # --- the refusals --------------------------------------------------------
    print("  WHAT IT REFUSES:")
    bad = inst.assess(unit_cost=now_unit * 0.6, volume=VOL_NOW, quality=0.912, levers_on=on)
    print(f"    quality 0.912   -> {bad['reason']}")
    flat = inst.assess(unit_cost=base_unit, volume=VOL_NOW, quality=0.97, levers_on=on)
    print(f"    unit cost flat  -> {flat['reason']}")
    try:
        Instrument.unit_cost(5_000.0, 0)
    except ValueError as e:
        print(f"    nothing solved  -> {e}")
    print()
    print("  " + "-" * (W - 4))
    print("  The refusals are the instrument. Anything can produce a number; this")
    print("  declines to produce one when the number would not survive an audit --")
    print("  which is the only reason a client should accept a savings claim that")
    print("  the party being paid for the saving also measured.")
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    if ap.parse_args().demo:
        _demo()
    else:
        print(__doc__)
