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

CONFIG      = Path.home() / "TellMeAJoke/config.json"
TRANSCRIPTS = Path.home() / "TellMeAJoke/content/transcripts.csv"


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


def generate(transcript: str, client: OpenAI) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        temperature=0.8,
        messages=[{
            "role": "user",
            "content": f"""You write Instagram captions for a comedy account called TellMeAJoke.com.
The account posts short clips of real people telling jokes on the street.

Joke transcript: "{transcript}"

Write:
- caption: 1-2 punchy sentences. Tease the joke without giving away the punchline.
  Conversational tone, no cringe. Can use 1-2 emojis max.
- hashtags: 10-15 relevant hashtags as a single string (space-separated, each starting with #).
  Mix broad (e.g. #comedy #funny) with niche (e.g. #streetcomedy #jokes).

Respond with JSON only:
{{"caption": "...", "hashtags": "..."}}"""
        }],
    )
    return json.loads(response.choices[0].message.content)


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

    result = generate(transcript, client)

    print("Caption:")
    print(f"  {result['caption']}")
    print("\nHashtags:")
    print(f"  {result['hashtags']}")
    print()

    # Also write to a .txt alongside where post_pipeline.py can pick it up
    out = Path.home() / f"TellMeAJoke/output/captions/{Path(args.clip).stem}_caption.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{result['caption']}\n\n{result['hashtags']}\n")
    print(f"Saved → {out}")


if __name__ == "__main__":
    main()
