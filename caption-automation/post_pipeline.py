#!/usr/bin/env python3
"""
End-to-end pipeline for a single clip → Instagram-ready output.

Steps:
  A  Filter: confirm clip is rated 'good' in transcripts.csv
  B  Blur:   convert to 9:16 TikTok format with blurred background
  D  Sticker: GPT-4o picks and overlays the right prop
  C  Caption: ZapCap burns captions onto the video
  E  Copy:   GPT-4o generates Instagram caption + hashtags
  F  Post:   Upload and publish to Instagram as a Reel (requires --post flag)

Usage:
    python3 caption-automation/post_pipeline.py "Frank tells mexican joke.mp4" --theme mexican

    # Also post to Instagram when done:
    python3 caption-automation/post_pipeline.py "clip.mp4" --theme mexican --post

    # Skip the approved-only check (e.g. for testing):
    python3 caption-automation/post_pipeline.py "clip.mp4" --theme animals --no-filter

    # Skip sticker step:
    python3 caption-automation/post_pipeline.py "clip.mp4" --no-sticker
"""

import argparse
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS     = Path(__file__).parent
MASTER      = Path.home() / "TellMeAJoke/content/master"
TRANSCRIPTS = Path.home() / "TellMeAJoke/content/transcripts.csv"
OUTPUT      = Path.home() / "TellMeAJoke/output/ready_to_post"

APPROVED_RATINGS = {"good", "funny", "approved"}


def run(label: str, cmd: list[str]) -> bool:
    print(f"\n{'─'*52}")
    print(f"  {label}")
    print(f"{'─'*52}")
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print(f"\n  ✗ {label} failed.")
        return False
    return True


def get_rating(clip_name: str) -> str | None:
    if not TRANSCRIPTS.exists():
        return None
    with open(TRANSCRIPTS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and Path(row[0]).name == clip_name:
                return row[1].strip().lower() if len(row) > 1 else None
    return None


def list_approved() -> list[str]:
    """Return all clip filenames rated as approved in transcripts.csv."""
    approved = []
    if not TRANSCRIPTS.exists():
        return approved
    with open(TRANSCRIPTS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and len(row) > 1 and row[1].strip().lower() in APPROVED_RATINGS:
                approved.append(Path(row[0]).name)
    return approved


def main() -> None:
    parser = argparse.ArgumentParser(description="Full per-clip post pipeline (A→B→D→C→E).")
    parser.add_argument("clip",          nargs="?", help="Clip filename, e.g. 'Frank tells mexican joke.mp4'")
    parser.add_argument("--no-filter",   action="store_true",
                        help="Skip the approved-rating check (useful for testing)")
    parser.add_argument("--no-sticker",  action="store_true",
                        help="Skip the emoji overlay step")
    parser.add_argument("--auto", action="store_true",
                        help="Skip caption review and render immediately")
    parser.add_argument("--post", action="store_true",
                        help="After rendering, upload and publish to Instagram (step F)")
    parser.add_argument("--list-approved", action="store_true",
                        help="Print all approved clips and exit")
    args = parser.parse_args()

    if args.list_approved:
        clips = list_approved()
        print(f"\n{len(clips)} approved clips:\n")
        for c in clips:
            print(f"  {c}")
        print()
        return

    if not args.clip:
        print("Error: clip filename required. Use --list-approved to see approved clips.")
        sys.exit(1)

    clip_name = Path(args.clip).name
    stem      = Path(args.clip).stem
    src       = MASTER / clip_name

    if not src.exists():
        print(f"Error: clip not found:\n  {src}")
        sys.exit(1)

    # ── A: filter ────────────────────────────────────────────────────────────
    if not args.no_filter:
        rating = get_rating(clip_name)
        if rating not in APPROVED_RATINGS:
            print(f"\nClip not approved (rating: {rating!r}). Use --no-filter to override.")
            sys.exit(1)
        print(f"\n[A] Approved ✓  (rating: {rating})")
    else:
        print(f"\n[A] Filter skipped")

    print(f"    Clip   : {clip_name}")
    print(f"    Emoji  : {'skip (--no-sticker)' if args.no_sticker else 'GPT-4o pick'}")

    OUTPUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)

        blurred   = tmp / f"{stem}_blurred.mp4"
        overlaid  = tmp / f"{stem}_overlaid.mp4"
        captioned = OUTPUT / f"{stem}_final.mp4"

        # ── B: blur ──────────────────────────────────────────────────────────
        ok = run("[B] TikTok blur", [
            "python3", str(SCRIPTS / "blur_clip.py"),
            clip_name,
            "--output", str(blurred),
        ])
        if not ok:
            sys.exit(1)

        sticker_input = blurred

        # ── D: emoji overlay ─────────────────────────────────────────────────
        if not args.no_sticker:
            ok = run("[D] Emoji overlay", [
                "python3", str(SCRIPTS / "smart_overlay.py"),
                clip_name,
                "--input", str(blurred),
                "--output", str(overlaid),
            ])
            if ok:
                sticker_input = overlaid
            else:
                print("  ⚠ Emoji overlay failed — continuing without it")

        # ── C: ZapCap captions ───────────────────────────────────────────────
        zapcap_cmd = ["python3", str(SCRIPTS / "zapcap.py"), str(sticker_input)]
        if args.auto:
            zapcap_cmd.append("--auto")
        ok = run("[C] ZapCap captions", zapcap_cmd)
        if not ok:
            sys.exit(1)

        # zapcap.py saves to output/captioned/<filename> — move to final output
        zapcap_out = Path.home() / f"TellMeAJoke/output/captioned/{sticker_input.name}"
        if zapcap_out.exists():
            # Force yuv420p — ZapCap outputs yuvj420p which Instagram rejects
            result = subprocess.run([
                "ffmpeg", "-y", "-i", str(zapcap_out),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                str(captioned),
            ], capture_output=True, text=True)
            if result.returncode != 0:
                captioned.write_bytes(zapcap_out.read_bytes())  # fallback: copy as-is
            zapcap_out.unlink()
        else:
            print(f"Warning: expected ZapCap output at {zapcap_out}, check output/captioned/")

        # ── E: Instagram caption + hashtags ──────────────────────────────────
        run("[E] Generate Instagram caption", [
            "python3", str(SCRIPTS / "generate_caption.py"),
            clip_name,
        ])

    caption_txt = Path.home() / f"TellMeAJoke/output/captions/{stem}_caption.txt"
    print(f"\n{'='*52}")
    print(f"  Pipeline complete!")
    print(f"  Video  : {captioned}")
    if caption_txt.exists():
        print(f"  Caption: {caption_txt}")
        print()
        print(caption_txt.read_text())
    print(f"{'='*52}\n")

    # ── F: post to Instagram + Facebook + YouTube ────────────────────────────
    if args.post:
        run("[F] Post to Instagram", [
            "python3", str(SCRIPTS / "instagram.py"),
            args.clip,
        ])
        run("[F] Post to Facebook", [
            "python3", str(SCRIPTS / "facebook.py"),
            args.clip,
        ])
        run("[F] Post to YouTube", [
            "python3", str(SCRIPTS / "youtube.py"),
            args.clip,
        ])


if __name__ == "__main__":
    main()
