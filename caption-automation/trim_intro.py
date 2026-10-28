#!/usr/bin/env python3
"""
Trim silent/idle intro from a video clip.

Detects the first non-silent moment using ffmpeg silencedetect,
then trims from just before that point.

Usage:
    python3 caption-automation/trim_intro.py "John tells a genie jokeR.mp4"
    python3 caption-automation/trim_intro.py input.mp4 --output trimmed.mp4
    python3 caption-automation/trim_intro.py input.mp4 --dry-run
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

MASTER = Path.home() / "TellMeAJoke/content/master"

SILENCE_DB  = -35   # dB threshold — below this is "silence"
SILENCE_DUR = 0.05  # seconds of silence to confirm a gap (50ms)
BUFFER      = 0.15  # seconds to keep before audio starts (so cut isn't jarring)
MIN_TRIM    = 0.3   # don't bother trimming if gap is smaller than this


def detect_audio_start(video_path: Path) -> float | None:
    """Return seconds when audio first starts, or None if no leading silence."""
    result = subprocess.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_DUR}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    # silencedetect writes to stderr, e.g.:
    #   silence_end: 1.234 | silence_duration: 1.234
    matches = re.findall(r"silence_end:\s*([\d.]+)", result.stderr)
    if not matches:
        return None  # no silence found at all — audio starts immediately
    first_end = float(matches[0])
    if first_end < MIN_TRIM:
        return None  # gap too short to bother
    return first_end


def trim_clip(input_path: Path, output_path: Path, start: float) -> bool:
    trim_from = max(0.0, start - BUFFER)
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(trim_from),
            "-i", str(input_path),
            "-c", "copy",
            str(output_path),
        ],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Trim silent intro from a clip.")
    parser.add_argument("clip",      help="Clip filename or full path")
    parser.add_argument("--output",  help="Output path (default: overwrites input in-place)")
    parser.add_argument("--dry-run", action="store_true", help="Show trim amount without modifying file")
    args = parser.parse_args()

    input_path = Path(args.clip)
    if not input_path.is_absolute():
        input_path = MASTER / input_path.name
    if not input_path.exists():
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    print(f"Analysing: {input_path.name}")
    audio_start = detect_audio_start(input_path)

    if audio_start is None:
        print("  No significant leading silence detected — nothing to trim.")
        return

    trim_from = max(0.0, audio_start - BUFFER)
    print(f"  Audio starts at : {audio_start:.2f}s")
    print(f"  Trimming from   : {trim_from:.2f}s  (keeping {BUFFER}s buffer)")

    if args.dry_run:
        print("  [dry-run] No file modified.")
        return

    output_path = Path(args.output) if args.output else input_path
    if output_path == input_path:
        # Trim in-place: write to temp then replace
        tmp = input_path.with_suffix(".trimtmp.mp4")
        ok  = trim_clip(input_path, tmp, audio_start)
        if ok:
            input_path.unlink()
            tmp.rename(input_path)
        else:
            tmp.unlink(missing_ok=True)
            print("  Error: ffmpeg failed.")
            sys.exit(1)
    else:
        ok = trim_clip(input_path, output_path, audio_start)
        if not ok:
            print("  Error: ffmpeg failed.")
            sys.exit(1)

    print(f"  Done → {output_path.name}")


if __name__ == "__main__":
    main()
