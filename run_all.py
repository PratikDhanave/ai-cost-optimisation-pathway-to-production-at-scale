#!/usr/bin/env python3
"""Run every recipe in order and collect the headline results.

    python3 recipes/run_all.py            # full output, recipe by recipe
    python3 recipes/run_all.py --summary  # just the table
    python3 recipes/run_all.py --tools    # the four tools' self-demos
    python3 recipes/run_all.py --check    # gate: every recipe and tool runs

--check is the demo's only automated guard, and it is deliberately narrow: it
proves each recipe executes and emits exactly one parseable RESULT line. It does
NOT check that the arithmetic is right or that a claim is defensible. Nothing
here replaces reading the recipe.
"""
import pathlib, re, subprocess, sys

HERE  = pathlib.Path(__file__).resolve().parent
FILES = sorted(p for p in HERE.glob("[0-9][0-9]_*.py"))
TOOLS = sorted(p for p in (HERE / "tools").glob("*.py") if not p.name.startswith("_"))
RESULT = re.compile(r"RESULT: TOKENS ([-+][\d.]+)%\s+\|\s+COST ([-+][\d.]+)%"
                    r"(?:\s+\|\s+SAVES (\S+)/mo)?")

def run_tools(show):
    """Each tool carries a --demo. Returns a list of failures."""
    bad = []
    for p in TOOLS:
        r = subprocess.run([sys.executable, str(p), "--demo"], capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"tools/{p.name}: exited {r.returncode}\n{r.stderr.strip()[:400]}")
        elif show:
            print(r.stdout)
    return bad


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "--tools":
        bad = run_tools(show=True)
        for x in bad:
            print("FAILED " + x)
        return 1 if bad else 0

    rows, failed = [], []

    for f in FILES:
        r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            failed.append(f"{f.name}: exited {r.returncode}\n{r.stderr.strip()[:400]}")
            continue
        hits = RESULT.findall(r.stdout)
        if len(hits) != 1:
            failed.append(f"{f.name}: expected 1 RESULT line, found {len(hits)}")
            continue
        tok, cost, saves = hits[0]
        title = next((l for l in r.stdout.splitlines() if l.startswith("RECIPE")), f.name)
        rows.append((title.split("  ", 1)[-1].strip(), float(tok), float(cost), saves or "--"))
        if mode not in ("--summary", "--check"):
            print(r.stdout)

    failed += run_tools(show=mode not in ("--summary", "--check"))

    if failed:
        print("FAILED")
        for x in failed:
            print("  " + x)
        return 1

    W = 78
    print("=" * W)
    print("SUMMARY -- tokens first, cost second, for all " + str(len(rows)) + " recipes")
    print("=" * W)
    print(f"  {'recipe':34} {'tokens':>9} {'cost':>9} {'illustrative saving':>21}")
    for title, tok, cost, saves in rows:
        print(f"  {title[:34]:34} {tok:>8.1f}% {cost:>8.1f}% {saves:>21}")
    print()
    zero = sum(1 for _, tok, _, _ in rows if abs(tok) < 0.05)
    print(f"  {zero} recipes cut ~0% of tokens. That is not a bug: caching, batch, routing,")
    print("  committed-use rates and self-hosting change what a token COSTS, not the count.")
    print("  The monthly figures use different volumes per recipe and DO NOT ADD UP --")
    print("  recipe 11 is the only one that composes levers against a single base.")
    print()
    print(f"  TOOLS: {', '.join('tools/' + p.name for p in TOOLS)}")
    print("  Each carries a --demo; cost_gate and prefix_lint are meant for CI.")
    print()
    if mode == "--check":
        print(f"  CHECK PASSED: {len(rows)} recipes reported, {len(TOOLS)} tool demos ran.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
