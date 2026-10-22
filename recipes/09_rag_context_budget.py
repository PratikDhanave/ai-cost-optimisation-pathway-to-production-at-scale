#!/usr/bin/env python3
"""RECIPE 09 - Give retrieval a token budget.

RAG turns a retrieval parameter into a line on the bill. top_k=20 was set during
a demo and never revisited; it is now twenty chunks of context on every request,
most of them irrelevant, all of them billed at input rates -- and relevance
falls off a cliff after the first few.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, pct, money, scaled
import prices as P

banner(9, "Give retrieval a token budget", "structural - retrieval budget")

CHUNK, QUESTION, SYS, OUT = 520, 40, 180, 350

def ctx(k, trim=1.0):
    return SYS + QUESTION + int(k * CHUNK * trim)

rows = [("top_k=20, full chunks",    ctx(20), OUT),
        ("top_k=5,  full chunks",    ctx(5),  OUT),
        ("top_k=5,  reranked+trimmed", ctx(5, 0.55), OUT)]

note("""
Same corpus, same question, same answer quality target. The retriever returns 20
chunks ranked by embedding similarity; a reranker reorders them and a trim keeps
only the passages that carry the answer.
""")

tokens(rows)

VOL = scaled(60_000)
cs = [(label, P.cost(i, o, "big")) for label, i, o in rows]
costs(cs, volume_per_day=VOL)

saving = (cs[0][1] - cs[2][1]) * VOL * 30

note(f"""
EMBEDDINGS ARE NOT THE COST. The retrieval side of RAG is embedding calls at a
fraction of generation rates, and they are paid ONCE per document at index time.
Re-embedding a corpus is a one-off; sending 20 chunks per request is paid
forever. Optimise the request, not the index.
""")

verdict(f"""
top_k 20 -> 5 with reranking: {pct(rows[0][1] + OUT, rows[2][1] + OUT):.0f}% fewer
tokens and {money(saving)}/month at {VOL:,} queries/day.

WHY IT USUALLY IMPROVES ANSWERS TOO. Fifteen irrelevant chunks are not harmless
padding -- they dilute attention and give the model more opportunity to ground an
answer in the wrong passage. Fewer, better-ranked chunks is the rare change that
moves cost and quality the same direction.

HOW TO SET k HONESTLY: measure answer accuracy against k on a labelled question
set, find the knee, then set k one notch above it. If accuracy is flat from k=4
to k=20, you have been paying for sixteen chunks of nothing.

AND KEEP THE ORDER RIGHT FOR CACHING: system prompt first, then retrieved
chunks, then the question. Retrieved context changes per request, so it must sit
AFTER everything stable or it breaks the cache prefix from recipe 05.
""")
headline(-pct(rows[0][1] + OUT, rows[2][1] + OUT), -pct(cs[0][1], cs[2][1]), saving)
