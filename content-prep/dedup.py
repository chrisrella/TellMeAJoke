#!/usr/bin/env python3
"""
TMAJ video deduplication script.

Groups all video files by base name across every subfolder, keeps the
best-quality format, and copies winners to a master/ output folder.

Usage:
    python3 dedup.py            # dry run — prints plan, copies nothing
    python3 dedup.py --execute  # actually copies files and writes the log
"""

import sys
import csv
import shutil
from pathlib import Path
from collections import defaultdict

SOURCE = Path.home() / "Library/CloudStorage/OneDrive-Personal/TMAJ"
#my computer's files held in a folder TellMeAJoke
DEST   = Path.home() / "TellMeAJoke/content/master"
LOG    = Path.home() / "TellMeAJoke/content/dedup_log.csv"

#lower index = higher priority
#prefer mp4 > mov > ...etc
FORMAT_PRIORITY = [".mp4", ".mov", ".wmv", ".flv", ".mpg", ".mpeg"]
VIDEO_EXTENSIONS = set(FORMAT_PRIORITY)


def format_rank(path: Path) -> int:
    ext = path.suffix.lower()
    try:
        return FORMAT_PRIORITY.index(ext)
    except ValueError:
        return len(FORMAT_PRIORITY)


def find_videos(root: Path) -> list[Path]:
    return [
        f for f in root.rglob("*")
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ]


def group_by_base(files: list[Path]) -> dict[str, list[Path]]:
    """Group files by their stem (name without extension), case-insensitive."""
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        groups[f.stem.lower()].append(f)
    return groups


def pick_best(files: list[Path]) -> tuple[Path, list[Path]]:
    """Return (winner, list_of_skipped) for a group of files with the same base name."""
    ranked = sorted(files, key=format_rank)
    return ranked[0], ranked[1:]


def main(execute: bool) -> None:
    if not SOURCE.exists():
        print(f"ERROR: Source folder not found: {SOURCE}")
        sys.exit(1)

    print(f"Scanning: {SOURCE}")
    all_videos = find_videos(SOURCE)
    print(f"Found {len(all_videos)} video files\n")

    groups = group_by_base(all_videos)

    winners: list[Path] = []
    skipped: list[tuple[Path, Path, str]] = []  # (file, kept_instead, reason)

    for base, files in sorted(groups.items()):
        best, dupes = pick_best(files)
        winners.append(best)
        for d in dupes:
            reason = "same base name, lower-priority format" if d.suffix.lower() != best.suffix.lower() else "same base name and format in different folder"
            skipped.append((d, best, reason))

    print(f"Files to copy : {len(winners)}")
    print(f"Files skipped : {len(skipped)}")
    print(f"Output folder : {DEST}\n")

    if not execute:
        print("=== DRY RUN — nothing copied ===")
        print("First 20 winners:")
        for w in winners[:20]:
            rel = w.relative_to(SOURCE)
            print(f"  COPY  {rel}")
        if skipped:
            print("\nFirst 20 skipped:")
            for f, kept, reason in skipped[:20]:
                print(f"  SKIP  {f.relative_to(SOURCE)}")
                print(f"        reason : {reason}")
                print(f"        kept   : {kept.relative_to(SOURCE)}")
        print("\nRun with --execute to perform the copy and write the log.")
        return

    # --- Execute ---
    DEST.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)

    copied = 0
    errors = 0
    log_rows: list[dict] = []

    for w in winners:
        dest_file = DEST / w.name
        # Handle rare name collision in destination (different base, same filename)
        if dest_file.exists():
            dest_file = DEST / f"{w.stem}__{w.parent.name}{w.suffix}"
        try:
            shutil.copy2(w, dest_file)
            copied += 1
            log_rows.append({
                "action": "COPIED",
                "source": str(w.relative_to(SOURCE)),
                "destination": str(dest_file.relative_to(DEST)),
                "reason": "",
                "kept_instead": "",
            })
        except Exception as e:
            errors += 1
            print(f"ERROR copying {w}: {e}")

    for f, kept, reason in skipped:
        log_rows.append({
            "action": "SKIPPED",
            "source": str(f.relative_to(SOURCE)),
            "destination": "",
            "reason": reason,
            "kept_instead": str(kept.relative_to(SOURCE)),
        })

    with open(LOG, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["action", "source", "destination", "reason", "kept_instead"])
        writer.writeheader()
        writer.writerows(log_rows)

    print(f"Done. Copied {copied} files, {errors} errors.")
    print(f"Log written to: {LOG}")


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    main(execute)
