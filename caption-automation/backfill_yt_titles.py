#!/usr/bin/env python3
"""
Generate missing _yt_title.txt files for videos already in output/ready_to_post/.

These were processed before the title-generation change and would otherwise
cause youtube.py to skip them. This script fills the gap without re-running
the full pipeline.

Usage:
    python3 caption-automation/backfill_yt_titles.py          # dry run
    python3 caption-automation/backfill_yt_titles.py --apply  # write files
"""

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

import requests

from title_utils import is_title_safe, title_violations

CONFIG         = Path.home() / "TellMeAJoke/config.json"
TRANSCRIPTS    = Path.home() / "TellMeAJoke/content/transcripts.csv"
READY          = Path.home() / "TellMeAJoke/output/ready_to_post"
CAPTIONS_DIR   = Path.home() / "TellMeAJoke/output/captions"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"
TITLE_SKIP_LOG = Path.home() / "TellMeAJoke/output/title_skip.log"

MAX_TITLE_RETRIES = 2

TITLE_PROMPT = """You are writing a YouTube Short title for a comedy clip.

Transcript: "{transcript}"

Write a title (5–8 words) that describes the joke's comic premise.
Rules:
- Must be advertiser-friendly: no demographic words, no sexual or crude words
  (no: gay, ethnic, black, jewish, hooker, sex, tampon, condom, nude, crabs, intimacy, or similar)
- No rating suffixes (no R, PG, 13, X)
- Describe the setup or punchline concept, not the person telling it
- Example: "Genie With Terrible Hearing" or "Cashier Knows Too Much"

Reply with the title only, no quotes, no punctuation at the end."""


def load_openai_key() -> str:
    with open(CONFIG) as f:
        return json.load(f).get("openai_api_key", "")


def load_transcripts() -> dict[str, str]:
    mapping = {}
    if not TRANSCRIPTS.exists():
        return mapping
    with open(TRANSCRIPTS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and len(row) > 2 and row[2].strip():
                mapping[Path(row[0]).stem.lower()] = row[2].strip()
    return mapping


def _call_gpt(transcript: str, api_key: str) -> str | None:
    prompt = TITLE_PROMPT.format(transcript=transcript[:1000])
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model":       "gpt-4o-mini",
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens":  30,
            },
            timeout=20,
        )
        return resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    except Exception as e:
        print(f"    API error: {e}")
        return None


def generate_title(transcript: str, api_key: str, stem: str) -> str | None:
    """Generate a safe title, retrying up to MAX_TITLE_RETRIES times on failures."""
    last_title = None
    for attempt in range(1 + MAX_TITLE_RETRIES):
        title = _call_gpt(transcript, api_key)
        if not title:
            continue
        last_title = title
        if is_title_safe(title):
            return title
        violations = title_violations(title)
        print(f"    attempt {attempt+1} flagged {violations!r}: {title!r} — retrying…")
        time.sleep(0.3)

    # Log the skip
    TITLE_SKIP_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(TITLE_SKIP_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | TITLE_SKIP | {stem} | last={last_title!r}\n")
    print(f"    ✗ No safe title after {1+MAX_TITLE_RETRIES} attempts — logged to title_skip.log")
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write the title files (default: dry run)")
    args = parser.parse_args()

    api_key     = load_openai_key()
    transcripts = load_transcripts()

    # Find all queued videos missing a _yt_title.txt
    missing = []
    for video in READY.glob("*_final.mp4"):
        stem       = video.stem.removesuffix("_final")
        title_file = CAPTIONS_DIR / f"{stem}_yt_title.txt"
        # Also check already_posted in case it was moved
        title_alt  = ALREADY_POSTED / f"{stem}_yt_title.txt"
        if not title_file.exists() and not title_alt.exists():
            missing.append((stem, video))

    if not missing:
        print("All queued videos already have _yt_title.txt files.")
        return

    print(f"\n{len(missing)} video(s) need a YouTube title:\n")

    for stem, video in missing:
        transcript = transcripts.get(stem.lower())
        if not transcript:
            print(f"  [no transcript] {stem}")
            continue

        title = generate_title(transcript, api_key, stem)
        if not title:
            print(f"  [title skipped] {stem}")
            continue

        print(f"  {stem[:50]}")
        print(f"    → {title!r}")

        if args.apply:
            CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
            (CAPTIONS_DIR / f"{stem}_yt_title.txt").write_text(title)

        time.sleep(0.3)

    if not args.apply:
        print("\n[dry run] Pass --apply to write the files.")
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
