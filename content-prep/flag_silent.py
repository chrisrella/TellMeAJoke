#!/usr/bin/env python3
"""
Scans unrated videos in content/master/ for missing or silent audio using ffprobe.
Auto-marks detected videos as "s" (skip) in ratings.csv so the review tool skips them.

Usage:
    python3 flag_silent.py            # dry run — reports count, changes nothing
    python3 flag_silent.py --execute  # writes skips to ratings.csv
"""

import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MASTER      = Path.home() / "TellMeAJoke/content/master"
RATINGS_CSV = Path.home() / "TellMeAJoke/content/ratings.csv"
EXTENSIONS  = {".mp4", ".mov"}

# Max volume threshold in dB — anything below this is considered silent.
# -60 dB is effectively inaudible; normal speech peaks around -10 to -3 dB.
SILENCE_THRESHOLD_DB = -60.0


def load_existing_ratings() -> set[str]:
    if not RATINGS_CSV.exists():
        return set()
    with open(RATINGS_CSV, newline="") as f:
        return {row["filename"] for row in csv.DictReader(f)}


def append_skips(filenames: list[str]) -> None:
    write_header = not RATINGS_CSV.exists()
    with open(RATINGS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "rating", "character", "rated_at"])
        if write_header:
            writer.writeheader()
        for name in filenames:
            writer.writerow({
                "filename":  name,
                "rating":    "s",
                "character": "n",
                "rated_at":  datetime.now().isoformat(timespec="seconds"),
            })


def has_audio_stream(path: Path) -> bool:
    """Returns True if the file has at least one audio stream."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "a", str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
        return len(data.get("streams", [])) > 0
    except json.JSONDecodeError:
        return False


def get_max_volume_db(path: Path) -> float | None:
    """
    Returns the max volume in dB by decoding the audio.
    Only called for files that have an audio stream.
    Returns None if measurement fails.
    """
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "/dev/null"],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        if "max_volume" in line:
            try:
                return float(line.split("max_volume:")[1].strip().split()[0])
            except (IndexError, ValueError):
                pass
    return None


def main(execute: bool) -> None:
    already_rated = load_existing_ratings()
    all_videos    = sorted(f for f in MASTER.iterdir() if f.suffix.lower() in EXTENSIONS)
    unrated       = [v for v in all_videos if v.name not in already_rated]

    print(f"Total videos  : {len(all_videos)}")
    print(f"Already rated : {len(already_rated)}")
    print(f"To scan       : {len(unrated)}\n")

    no_audio_stream: list[Path] = []
    silent_stream:   list[Path] = []

    for i, video in enumerate(unrated, 1):
        print(f"\r  Scanning [{i}/{len(unrated)}] {video.name[:60]:<60}", end="", flush=True)

        if not has_audio_stream(video):
            no_audio_stream.append(video)
            continue

        max_vol = get_max_volume_db(video)
        if max_vol is not None and max_vol < SILENCE_THRESHOLD_DB:
            silent_stream.append(video)

    print()  # newline after progress line

    flagged = no_audio_stream + silent_stream
    print(f"\nResults:")
    print(f"  No audio stream : {len(no_audio_stream)}")
    print(f"  Silent audio    : {len(silent_stream)}")
    print(f"  Total to skip   : {len(flagged)}")

    if not flagged:
        print("\nNo silent videos found.")
        return

    print(f"\nFirst 20 flagged:")
    for v in flagged[:20]:
        reason = "no audio stream" if v in no_audio_stream else f"silent (max < {SILENCE_THRESHOLD_DB} dB)"
        print(f"  {v.name}  [{reason}]")

    if not execute:
        print("\n=== DRY RUN — nothing written ===")
        print("Run with --execute to add these to ratings.csv as skips.")
        return

    append_skips([v.name for v in flagged])
    print(f"\nDone. {len(flagged)} videos marked as skip in ratings.csv.")


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    main(execute)
