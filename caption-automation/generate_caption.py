#!/usr/bin/env python3
"""
Generate an Instagram caption + hashtags for a joke clip using GPT-4o.

Usage:
    python3 caption-automation/generate_caption.py "Frank tells mexican joke.mp4"
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from openai import OpenAI

from title_utils import is_title_safe, title_violations

CONFIG      = Path.home() / "TellMeAJoke/config.json"
TRANSCRIPTS = Path.home() / "TellMeAJoke/content/transcripts.csv"
TITLE_SKIP_LOG = Path.home() / "TellMeAJoke/output/title_skip.log"

MAX_TITLE_RETRIES = 2


def load_config() -> dict:
    if not CONFIG.exists():
        print("config.json not found.")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


def get_transcript(clip_name: str) -> str | None:
    if not TRANSCRIPTS.exists():
        return None
    with open(TRANSCRIPTS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and Path(row[0]).name == clip_name:
                return row[2].strip() if len(row) > 2 else None
    return None


_CAPTION_PROMPT = """You write captions for a comedy account called TellMeAJoke.com.
The account posts short clips of real people telling jokes on the street.

Joke transcript: "{transcript}"

Write three things:

1. caption: 1-2 punchy sentences. Tease the setup or reaction — never give away the punchline.
   Conversational tone. 1-2 emojis max.
   Do NOT start with "Ever heard a joke", "This joke", "Wait for it", or any hype opener.
   Do NOT use demographic labels (e.g. ethnic, gay, retarded, blonde, Mexican, Jewish, etc.).
   Write about the situation or premise instead.

2. hashtags: 10-15 hashtags as a single space-separated string (each starting with #).
   Mix broad (#comedy #funny) with niche (#streetcomedy #jokes #tellmeajoke).
   No hashtags with demographic slurs or slang.

3. youtube_title: 5-8 words describing the joke's comic premise.
   Must be advertiser-friendly — no demographic words, no sexual or crude words
   (no: hooker, sex, tampon, condom, nude, crabs, intimacy, or similar).
   No rating suffix (no R, PG, 13, X).
   Describe the premise, not the person.
   Example: "Genie With Terrible Hearing" or "Cashier Knows Everything About You".

Respond with JSON only:
{{"caption": "...", "hashtags": "...", "youtube_title": "..."}}"""


def generate(transcript: str, client: OpenAI) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        temperature=0.8,
        messages=[{"role": "user", "content": _CAPTION_PROMPT.format(transcript=transcript)}],
    )
    return json.loads(response.choices[0].message.content)


def safe_yt_title(transcript: str, client: OpenAI, clip_name: str) -> str | None:
    """Generate a title, retry up to MAX_TITLE_RETRIES times if it fails the safety check."""
    for attempt in range(1 + MAX_TITLE_RETRIES):
        result   = generate(transcript, client)
        title    = result.get("youtube_title", "").strip()
        if not title:
            continue
        if is_title_safe(title):
            return title
        violations = title_violations(title)
        print(f"  Title attempt {attempt+1} flagged {violations!r}: {title!r} — retrying…")

    # All attempts failed — log and skip
    TITLE_SKIP_LOG.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    with open(TITLE_SKIP_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | TITLE_SKIP | {clip_name} | last={title!r} | flags={violations!r}\n")
    print(f"  ✗ Could not generate a safe title after {1+MAX_TITLE_RETRIES} attempts — skipping YT title.")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Instagram caption + hashtags for a clip.")
    parser.add_argument("clip", help="Clip filename")
    args = parser.parse_args()

    clip_name  = Path(args.clip).name
    transcript = get_transcript(clip_name)

    if not transcript:
        print(f"No transcript found for {clip_name!r} in transcripts.csv")
        sys.exit(1)

    config = load_config()
    client = OpenAI(api_key=config["openai_api_key"])

    print(f"\nClip      : {clip_name}")
    print(f"Transcript: {transcript[:100]}{'…' if len(transcript) > 100 else ''}\n")

    # Caption + hashtags (one call)
    result = generate(transcript, client)

    print("Caption:")
    print(f"  {result['caption']}")
    print("\nHashtags:")
    print(f"  {result['hashtags']}")
    print()

    out_dir = Path.home() / "TellMeAJoke/output/captions"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.clip).stem

    caption_file = out_dir / f"{stem}_caption.txt"
    caption_file.write_text(f"{result['caption']}\n\n{result['hashtags']}\n")
    print(f"Saved caption → {caption_file}")

    # YouTube title — checked and retried for safety
    yt_title = safe_yt_title(transcript, client, clip_name)
    if yt_title:
        yt_title_file = out_dir / f"{stem}_yt_title.txt"
        yt_title_file.write_text(yt_title)
        print(f"Saved YT title → {yt_title_file}  ({yt_title!r})")


if __name__ == "__main__":
    main()
