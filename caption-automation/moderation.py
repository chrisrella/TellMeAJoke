"""
Shared content moderation logic.

Imported by batch.py, poster.py, and youtube_audit.py — one copy, no drift.

Screen order:
  1. Filename hard block  — block word in clip name → blocked, no GPT call
  2. Transcript text scan — block word in transcript → GPT sees a warning hint
  3. Short transcript     — < 30 non-space chars → uncertain_block, no GPT call
  4. GPT screen           — returns blocked + confidence (0.0–1.0)
  5. Confidence gate      — confidence < CONFIDENCE_THRESHOLD → uncertain_block

Regex note — word-boundary matching:
  "retard"      matches "retard"       but NOT "retarded" (no \b after 'd' → 'e')
  "retarded"    matches "retarded"     — both are listed so both are caught
  "blind"       matches "blind"        but NOT "blindness" (no boundary after 'd')
  "puerto rican" matches the phrase "puerto rican" — \b anchors at 'p' and 'n'
  Multi-word entries work because space isn't a word char; boundaries still fire correctly.
"""

import json
import re

import requests

BLOCK_WORDS = [
    # ── Disability / mobility ─────────────────────────────────────────────────
    "ethnic", "gay",
    "retard", "retarded",          # both listed — \b matches each full form only
    "blind", "deaf",
    "midget", "dwarf",
    "cripple", "crippled",
    "lesbian",
    "transgender", "trans",

    # ── Race (broad labels used in joke targeting) ───────────────────────────
    "black", "white",

    # ── Nationalities / ethnicities ───────────────────────────────────────────
    "puerto rican",
    "chinese",
    "irish",
    "arab", "arabic",
    "asian",
    "indian",
    "korean",
    "japanese",
    "russian",
    "cuban",
    "dominican",
    "haitian",
    "vietnamese",
    "persian",
    "armenian",
    "turkish",
    "greek",
    "french",
    "german",
    "mexican",                     # also in title_utils._DEMOGRAPHIC
    "italian",
    "polish",
    "ukrainian",
    "romanian",
    "pakistani",
    "filipino",

    # ── Religions ─────────────────────────────────────────────────────────────
    "jewish", "jew",
    "muslim",
    "catholic",
    "protestant",
    "hindu",
    "mormon",
]

# Word-boundary pattern, case-insensitive
_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BLOCK_WORDS) + r")\b",
    re.IGNORECASE,
)

CONFIDENCE_THRESHOLD = 0.7

_PROMPT = """\
You are a content moderation screener for YouTube and Instagram.

Transcript: "{transcript}"
{hint}
Answer in JSON with three fields:
- "blocked": true if the joke's PUNCHLINE primarily mocks or demeans a protected group
  (race, ethnicity, nationality, religion, sexual orientation, gender identity, disability, or age).
  false if a group is merely mentioned as context, or the joke is crude/sexual but not group-targeted.
- "confidence": float 0.0-1.0. Set BELOW 0.7 if the transcript is garbled, too short,
  mostly filler words, or the verdict is genuinely ambiguous. Set 0.9+ only when unambiguous.
- "reason": one sentence.

JSON only, no markdown.\
"""


def first_match(text: str) -> str | None:
    """Return the first block word found in text (word-boundary, case-insensitive), else None."""
    m = _PATTERN.search(text)
    return m.group(0).lower() if m else None


def moderation_screen(clip_name: str, transcript: str, api_key: str) -> tuple[bool, str]:
    """
    Return (blocked, reason).

    blocked=True  → skip this clip
    blocked=False → safe to post
    """
    # 1. Filename hard block
    tag = first_match(clip_name)
    if tag:
        return True, f"tag_block: '{tag}' in filename"

    if not api_key or not transcript:
        return False, "no transcript/key — skipping screen"

    # 2. Transcript soft flag — warn GPT without auto-blocking
    transcript_tag = first_match(transcript)
    hint = (
        f'\n⚠️  Block word "{transcript_tag}" appears in transcript — '
        f"evaluate carefully whether it is the punchline target.\n"
        if transcript_tag else ""
    )

    # 3. Short transcript guard
    if len(transcript.replace(" ", "")) < 30:
        return True, "uncertain_block: transcript too short to judge"

    # 4. GPT with confidence gate
    prompt = _PROMPT.format(transcript=transcript[:1500], hint=hint)
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model":       "gpt-4o-mini",
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens":  150,
            },
            timeout=20,
        )
        text       = resp.json()["choices"][0]["message"]["content"].strip()
        result     = json.loads(text)
        blocked    = bool(result.get("blocked"))
        confidence = float(result.get("confidence", 1.0))
        reason     = result.get("reason", "")
        if confidence < CONFIDENCE_THRESHOLD:
            return True, f"uncertain_block: confidence={confidence:.2f} — {reason}"
        return blocked, reason
    except Exception as e:
        return False, f"screen error: {e}"
