#!/usr/bin/env python3

#TOOL FOR CLI (command line) REVIEW
#will watch each video sequentially and record a quality rating + character flag
#helps me comb through the content quickly, and keep progress saved
#Themes like relationship, food, animal, etc. will be added using AI after captioning
#Usage: python3 review.py

import csv
import subprocess
from datetime import datetime
from pathlib import Path

MASTER      = Path.home() / "TellMeAJoke/content/master"
RATINGS_CSV = Path.home() / "TellMeAJoke/content/ratings.csv"
EXTENSIONS  = {".mp4", ".mov"}

RATING_LABELS = {"f": "funny", "c": "clips only", "s": "skip", "i": "intro"}


# ── CSV helpers ──────────────────────────────────────────────────────────────

def load_existing_ratings() -> set[str]:
    """Return set of filenames already rated."""
    if not RATINGS_CSV.exists():
        return set()
    with open(RATINGS_CSV, newline="") as f:
        return {row["filename"] for row in csv.DictReader(f)}


def append_rating(filename: str, rating: str, character: bool) -> None:
    write_header = not RATINGS_CSV.exists()
    with open(RATINGS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "rating", "character", "rated_at"])
        if write_header:
            writer.writeheader()
        writer.writerow({
            "filename":  filename,
            "rating":    rating,
            "character": "y" if character else "n",
            "rated_at":  datetime.now().isoformat(timespec="seconds"),
        })


# ── Player helpers ───────────────────────────────────────────────────────────

def close_quicktime() -> None:
    subprocess.run(
        ["osascript", "-e", "tell application \"QuickTime Player\" to close every document"],
        capture_output=True,
    )


def open_video(path: Path) -> None:
    """Open video in ffplay with loudnorm so every video plays at consistent volume."""
    close_quicktime()
    subprocess.Popen(
        ["ffplay", "-af", "volume=3", "-autoexit", str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def play_boosted(path: Path) -> None:
    """Extra-loud replay for still-quiet videos (4x on top of loudnorm)."""
    print("  Playing boosted audio (press Q in the ffplay window to stop)...")
    subprocess.run(
        ["ffplay", "-af", "volume=6", "-autoexit", str(path)],
        capture_output=True,
    )


# ── Input helpers ────────────────────────────────────────────────────────────

def ask_rating() -> str | None:
    """Prompt for rating. Returns None if user wants to quit."""
    while True:
        raw = input("  Rate:  f = funny   c = clips only   s = skip   i = intro   r = replay   b = boost volume   q = quit\n  > ").strip().lower()
        if raw in ("f", "c", "s", "i", "r", "b", "q"):
            return raw
        print("  Please enter f, c, s, i, r, b, or q.")


def ask_character() -> bool:
    while True:
        raw = input("  Character? y/n  (animated, noteworthy delivery)\n  > ").strip().lower()
        if raw in ("y", "n"):
            return raw == "y"
        print("  Please enter y or n.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    all_videos   = sorted(f for f in MASTER.iterdir() if f.suffix.lower() in EXTENSIONS)
    already_done = load_existing_ratings()
    queue        = [v for v in all_videos if v.name not in already_done]
    total        = len(all_videos)
    remaining    = len(queue)
    done_count   = total - remaining

    print(f"\nTMAJ Review Tool")
    print(f"  Total videos : {total}")
    print(f"  Already rated: {done_count}")
    print(f"  Remaining    : {remaining}")
    print(f"  Ratings file : {RATINGS_CSV}\n")

    if not queue:
        print("All videos have been rated!")
        return

    for i, video in enumerate(queue, start=done_count + 1):
        print(f"\n{'─' * 50}")
        print(f"[{i}/{total}]  {video.name}")

        open_video(video)

        while True:
            rating = ask_rating()

            if rating == "q":
                close_quicktime()
                print(f"\nProgress saved. {i - 1} rated this session.")
                return

            if rating == "r":
                open_video(video)
                continue

            if rating == "b":
                play_boosted(video)
                continue

            # Valid rating — ask character
            character = ask_character()
            append_rating(video.name, rating, character)

            label = RATING_LABELS[rating]
            char_label = "character ★" if character else ""
            print(f"  Saved: {label}  {char_label}")
            break

    close_quicktime()
    print(f"\nAll {total} videos reviewed!")


if __name__ == "__main__":
    main()
