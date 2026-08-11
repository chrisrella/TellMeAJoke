#!/usr/bin/env python3
"""
Bulk-process all approved clips through the pipeline (A→B→D→C→E) without posting.

Skips clips that already have a final video in ready_to_post/ or already_posted/.
After this runs, all processed clips sit in output/ready_to_post/ ready for the
scheduled poster to pick up.

Usage:
    python3 caption-automation/batch.py               # process all unprocessed approved clips
    python3 caption-automation/batch.py --list        # show what would be processed
    python3 caption-automation/batch.py --auto        # skip ZapCap review for each clip
    python3 caption-automation/batch.py --limit 3     # process at most 3 clips this run
"""

import argparse
import csv
import random
import subprocess
import sys
from pathlib import Path

SCRIPTS        = Path(__file__).parent
MASTER         = Path.home() / "TellMeAJoke/content/master"
TRANSCRIPTS    = Path.home() / "TellMeAJoke/content/transcripts.csv"
READY          = Path.home() / "TellMeAJoke/output/ready_to_post"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"

APPROVED_RATINGS = {"good", "funny", "approved"}


def approved_clips() -> list[tuple[str, str]]:
    """Return [(filename, rating), ...] for all approved clips in transcripts.csv."""
    clips = []
    if not TRANSCRIPTS.exists():
        return clips
    with open(TRANSCRIPTS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and len(row) > 1 and row[1].strip().lower() in APPROVED_RATINGS:
                clips.append((Path(row[0]).name, row[1].strip().lower()))
    return clips


def already_processed(clip_name: str) -> bool:
    stem = Path(clip_name).stem
    final = f"{stem}_final.mp4"
    return (
        (READY.exists()          and (READY          / final).exists()) or
        (ALREADY_POSTED.exists() and (ALREADY_POSTED / final).exists())
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk pipeline (A→E) for all approved clips.")
    parser.add_argument("--list",  action="store_true", help="Show pending clips and exit")
    parser.add_argument("--auto",  action="store_true", help="Skip ZapCap review (--auto flag)")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Stop after processing N clips")
    args = parser.parse_args()

    all_approved = approved_clips()
    pending      = [(n, r) for n, r in all_approved if not already_processed(n)]
    random.shuffle(pending)

    if args.list:
        print(f"\n{len(all_approved)} approved clips total, {len(pending)} not yet processed:\n")
        for name, rating in pending:
            print(f"  [{rating}] {name}")
        print()
        return

    if not pending:
        print("Nothing to process — all approved clips already have final videos.")
        return

    to_process = pending[: args.limit] if args.limit else pending
    skipped    = len(pending) - len(to_process)

    print(f"\nProcessing {len(to_process)} clip(s)"
          + (f"  ({skipped} more will remain after --limit)" if skipped else "")
          + "\n")

    failed = []
    for i, (clip_name, rating) in enumerate(to_process, 1):
        print(f"\n{'='*60}")
        print(f"  [{i}/{len(to_process)}]  {clip_name}  (rating: {rating})")
        print(f"{'='*60}")

        cmd = [
            sys.executable, str(SCRIPTS / "post_pipeline.py"),
            clip_name,
            "--no-filter",   # rating already verified above
        ]
        if args.auto:
            cmd.append("--auto")

        result = subprocess.run(cmd, text=True)
        if result.returncode != 0:
            print(f"\n  ✗ Failed: {clip_name}")
            failed.append(clip_name)

    print(f"\n{'='*60}")
    print(f"  Batch complete: {len(to_process) - len(failed)}/{len(to_process)} succeeded")
    if failed:
        print(f"  Failed ({len(failed)}):")
        for f in failed:
            print(f"    - {f}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
