#!/usr/bin/env python3
"""Speak an agent's reply, and price what speaking it cost.

Two things this is NOT, stated up front because both are easy to assume:

  NOT real-time conversational voice. That needs the Live API
  (`bidiGenerateContent`), which this key has no access to -- all fifty models
  it can reach support `generateContent` only, so ADK's microphone button in
  the dev UI will not connect. This is text-to-speech on a reply that has
  already been generated.

  NOT free. Audio is billed per token at its own rate. A live call returned
  9 text tokens in and 72 AUDIO tokens out for 2.9 seconds of speech -- about
  25 audio tokens per second, almost independent of how few words were said.
  Priced correctly rather than at the text rate, that clip costs 2.4x more.

Standard library only: urllib, wave, json. No SDK.

    GOOGLE_API_KEY=$(cat ~/.gemini_key) python3 voice.py "text to speak"
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import sys
import urllib.request
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cost_core import price, read_usage

ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent?key={key}")
DEFAULT_MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-preview-tts")
DEFAULT_VOICE = os.environ.get("TTS_VOICE", "Kore")
RATE_HZ = 24_000          # what the API returns: L16 PCM, mono, 24 kHz


def speak(text: str, *, model: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE,
          out_path: str | None = None, key: str | None = None):
    """Returns (wav_path, seconds, Usage, Cost). Raises on an API error."""
    key = key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GOOGLE_API_KEY / GEMINI_API_KEY in the environment")

    body = json.dumps({
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }).encode()
    req = urllib.request.Request(ENDPOINT.format(model=model, key=key), data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = json.load(r)

    if "error" in payload:
        raise RuntimeError(f"{payload['error'].get('code')}: "
                           f"{payload['error'].get('message')}")

    part = payload["candidates"][0]["content"]["parts"][0]["inlineData"]
    pcm = base64.b64decode(part["data"])

    # The API returns headerless PCM; wrap it so it is playable anywhere.
    out_path = out_path or "/tmp/agent_voice.wav"
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)          # L16 = 16-bit
        w.setframerate(RATE_HZ)
        w.writeframes(pcm)

    usage = read_usage(payload.get("usageMetadata"))
    cost = price(model, usage)
    seconds = len(pcm) / 2 / RATE_HZ
    return out_path, seconds, usage, cost


def _report(text, path, seconds, usage, cost):
    from cost_core import Usage
    print(f'  spoke      : "{text[:58]}{"..." if len(text) > 58 else ""}"')
    print(f"  wav        : {path}  ({seconds:.2f}s, {RATE_HZ // 1000} kHz mono)")
    if usage is None:
        print("  usage      : the API reported none"); return
    print(f"  tokens     : {usage.in_tokens} in, {usage.out_tokens} out "
          f"({usage.audio_out} of them AUDIO)")
    print(f"  cost       : {'$%.6f' % cost.usd if cost.known else cost.reason}")
    if usage.audio_out and cost.known:
        as_text = price(DEFAULT_MODEL, Usage(usage.in_tokens, usage.out_tokens))
        if as_text.known and as_text.usd:
            print(f"  if audio were priced as text: ${as_text.usd:.6f} "
                  f"-> speaking it is {cost.usd / as_text.usd:.1f}x")
    if usage.audio_out and seconds:
        print(f"  rate       : {usage.audio_out / seconds:.0f} audio tokens per "
              f"second of speech -- length drives this, not word count")


def main():
    text = " ".join(sys.argv[1:]) or "Your session cost one tenth of a cent."
    try:
        path, seconds, usage, cost = speak(text)
    except Exception as e:
        print(f"  voice failed: {e}")
        return 1
    _report(text, path, seconds, usage, cost)
    return 0


if __name__ == "__main__":
    sys.exit(main())
