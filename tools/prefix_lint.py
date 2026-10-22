#!/usr/bin/env python3
"""prefix_lint.py - find the interpolation that silently broke your cache.

Prompt caching matches on an EXACT prefix. One variable substituted near the top
of a template -- a user id, a timestamp, today's date -- changes the first bytes
of every request, so nothing after it can ever match. The cache does not error.
It reports a hit rate near zero while you keep paying the write premium, which
recipe 05 shows is strictly worse than not caching at all.

This linter reads a template, finds where the first per-request variable lands,
and reports how many tokens of stable content are stranded behind it.

    python3 recipes/tools/prefix_lint.py prompts/
    python3 recipes/tools/prefix_lint.py --demo

Placeholder syntaxes understood: {name}, {{name}}, %(name)s, $name, ${name},
<name>. A variable whose name suggests it changes per request (id, user, time,
date, query, session, uuid, random, ...) is treated as cache-breaking; anything
else is reported as probably-stable so you can confirm it yourself. THE LINTER
GUESSES FROM NAMES -- it cannot know your data, so treat its verdict as a
prompt to go and look, not a proof.
"""
import argparse, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _harness import count, money
import prices as P

PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}|\{\s*(\w+)\s*\}|%\((\w+)\)s"
                         r"|\$\{\s*(\w+)\s*\}|\$(\w+)|<(\w+)>")

# names that almost always vary per request
VOLATILE = re.compile(r"user|id\b|_id|uuid|session|time|date|now|today|timestamp"
                      r"|query|question|input|message|ticket|order|request|random"
                      r"|nonce|turn|history", re.I)

SUFFIXES = {".txt", ".md", ".prompt", ".tmpl", ".j2"}


def placeholders(text):
    for m in PLACEHOLDER.finditer(text):
        name = next(g for g in m.groups() if g)
        yield m.start(), name, bool(VOLATILE.search(name))


def lint(path, text, rpd, out=print):
    found = list(placeholders(text))
    total = count(text)
    first_volatile = next(((i, n) for i, n, v in found if v), None)

    out(f"  {path}")
    if not found:
        out(f"    no placeholders. whole template is a stable prefix: {total:,} tokens")
        out(f"    {'CACHEABLE' if total >= P.CACHE_MIN else 'too short to cache'}"
            f" (minimum {P.CACHE_MIN:,})")
        out("")
        return 0.0

    if first_volatile is None:
        out(f"    {len(found)} placeholder(s), none obviously per-request: "
            + ", ".join(sorted({n for _, n, _ in found})))
        out(f"    stable prefix could be the whole {total:,} tokens -- CONFIRM by hand")
        out("")
        return 0.0

    idx, name = first_volatile
    line = text[:idx].count("\n") + 1
    prefix_tok = count(text[:idx])
    stranded = total - prefix_tok

    out(f"    line {line}: {{{name}}} is the first per-request variable")
    out(f"    cacheable prefix before it   {prefix_tok:>7,} tokens")
    out(f"    stable content stranded after{stranded:>7,} tokens")

    # A reorder only recovers money if the REORDERED prefix would clear the
    # minimum. Pricing the fix without checking that is how a linter invents a
    # saving its own advice cannot deliver.
    if total < P.CACHE_MIN:
        out(f"    VERDICT: TOO SHORT TO CACHE, before and after any reorder.")
        out(f"             The whole template is {total:,} tokens against a "
            f"{P.CACHE_MIN:,}-token minimum.")
        out( "             Moving the variable changes NOTHING. If you want this cached,")
        out( "             the stable block has to get bigger, not get reordered -- or")
        out( "             accept that this prompt is not a caching candidate.")
        out("")
        return 0.0

    if prefix_tok < P.CACHE_MIN:
        out(f"    VERDICT: BROKEN. The prefix is under the {P.CACHE_MIN:,}-token minimum,")
        out( "             so NOTHING caches and every request pays the write premium --")
        out( "             strictly worse than leaving caching switched off.")
    elif stranded <= max(100, total * 0.05):
        out(f"    VERDICT: HEALTHY. {prefix_tok:,} tokens cache; only {stranded:,} sit")
        out( "             after the first variable, which is where they belong.")
        out("")
        return 0.0
    else:
        out(f"    VERDICT: partial. {prefix_tok:,} tokens cache; {stranded:,} do not.")

    recoverable = stranded
    gain = recoverable / 1e6 * P.MODELS["big"][0] * (1 - P.CACHE_READ)
    out(f"    FIX: move {{{name}}} (and everything else per-request) BELOW the stable")
    out( "         block. Order: system rules, examples, retrieved context, THEN the")
    out( "         variables. Worth "
        f"{money(gain)}/request, {money(gain * rpd * 30)}/month at {rpd:,} req/day.")
    out("")
    return gain * rpd * 30


def _demo():
    SHORT = """Current date: {today}. Session: {session_id}.
You are a support assistant for an online retailer.

Rules:
- Be professional and concise.
- Never invent order numbers, tracking numbers, dates or amounts.
- If you cannot help, offer escalation to a human agent.

Now classify this ticket: {ticket_text}
"""

    # A realistic production prompt: rules, a policy block, and enough worked
    # examples to clear the minimum. This is the case where a reorder pays.
    rules = ("- Be professional and concise.\n"
             "- Never invent order numbers, tracking numbers, dates or amounts.\n"
             "- If you cannot help, offer escalation to a human agent.\n"
             "- Always return the confidence score so the router can threshold.\n")
    examples = "".join(
        f'Ticket: "{q}" -> {{"category":"{c}","confidence":0.9{i%10}}}\n'
        for i, (q, c) in enumerate([
            ("I was charged twice for March.", "billing"),
            ("The app crashes when I open settings.", "technical"),
            ("How do I change my delivery address?", "account"),
            ("My refund has not arrived after ten days.", "billing"),
            ("Is the blue version back in stock?", "product"),
            ("I cannot log in since the update.", "technical"),
            ("Cancel my subscription please.", "account"),
            ("Do these shoes run small?", "product"),
        ] * 6))
    policy = ("Escalation policy: billing to the finance queue, technical to tier-two\n"
              "support, account changes to the service desk, product questions to\n"
              "merchandising. Below 0.7 confidence, route to human triage instead.\n")

    LONG_BROKEN = (f"Current date: {{today}}. Session: {{session_id}}. User: {{user_id}}.\n"
                   f"You are a support assistant for an online retailer.\n\nRules:\n{rules}\n"
                   f"Worked examples:\n{examples}\n{policy}\n"
                   f"Now classify this ticket: {{ticket_text}}\n")
    LONG_FIXED  = (f"You are a support assistant for an online retailer.\n\nRules:\n{rules}\n"
                   f"Worked examples:\n{examples}\n{policy}\n"
                   f"Context: {{today}} / {{session_id}} / {{user_id}}\n"
                   f"Now classify this ticket: {{ticket_text}}\n")

    print("=" * 78)
    print("prefix_lint.py --demo   two templates, and only one of them is fixable")
    print("=" * 78)
    print("  CASE 1 -- a short prompt with the date on line 1\n")
    lint("prompts/short.txt", SHORT, 150_000)
    print("  The linter refuses to price a reorder here, and that is the point: the")
    print("  whole template is below the minimum, so moving the variable recovers")
    print("  nothing. A tool that quoted a saving here would be inventing one.\n")

    print("  CASE 2 -- a real production prompt, same mistake on line 1\n")
    a = lint("prompts/classify.txt", LONG_BROKEN, 150_000)
    print("  CASE 2, reordered -- identical content, variables moved to the bottom\n")
    b = lint("prompts/classify.txt", LONG_FIXED, 150_000)

    print(f"  Same instructions, same examples, same tokens sent. Three variables moved")
    print(f"  off line 1, and the difference is {money(a - b)}/month at 150,000 req/day.")
    print("")
    print("  This failure is invisible in every dashboard: no error, no latency change,")
    print("  just a hit rate near zero and a write premium on every call. Lint the")
    print("  templates in CI, next to cost_gate.")
    print("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--requests-per-day", type=int, default=150_000)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        _demo()
        return 0
    if not a.path:
        ap.error("path is required (or use --demo)")
    root = pathlib.Path(a.path)
    files = ([root] if root.is_file()
             else sorted(p for p in root.rglob("*") if p.suffix in SUFFIXES))
    if not files:
        print("no templates found")
        return 0
    total = sum(lint(str(p), p.read_text(), a.requests_per_day) for p in files)
    print(f"  TOTAL RECOVERABLE: {money(total)}/month at {a.requests_per_day:,} req/day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
