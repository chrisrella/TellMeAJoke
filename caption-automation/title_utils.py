"""
Shared title safety check for YouTube titles.

Used by generate_caption.py, backfill_yt_titles.py, and youtube_audit.py.
A title must pass before it is written to disk or used for upload.
"""

import re

# Demographic words (same list as the audit)
_DEMOGRAPHIC = [
    "ethnic", "gay", "lesbian", "retarded", "retard", "black", "jewish", "jew",
    "mexican", "italian", "polish", "old lady", "gasp",
    "blind", "deaf", "crippled", "midget", "dwarf",
]

# Sexual / crude words that trigger age-restriction or limited ads
_CRUDE = [
    "hooker", "prostitute", "escort", "tampon", "condom", "penis", "vagina",
    "dick", "cock", "balls", "tit", "boob", "cum", "jizz", "boner", "erection",
    "masturbat", "porn", "nude", "naked", "hookers", "sex", "hooker",
    "crab", "crabs", "intimacy", "intimate",
]

TITLE_BLOCKED_WORDS = _DEMOGRAPHIC + _CRUDE

# Pre-compile: whole-word match, case-insensitive
_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in TITLE_BLOCKED_WORDS) + r")\b",
    re.IGNORECASE,
)


def title_violations(title: str) -> list[str]:
    """Return list of blocked words found in the title (empty = safe)."""
    return [m.group(0) for m in _PATTERN.finditer(title)]


def is_title_safe(title: str) -> bool:
    return len(title_violations(title)) == 0
