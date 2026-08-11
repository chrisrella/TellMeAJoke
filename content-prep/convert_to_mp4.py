#!/usr/bin/env python3
"""
Converts all .wmv and .flv files in content/master/ to .mp4 using ffmpeg.
Deletes the original only after a confirmed successful conversion.
Skips files that already have an .mp4 counterpart (safe to re-run).

Usage:
    python3 convert_to_mp4.py            # dry run
    python3 convert_to_mp4.py --execute  # convert and delete originals
"""

import sys
import csv
import subprocess
from pathlib import Path

MASTER = Path.home() / "TellMeAJoke/content/master"
LOG    = Path.home() / "TellMeAJoke/content/convert_log.csv"
TARGET_EXTENSIONS = {".wmv", ".flv"}


def find_targets(folder: Path) -> list[Path]:
    return [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in TARGET_EXTENSIONS
    ]


def already_converted(source: Path) -> bool:
    """True if an mp4 with the same stem already exists alongside the source."""
    return source.with_suffix(".mp4").exists()


def convert(source: Path, dest: Path) -> tuple[bool, str]:
    """Run ffmpeg. Returns (success, error_message)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source),
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(dest)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Pull the last meaningful ffmpeg error line
        error = next(
            (l for l in reversed(result.stderr.splitlines()) if l.strip()),
            "unknown error"
        )
        return False, error
    return True, ""


def main(execute: bool) -> None:
    if not MASTER.exists():
        print(f"ERROR: master folder not found: {MASTER}")
        sys.exit(1)

    targets = find_targets(MASTER)
    already_done = [f for f in targets if already_converted(f)]
    to_convert   = [f for f in targets if not already_converted(f)]

    print(f"Found {len(targets)} wmv/flv files")
    print(f"  Already converted (will skip): {len(already_done)}")
    print(f"  To convert                   : {len(to_convert)}\n")

    if not execute:
        print("=== DRY RUN — nothing converted ===")
        for f in to_convert[:20]:
            print(f"  {f.name}  →  {f.stem}.mp4")
        if len(to_convert) > 20:
            print(f"  ... and {len(to_convert) - 20} more")
        print("\nRun with --execute to convert.")
        return

    log_rows = []
    converted = 0
    failed    = 0

    for i, source in enumerate(to_convert, 1):
        dest = source.with_suffix(".mp4")
        print(f"[{i}/{len(to_convert)}] {source.name}", end=" ... ", flush=True)

        success, error = convert(source, dest)

        if success:
            source.unlink()  # delete original only after confirmed success
            converted += 1
            print("done")
            log_rows.append({
                "status": "converted",
                "original": source.name,
                "output": dest.name,
                "error": "",
            })
        else:
            # Remove the failed/partial output if it exists
            if dest.exists():
                dest.unlink()
            failed += 1
            print(f"FAILED — {error}")
            log_rows.append({
                "status": "failed",
                "original": source.name,
                "output": "",
                "error": error,
            })

    with open(LOG, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["status", "original", "output", "error"])
        writer.writeheader()
        writer.writerows(log_rows)

    print(f"\nDone. Converted: {converted}  Failed: {failed}")
    if failed:
        print(f"See failed files in: {LOG}")


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    main(execute)
