#!/usr/bin/env python3
"""
Post queued videos from output/ready_to_post/ to Instagram, Facebook, and YouTube.

By default posts the next single video (oldest first) — designed for cron.
Per-platform results (ok / failed / skipped) are written to output/post_log.csv.

Usage:
    python3 caption-automation/poster.py              # post next in queue (IG+FB+YT)
    python3 caption-automation/poster.py --all        # post everything in the queue
    python3 caption-automation/poster.py --limit 3    # post next 3
    python3 caption-automation/poster.py --list       # show what's queued
    python3 caption-automation/poster.py --dry-run    # show what would post without posting
    python3 caption-automation/poster.py --no-youtube # skip YouTube (strike active)
    python3 caption-automation/poster.py --retry-youtube  # post clips that missed YouTube
    python3 caption-automation/poster.py --instagram-only
    python3 caption-automation/poster.py --facebook-only
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS        = Path(__file__).parent
READY          = Path.home() / "TellMeAJoke/output/ready_to_post"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"
CONFIG         = Path.home() / "TellMeAJoke/config.json"
TRANSCRIPTS    = Path.home() / "TellMeAJoke/content/transcripts.csv"
POST_LOG_CSV   = Path.home() / "TellMeAJoke/output/post_log.csv"
MOD_LOG        = Path.home() / "TellMeAJoke/output/moderation_blocked.log"

ALL_STANDARD_PLATFORMS = ["instagram", "facebook", "youtube"]



# ── logging ──────────────────────────────────────────────────────────────────

def log_platform_result(stem: str, platform: str, result: str) -> None:
    """Append one row to post_log.csv. result is 'ok', 'failed', or 'skipped'."""
    POST_LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not POST_LOG_CSV.exists()
    with open(POST_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "stem", "platform", "result"])
        writer.writerow([datetime.now().isoformat(), stem, platform, result])


# ── queue ─────────────────────────────────────────────────────────────────────

def queued_videos() -> list[Path]:
    """Return ready_to_post videos sorted oldest-first, excluding already-posted ones."""
    if not READY.exists():
        return []
    posted_names = {p.name for p in ALREADY_POSTED.glob("*_final.mp4")} if ALREADY_POSTED.exists() else set()
    return [
        p for p in sorted(READY.glob("*_final.mp4"), key=lambda f: f.stat().st_mtime)
        if p.name not in posted_names
    ]


def clip_arg(video_path: Path) -> str:
    """Convert 'Frank tells mexican joke_final.mp4' → 'Frank tells mexican joke.mp4'."""
    return video_path.stem.removesuffix("_final") + ".mp4"


def post_to(script: str, clip_name: str) -> bool:
    """Run a posting script and return True on success."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), clip_name],
        text=True,
    )
    return result.returncode == 0


# ── moderation screen (shared module) ────────────────────────────────────────

from moderation import moderation_screen


def load_openai_key() -> str:
    try:
        with open(CONFIG) as f:
            return json.load(f).get("openai_api_key", "")
    except Exception:
        return ""


def get_transcript(clip_name: str) -> str | None:
    if not TRANSCRIPTS.exists():
        return None
    with open(TRANSCRIPTS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and Path(row[0]).name == clip_name and len(row) > 2:
                return row[2].strip() or None
    return None


def log_blocked(stem: str, reason: str) -> None:
    MOD_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(MOD_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | BLOCKED | {stem} | {reason}\n")


# ── retry-youtube ─────────────────────────────────────────────────────────────

def stems_needing_youtube() -> list[str]:
    """Read post_log.csv and return stems where YouTube was skipped or failed."""
    if not POST_LOG_CSV.exists():
        return []
    ok_stems: set[str] = set()
    all_stems: set[str] = set()
    with open(POST_LOG_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            all_stems.add(row["stem"])
            if row["platform"] == "youtube" and row["result"] == "ok":
                ok_stems.add(row["stem"])
    # Also include stems that never appear in the CSV with a youtube row at all
    missing = set()
    with open(POST_LOG_CSV, newline="", encoding="utf-8") as f:
        yt_stems = {row["stem"] for row in csv.DictReader(f) if row["platform"] == "youtube"}
    missing = all_stems - yt_stems
    return sorted((all_stems - ok_stems) | missing)


def run_retry_youtube() -> None:
    api_key = load_openai_key()
    stems   = stems_needing_youtube()
    if not stems:
        print("No clips with missing/failed YouTube posts found in post_log.csv.")
        return

    print(f"\n{len(stems)} clip(s) never successfully posted to YouTube:\n")
    passed = failed = blocked = 0

    for stem in stems:
        video_name = f"{stem}_final.mp4"
        video      = ALREADY_POSTED / video_name
        if not video.exists():
            print(f"  [not found] {stem}")
            continue

        clip_name  = f"{stem}.mp4"
        transcript = get_transcript(clip_name)

        # Moderation screen
        if api_key and transcript:
            is_blocked, reason = moderation_screen(stem, transcript, api_key)
            time.sleep(0.3)
            if is_blocked:
                print(f"  ⛔ BLOCKED  {stem[:55]}")
                print(f"        {reason}")
                log_blocked(stem, reason)
                log_platform_result(stem, "youtube", "blocked")
                blocked += 1
                continue
        elif not transcript:
            print(f"  [no transcript — skipping] {stem}")
            continue

        # Post to YouTube (youtube.py reads from ALREADY_POSTED too)
        print(f"  Posting: {stem[:55]}")
        ok = post_to("youtube.py", clip_name)
        result = "ok" if ok else "failed"
        log_platform_result(stem, "youtube", result)
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n  Retry complete: {passed} posted, {blocked} blocked, {failed} failed")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Post next queued video to all platforms.")
    parser.add_argument("--list",           action="store_true")
    parser.add_argument("--dry-run",        action="store_true")
    parser.add_argument("--all",            action="store_true")
    parser.add_argument("--limit",          type=int, default=None, metavar="N")
    parser.add_argument("--instagram-only", action="store_true")
    parser.add_argument("--facebook-only",  action="store_true")
    parser.add_argument("--youtube-only",   action="store_true")
    parser.add_argument("--no-youtube",     action="store_true", help="Skip YouTube (strike active until Jan 25 2027)")
    parser.add_argument("--tiktok",         action="store_true")
    parser.add_argument("--retry-youtube",  action="store_true",
                        help="Upload clips that previously missed YouTube (screens each first)")
    args = parser.parse_args()

    if args.retry_youtube:
        run_retry_youtube()
        return

    queue = queued_videos()

    if args.list:
        if not queue:
            print("Queue is empty.")
        else:
            print(f"{len(queue)} video(s) queued:\n")
            for i, v in enumerate(queue, 1):
                print(f"  {i}. {v.name}")
        return

    if not queue:
        print("Queue is empty — nothing to post.")
        sys.exit(0)

    # Build active and skipped platform sets
    active = []
    if not args.facebook_only and not args.youtube_only:
        active.append("instagram")
    if not args.instagram_only and not args.youtube_only:
        active.append("facebook")
    if not args.no_youtube and not args.instagram_only and not args.facebook_only:
        active.append("youtube")
    if args.tiktok:
        active.append("tiktok")

    skipped_platforms = [p for p in ALL_STANDARD_PLATFORMS if p not in active]

    if args.all:
        to_post = queue
    elif args.limit:
        to_post = queue[: args.limit]
    else:
        to_post = queue[:1]

    print(f"Posting {len(to_post)} video(s) to {', '.join(active)}")
    if skipped_platforms:
        print(f"Skipping: {', '.join(skipped_platforms)}")
    print()

    if args.dry_run:
        for v in to_post:
            print(f"[dry-run] Would post: {clip_arg(v)}")
        return

    run_failed = []
    for i, video in enumerate(to_post, 1):
        clip_name = clip_arg(video)
        stem      = video.stem.removesuffix("_final")

        print(f"\n{'='*60}")
        print(f"  [{i}/{len(to_post)}]  {clip_name}")
        print(f"{'='*60}")

        clip_failed = []
        for platform in active:
            ok = post_to(f"{platform}.py", clip_name)
            log_platform_result(stem, platform, "ok" if ok else "failed")
            if not ok:
                clip_failed.append(platform)

        for platform in skipped_platforms:
            log_platform_result(stem, platform, "skipped")

        # Archive regardless of platform success so video is never re-queued
        ALREADY_POSTED.mkdir(parents=True, exist_ok=True)
        cap_file    = Path.home() / f"TellMeAJoke/output/captions/{stem}_caption.txt"
        yt_title_f  = Path.home() / f"TellMeAJoke/output/captions/{stem}_yt_title.txt"
        if video.exists():
            video.rename(ALREADY_POSTED / video.name)
        if cap_file.exists():
            cap_file.rename(ALREADY_POSTED / cap_file.name)
        if yt_title_f.exists():
            yt_title_f.rename(ALREADY_POSTED / yt_title_f.name)

        if clip_failed:
            run_failed.append(f"{clip_name} ({', '.join(clip_failed)})")

    print(f"\n{'='*60}")
    print(f"  Done: {len(to_post) - len(run_failed)}/{len(to_post)} succeeded")
    if run_failed:
        print(f"  Failed:")
        for f in run_failed:
            print(f"    - {f}")
    print(f"{'='*60}\n")

    if run_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
