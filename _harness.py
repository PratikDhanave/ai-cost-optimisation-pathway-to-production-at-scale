"""Token counting and the one output format every recipe uses.

THE FORMAT IS THE POINT: tokens first, cost second. A recipe that opens with a
dollar figure has hidden the mechanism behind a rate it does not control. Tokens
are what the engineer changes; dollars are tokens multiplied by someone else's
price list.

Three of the eleven recipes reduce NO tokens at all (caching, batch, routing) --
they change the price of a token. The report prints "0%" for those honestly
rather than borrowing the cost saving into the token column, because conflating
the two is how a team ends up double-counting its own savings.

COUNTING. tiktoken is used when importable (exact for OpenAI models). Otherwise
a vendored estimator runs: word/punctuation split with a ~4-chars-per-token
sub-word rule. It lands within roughly 10-15% on English prose and is
deterministic, offline and dependency-free -- which matters more here than
absolute precision, because every result in these recipes is a RATIO measured
with one counter on both sides. The ratio survives a biased counter; an absolute
token count does not. The banner says which counter ran.
"""
import math, re, sys

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    COUNTER = "tiktoken cl100k_base (exact for OpenAI models)"
    def count(text):
        return len(_ENC.encode(text))
except Exception:
    COUNTER = "vendored estimator (+/-10-15% on English prose; ratios reliable)"
    _TOK = re.compile(r"[A-Za-z]+|\d+|\s+|[^\sA-Za-z\d]")
    def count(text):
        n = 0
        for piece in _TOK.findall(text):
            if piece.isspace():
                continue                          # whitespace rides with its neighbour
            if piece.isalpha():
                n += max(1, math.ceil(len(piece) / 4))   # sub-word split
            elif piece.isdigit():
                n += max(1, math.ceil(len(piece) / 3))   # digits split finer
            else:
                n += 1                            # punctuation is its own token
        return n


def pct(before, after):
    return 0.0 if not before else (1 - after / before) * 100


def money(x):
    # sign is handled separately: without this a loss of -39.16 falls through
    # the magnitude tests and prints as "$-39.160000"
    s, a = ("-" if x < 0 else ""), abs(x)
    if a >= 1:    return f"{s}${a:,.2f}"
    if a >= 0.01: return f"{s}${a:.4f}"
    return f"{s}${a:.6f}"


# --- output ------------------------------------------------------------------

W = 78

def banner(n, title, kind):
    print("=" * W)
    print(f"RECIPE {n:02d}  {title}")
    print(f"{'':10}lever class   : {kind}")
    print(f"{'':10}token counter : {COUNTER}")
    print("=" * W)


def note(text):
    for line in text.strip().splitlines():
        print("  " + line.strip())
    print()


def tokens(rows):
    """rows: [(label, in_tok, out_tok)] -- the FIRST half of every recipe."""
    print("  TOKENS")
    print(f"  {'':28} {'in':>10} {'out':>10} {'total':>10} {'change':>9}")
    base = None
    for label, i, o in rows:
        t = i + o
        if base is None:
            base, change = t, ""
        else:
            change = f"{-pct(base, t):+6.1f}%"   # negative = fewer tokens
        print(f"  {label:28} {i:>10,} {o:>10,} {t:>10,} {change:>9}")
    print()
    return base


def costs(rows, volume_per_day=None, unit="request"):
    """rows: [(label, dollars_per_unit)] -- the SECOND half, always."""
    print("  COST")
    hdr = f"  {'':28} {'/' + unit:>12}"
    if volume_per_day:
        hdr += f" {'/day':>12} {'/month':>12}"
    print(hdr + f" {'change':>9}")
    base = None
    for label, c in rows:
        line = f"  {label:28} {money(c):>12}"
        if volume_per_day:
            line += f" {money(c * volume_per_day):>12} {money(c * volume_per_day * 30):>12}"
        if base is None:
            base = c
        else:
            line += f" {-pct(base, c):+8.1f}%"
        print(line)
    print()


def verdict(text):
    print("  " + "-" * (W - 2))
    for line in text.strip().splitlines():
        print("  " + line.strip())
    print()


def headline(token_cut, cost_cut, monthly_saving=None):
    """One machine-readable line per recipe, for run_all.py to collect."""
    parts = [f"TOKENS {token_cut:+.1f}%", f"COST {cost_cut:+.1f}%"]
    if monthly_saving is not None:
        parts.append(f"SAVES {money(monthly_saving)}/mo")
    print("  RESULT: " + "  |  ".join(parts))
    print()
