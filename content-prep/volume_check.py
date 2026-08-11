#!/usr/bin/env python3
"""
Samples 100 random unrated videos and prints their mean_volume in dB.
Use this to decide a good silence threshold for flag_silent.py.

Usage:
    python3 volume_check.py
"""

import json
import random
import subprocess
import csv
from pathlib import Path

MASTER      = Path.home() / "TellMeAJoke/content/master"
RATINGS_CSV = Path.home() / "TellMeAJoke/content/ratings.csv"
EXTENSIONS  = {".mp4", ".mov"}
SAMPLE_SIZE = 100


def load_existing_ratings() -> set[str]:
    if not RATINGS_CSV.exists():
        return set()
    with open(RATINGS_CSV, newline="") as f:
        return {row["filename"] for row in csv.DictReader(f)}


def get_mean_volume_db(path: Path) -> float | None:
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "/dev/null"],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split()[0])
            except (IndexError, ValueError):
                pass
    return None


def main() -> None:
    already_rated = load_existing_ratings()
    unrated = [
        f for f in MASTER.iterdir()
        if f.suffix.lower() in EXTENSIONS and f.name not in already_rated
    ]
    sample = random.sample(unrated, min(SAMPLE_SIZE, len(unrated)))

    print(f"Sampling {len(sample)} random unrated videos...\n")

    volumes = []
    for i, video in enumerate(sample, 1):
        print(f"\r  [{i}/{len(sample)}] {video.name[:60]:<60}", end="", flush=True)
        vol = get_mean_volume_db(video)
        if vol is not None:
            volumes.append((vol, video.name))

    print("\n")
    volumes.sort()

    # Histogram buckets
    buckets = [
        ("< -70 dB  (dead silence)",   lambda v: v < -70),
        ("-70 to -50 dB  (near silent)", lambda v: -70 <= v < -50),
        ("-50 to -40 dB  (very quiet)",  lambda v: -50 <= v < -40),
        ("-40 to -30 dB  (quiet)",       lambda v: -40 <= v < -30),
        ("-30 to -20 dB  (normal low)",  lambda v: -30 <= v < -20),
        ("-20 to -10 dB  (normal)",      lambda v: -20 <= v < -10),
        ("> -10 dB   (loud)",            lambda v: v >= -10),
    ]

    print("Volume distribution:")
    for label, test in buckets:
        count = sum(1 for v, _ in volumes if test(v))
        bar = "█" * count
        print(f"  {label:<30} {count:>3}  {bar}")

    print(f"\nQuietest 10 videos:")
    for vol, name in volumes[:10]:
        print(f"  {vol:>7.1f} dB  {name}")

    print(f"\nSuggested threshold: look at the gap in the distribution above.")
    print(f"If quiet videos cluster below -40 dB, use -40 as the cutoff.")


if __name__ == "__main__":
    main()
