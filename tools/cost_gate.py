#!/usr/bin/env python3
"""cost_gate.py - fail the build when a prompt change makes it more expensive.

Prompt bloat arrives the way all bloat arrives: one reasonable paragraph at a
time, each too small to argue about, none of them reviewed as a cost change.
Code has had regression gates for thirty years. Prompts have had none, and they
are the part of the system that is billed per word.

This is that gate. It counts the tokens in every prompt template, compares
against a committed baseline, and exits non-zero when the increase crosses a
threshold. Wire it into CI next to the tests.

    python3 recipes/tools/cost_gate.py --baseline prompts/baseline.json prompts/
    python3 recipes/tools/cost_gate.py --update   prompts/baseline.json prompts/
    python3 recipes/tools/cost_gate.py --demo

WHAT IT CANNOT DO, and the limit matters: a gate on tokens is not a gate on
cost. Moving a prompt to a cheaper model, or caching its prefix, lowers the bill
while this gate sees nothing. It catches the one failure mode it is built for --
prompts growing unnoticed between reviews -- and recipe 13 is there because
growth happens in volume too, where no gate on templates can see it.

WHY A THRESHOLD AND NOT ZERO: a gate that fires on every edit gets disabled in a
week. The default allows a 3% drift and fails on a step change, which is the
shape of the failure actually worth blocking.
"""
import argparse, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "recipes"))
from _harness import count, COUNTER
import prices as P

SUFFIXES = {".txt", ".md", ".prompt", ".tmpl", ".j2"}


def scan(root):
    root = pathlib.Path(root)
    files = ([root] if root.is_file()
             else sorted(p for p in root.rglob("*") if p.suffix in SUFFIXES))
    return {str(p.relative_to(root if root.is_dir() else root.parent)): count(p.read_text())
            for p in files}


def check(current, baseline, tol_pct, rpd, out=print):
    """Returns (ok, failures). Prints a per-template table."""
    names = sorted(set(current) | set(baseline))
    failures, total_b, total_c = [], 0, 0
    out(f"  {'template':34} {'baseline':>9} {'now':>9} {'change':>9}  verdict")
    for n in names:
        b, c = baseline.get(n), current.get(n)
        if b is None:
            out(f"  {n:34} {'-':>9} {c:>9,} {'new':>9}  NEW (add to baseline)")
            total_c += c
            continue
        if c is None:
            out(f"  {n:34} {b:>9,} {'-':>9} {'gone':>9}  REMOVED")
            total_b += b
            continue
        total_b, total_c = total_b + b, total_c + c
        delta = (c / b - 1) * 100 if b else 0.0
        if delta > tol_pct:
            failures.append((n, b, c, delta))
            verdict = f"FAIL (> {tol_pct:g}%)"
        elif delta < -tol_pct:
            verdict = "improved"
        else:
            verdict = "ok"
        out(f"  {n:34} {b:>9,} {c:>9,} {delta:>+8.1f}%  {verdict}")

    out("")
    if total_b:
        drift = (total_c / total_b - 1) * 100
        # cost framing: what the drift is worth at a stated request volume
        per_req_delta = (total_c - total_b) / 1e6 * P.MODELS["big"][0]
        out(f"  TOKENS  {total_b:,} -> {total_c:,}  ({drift:+.1f}%)")
        out(f"  COST    {per_req_delta * rpd * 30:+,.2f} USD/month at {rpd:,} requests/day, "
            f"input rate ${P.MODELS['big'][0]:.2f}/1M")
    return not failures, failures


def _demo():
    import tempfile, textwrap
    print("=" * 78)
    print("cost_gate.py --demo   a passing edit, then the one that should block a PR")
    print("=" * 78)
    print(f"  counter: {COUNTER}\n")

    tidy = "Classify the ticket. Reply with JSON: category, confidence.\n"
    helpful_addition = textwrap.dedent("""\
        Classify the ticket. Reply with JSON: category, confidence.

        Please be very careful and thorough in your analysis. Consider the full
        context of the customer's message, including their tone, any previous
        interactions they may have referenced, the specific products mentioned,
        and whether the issue appears to be urgent. Think step by step about
        which category fits best before you answer. It is very important to be
        accurate. If you are uncertain between two categories, choose the one
        that would route the ticket to the team best able to resolve it, and
        lower your confidence score accordingly to reflect that uncertainty.
        """)

    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d)
        (p / "classify.txt").write_text(tidy)
        (p / "summarise.txt").write_text("Summarise in three bullets. No preamble.\n")
        baseline = scan(p)
        print("  baseline committed:", json.dumps(baseline), "\n")

        print("  PR 1 -- tighten the wording")
        (p / "summarise.txt").write_text("Summarise in three bullets.\n")
        ok, _ = check(scan(p), baseline, 3.0, 150_000)
        print(f"  -> exit {0 if ok else 1}   {'PASS' if ok else 'BLOCKED'}\n")

        print('  PR 2 -- "just adding a bit of guidance to improve accuracy"')
        (p / "classify.txt").write_text(helpful_addition)
        ok, failures = check(scan(p), baseline, 3.0, 150_000)
        print(f"  -> exit {0 if ok else 1}   {'PASS' if ok else 'BLOCKED'}")
        for n, b, c, d_ in failures:
            print(f"     {n}: {b:,} -> {c:,} tokens ({d_:+.0f}%) on every request, forever")
    print("")
    print("  Nothing in PR 2 is wrong. It is a reasonable instruction, written in")
    print("  good faith, and it would pass any code review that was not counting.")
    print("  That is exactly why the counting has to be automatic.")
    print("")


def main():
    ap = argparse.ArgumentParser(description="Fail the build on prompt token regressions.")
    ap.add_argument("path", nargs="?", help="prompt file or directory")
    ap.add_argument("--baseline", help="committed baseline JSON to compare against")
    ap.add_argument("--update", metavar="JSON", help="write a fresh baseline and exit")
    ap.add_argument("--tolerance", type=float, default=3.0, help="allowed %% drift (default 3)")
    ap.add_argument("--requests-per-day", type=int, default=150_000,
                    help="volume used only to price the drift (default 150000)")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()

    if a.demo:
        _demo()
        return 0
    if not a.path:
        ap.error("path is required (or use --demo)")
    current = scan(a.path)
    if a.update:
        pathlib.Path(a.update).write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"baseline written: {a.update} ({len(current)} templates)")
        return 0
    if not a.baseline:
        ap.error("--baseline is required (or --update to create one)")
    baseline = json.loads(pathlib.Path(a.baseline).read_text())
    print(f"  counter: {COUNTER}\n")
    ok, _ = check(current, baseline, a.tolerance, a.requests_per_day)
    print("\n  PASSED" if ok else "\n  FAILED -- prompt tokens grew beyond tolerance")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
