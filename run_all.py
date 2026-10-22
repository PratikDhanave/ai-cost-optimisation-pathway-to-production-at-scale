#!/usr/bin/env python3
"""Run every recipe in order and collect the headline results.

    python3 recipes/run_all.py            # full output, recipe by recipe
    python3 recipes/run_all.py --summary  # just the table
    python3 recipes/run_all.py --tools    # the four tools' self-demos
    python3 recipes/run_all.py --check    # gate: every recipe and tool runs
    python3 recipes/run_all.py --menu     # pick one from a list

--check is the demo's only automated guard, and it is deliberately narrow: it
proves each recipe executes and emits exactly one parseable RESULT line. It does
NOT check that the arithmetic is right or that a claim is defensible. Nothing
here replaces reading the recipe.
"""
import pathlib, re, subprocess, sys

HERE  = pathlib.Path(__file__).resolve().parent
FILES = sorted(p for p in (HERE / "recipes").glob("[0-9][0-9]_*.py"))
TOOLS = sorted(p for p in (HERE / "tools").glob("*.py") if not p.name.startswith("_"))
SUITES = sorted((HERE / "tests").glob("test_*.py"))
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


def menu():
    """Pick a recipe from a list. For a workshop room, or a first read."""
    items = FILES + TOOLS
    print("=" * 78)
    print("  pick one, or 'a' for the summary of all")
    print("=" * 78)
    for i, p in enumerate(FILES, 1):
        doc = p.read_text().split(chr(34) * 3)[1].splitlines()[0]
        title = doc.split(" - ", 1)[1] if " - " in doc else doc
        print(f"  {i:>2}  {title.rstrip('.')}")
    for j, p in enumerate(TOOLS, len(FILES) + 1):
        print(f"  {j:>2}  tools/{p.name}  (--demo)")
    print()
    try:
        raw = input("  number, or a: ").strip()
    except (EOFError, KeyboardInterrupt):
        print(); return 0
    if raw.lower() == "a":
        return main_with("--summary")
    if not raw.isdigit() or not (1 <= int(raw) <= len(items)):
        print("  not a choice on that list"); return 1
    p = items[int(raw) - 1]
    args = [sys.executable, str(p)] + (["--demo"] if p in TOOLS else [])
    print()
    return subprocess.run(args).returncode


def main_with(mode):
    sys.argv = [sys.argv[0], mode]
    return main()


def run_suites():
    """The unit tests. --check runs them; they are the only thing here that
    checks the ARITHMETIC rather than that a recipe merely executed."""
    bad = []
    for p in SUITES:
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"{p.name}: {r.stderr.strip().splitlines()[-1][:160]}")
    return bad


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--menu":
        return menu()

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
    failed += run_suites()

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
        n = sum(1 for p in SUITES
                for line in [p.read_text()] for _ in [0]) and sum(
            p.read_text().count("def test_") for p in SUITES)
        print(f"  CHECK PASSED: {len(rows)} recipes reported, {len(TOOLS)} tool "
              f"demos ran, {len(SUITES)} suites / {n} assertions passed.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
