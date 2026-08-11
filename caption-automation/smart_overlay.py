#!/usr/bin/env python3
"""
Smart emoji overlay: GPT-4o reads the transcript and picks an emoji,
timing, and position — then burns it onto the video.

Works for any joke theme; no pre-generated assets needed.

Usage:
    python3 caption-automation/smart_overlay.py "Frank tells mexican joke.mp4" --input blurred.mp4
    python3 caption-automation/smart_overlay.py "clip.mp4" --input blurred.mp4 --output out.mp4
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import requests
from openai import OpenAI

CONFIG      = Path.home() / "TellMeAJoke/config.json"
MASTER      = Path.home() / "TellMeAJoke/content/master"
TRANSCRIPTS = Path.home() / "TellMeAJoke/content/transcripts.csv"
OUTPUT      = Path.home() / "TellMeAJoke/output/overlaid"

EMOJI_CACHE = Path.home() / "TellMeAJoke/assets/emojis"
EMOJI_SCALE = 0.18   # emoji width as fraction of video width
MARGIN      = 0.03


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


def video_dimensions(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    parts = [v for v in r.stdout.strip().split(",") if v]
    return int(parts[0]), int(parts[1])


def video_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def emoji_to_code(emoji_char: str) -> str:
    """Convert emoji to Twemoji codepoint string (e.g. '1f602' or '1f1fa-1f1f8')."""
    # Strip variation selector U+FE0F — Twemoji filenames don't include it
    points = [f"{ord(c):x}" for c in emoji_char if ord(c) != 0xFE0F]
    return "-".join(points)


FALLBACK_EMOJI = "1f602"  # 😂

def fetch_emoji_png(emoji_char: str) -> Path:
    """Return a local PNG for the emoji, downloading from Twemoji CDN if needed."""
    EMOJI_CACHE.mkdir(parents=True, exist_ok=True)
    code   = emoji_to_code(emoji_char)
    cached = EMOJI_CACHE / f"{code}.png"
    if cached.exists():
        return cached
    url = f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{code}.png"
    r   = requests.get(url, timeout=10)
    if not r.ok and code != FALLBACK_EMOJI:
        print(f"  Warning: emoji {emoji_char!r} not in Twemoji ({code}), using 😂")
        fallback = EMOJI_CACHE / f"{FALLBACK_EMOJI}.png"
        if not fallback.exists():
            fb_url = f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{FALLBACK_EMOJI}.png"
            fallback.write_bytes(requests.get(fb_url, timeout=10).content)
        return fallback
    cached.write_bytes(r.content)
    print(f"  Downloaded {emoji_char} → {cached.name}")
    return cached


def resolve_position(label: str, vid_w: int, vid_h: int,
                     emoji_px: int) -> tuple[int, int]:
    m       = int(vid_w * MARGIN)
    right_x = vid_w - emoji_px - m
    bot_y   = vid_h - emoji_px - m
    return {
        "top-left":     (m, m),
        "top-right":    (right_x, m),
        "top-center":   ((vid_w - emoji_px) // 2, m),
        "bottom-left":  (m, bot_y),
        "bottom-right": (right_x, bot_y),
    }.get(label, (right_x, m))


def ask_gpt(client: OpenAI, transcript: str, duration: float) -> dict:
    prompt = f"""You are adding a single fun emoji reaction to a short joke video.

Transcript: "{transcript}"
Video duration: {duration:.1f} seconds

Pick:
- emoji: one emoji character that best matches the joke's punchline or vibe
  (e.g. 🌮 for a Mexican food joke, 💀 for dark humor, 🐄 for a cow joke)
- start_sec: when to show it — ideally just before or at the punchline
- end_sec: when to hide it — typically 2-4 seconds after it appears, max {duration - 0.2:.1f}
- position: where to place it — one of: top-left, top-right, top-center, bottom-left, bottom-right
  (avoid covering the joke-teller's face; top corners are usually safe)

Respond with JSON only:
{{"emoji": "🌮", "start_sec": 5.0, "end_sec": 8.5, "position": "top-right"}}"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return json.loads(resp.choices[0].message.content)


def overlay_emoji(src: Path, emoji_png: Path, start: float, end: float,
                  x: int, y: int, emoji_px: int, out_path: Path) -> None:
    duration = video_duration(src)
    end = min(end, duration - 0.1)
    end = max(end, start + 0.5)

    filt = (
        f"[1:v]scale={emoji_px}:{emoji_px}[em];"
        f"[0:v][em]overlay={x}:{y}:enable='between(t,{start:.3f},{end:.3f})'[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-loop", "1", "-i", str(emoji_png),
        "-filter_complex", filt,
        "-map", "[out]", "-map", "0:a?",
        "-t", str(duration),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg error:\n" + result.stderr[-3000:])
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="GPT-4o emoji overlay.")
    parser.add_argument("clip",     help="Source clip filename")
    parser.add_argument("--input",  required=True,
                        help="Input video path (e.g. the blurred 9:16 video)")
    parser.add_argument("--output", default=None,
                        help="Output path (default: output/overlaid/<stem>_overlaid.mp4)")
    args = parser.parse_args()

    clip_name  = Path(args.clip).name
    stem       = Path(args.clip).stem
    src        = Path(args.input)

    if not src.exists():
        print(f"Error: input not found:\n  {src}")
        sys.exit(1)

    transcript = get_transcript(clip_name) or "(transcript unavailable)"
    duration   = video_duration(src)
    vid_w, vid_h = video_dimensions(src)
    emoji_px   = max(40, int(vid_w * EMOJI_SCALE))

    print(f"\nClip      : {clip_name}")
    print(f"Duration  : {duration:.1f}s  ({vid_w}×{vid_h})")
    print(f"Transcript: {transcript[:80]}{'…' if len(transcript) > 80 else ''}\n")

    config = load_config()
    client = OpenAI(api_key=config["openai_api_key"])

    print("Asking GPT-4o for emoji…")
    decision = ask_gpt(client, transcript, duration)
    emoji    = decision.get("emoji", "😂")
    start    = float(decision.get("start_sec", max(0, duration - 4)))
    end      = float(decision.get("end_sec",   duration - 0.5))
    position = decision.get("position", "top-right")
    px, py   = resolve_position(position, vid_w, vid_h, emoji_px)

    print(f"  Emoji    : {emoji}")
    print(f"  Timing   : {start:.1f}s → {end:.1f}s")
    print(f"  Position : {position}  ({px}, {py})")

    print("\nFetching emoji PNG…")
    emoji_png = fetch_emoji_png(emoji)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT / f"{stem}_overlaid.mp4"

    overlay_emoji(src, emoji_png, start, end, px, py, emoji_px, out_path)
    print(f"Done → {out_path}\n")


if __name__ == "__main__":
    main()
