#!/usr/bin/env python3
"""RECIPE 18 - Automated prompt compression, and the call that does the work.

Compressors promise large reductions on verbose context. The arithmetic people
skip is that compressing a prompt takes a MODEL CALL, and that call is billed
like any other. Compress once and reuse the result a thousand times and it is
free money. Compress on every request and you have added an inference to save
an inference.

Recipe 02 is the hand-written version of this and costs nothing to run. Reach
for the automated kind when the content is machine-generated or too large to
edit by hand -- retrieved documents, transcripts, logs -- not for your own
system prompt, which you should simply rewrite.
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _harness import banner, note, tokens, costs, verdict, headline, money, pct
import prices as P

banner(18, "Prompt compression and who pays the compressor", "input side - not free")

RAW, OUT, RATIO = 9_000, 600, 3.2
COMPRESSED = round(RAW / RATIO)
# the compressor reads the raw prompt and writes the compressed one, on the
# cheap model -- but it is still a call, and it is billed
COMPRESS_COST = P.cost(RAW, COMPRESSED, "small")

uncompressed = P.cost(RAW, OUT, "big")
compressed = P.cost(COMPRESSED, OUT, "big")

note(f"""
A {RAW:,}-token context compressed {RATIO:.1f}x to {COMPRESSED:,} tokens.
inference, uncompressed   {money(uncompressed)}
inference, compressed     {money(compressed)}   saves {money(uncompressed-compressed)}
the compressor call       {money(COMPRESS_COST)}   <-- the line people omit
""")

tokens([("raw context", RAW, OUT), ("compressed", COMPRESSED, OUT)])

costs([("no compression", uncompressed),
       ("compressed, per request", compressed + COMPRESS_COST),
       ("compressed, reused 50x", compressed + COMPRESS_COST / 50)],
      volume_per_day=60_000)

reuses = COMPRESS_COST / max(1e-12, uncompressed - compressed)
note(f"""
BREAK-EVEN: the compressor costs {COMPRESS_COST/(uncompressed-compressed):.2f}x what
one compression saves. Compress and use it once and you have roughly broken
even -- all that work, no money. The win only arrives on REUSE.

Compress-per-request is {'STILL WORTH IT' if compressed + COMPRESS_COST < uncompressed else 'A LOSS'}
here: {money(compressed + COMPRESS_COST)} against {money(uncompressed)} uncompressed.
Change the compressor's model or the ratio and that flips -- which is the whole
point of computing it rather than assuming it.
""")

verdict(f"""
THE QUESTION IS REUSE, NOT RATIO. A 20x compressor that runs on every request
can lose money; a 2x compressor on a document you query fifty times is free
after the second query. Compress things that are STABLE and queried REPEATEDLY:
a knowledge-base article, a contract, a transcript. Do not compress the user's
question -- it is short, it is used once, and it is the part you cannot afford
to garble.

AND IT COMPOSES BADLY WITH CACHING unless you are careful. A compressor whose
output varies run to run gives you a prefix that changes every time, which
breaks prompt caching (recipe 05) and costs you the write premium forever. If
you compress, compress ONCE, store the result, and cache that -- deterministic
output is a hard requirement here, not a nicety.

MEASURE THE QUALITY LOSS. Compression drops tokens the compressor judged
redundant. Sometimes it was right. Run your eval set against compressed and
uncompressed context and look at cost per CORRECT answer, exactly as in
recipes 04 and 15 -- the saving is real and so is the risk.
""")
headline(-pct(RAW + OUT, COMPRESSED + OUT), -pct(uncompressed, compressed + COMPRESS_COST),
         (uncompressed - compressed - COMPRESS_COST) * 60_000 * 30)
