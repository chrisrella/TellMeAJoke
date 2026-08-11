#!/usr/bin/env python3
"""
Post queued videos from output/ready_to_post/ to Instagram and Facebook.

By default posts the next single video (oldest first) — designed for cron.
Use --all or --limit N to post multiple in one run.

Usage:
    python3 caption-automation/poster.py              # post next in queue
    python3 caption-automation/poster.py --all        # post everything in the queue
    python3 caption-automation/poster.py --limit 3    # post next 3
    python3 caption-automation/poster.py --list       # show what's queued
    python3 caption-automation/poster.py --dry-run    # show what would post without posting
    python3 caption-automation/poster.py --instagram-only
    python3 caption-automation/poster.py --facebook-only
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS        = Path(__file__).parent
READY          = Path.home() / "TellMeAJoke/output/ready_to_post"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"


def queued_videos() -> list[Path]:
    """Return ready_to_post videos sorted oldest-first, excluding already-posted ones."""
    if not READY.exists():
        return []
    posted_names = {p.name for p in ALREADY_POSTED.glob("*_final.mp4")} if ALREADY_POSTED.exists() else set()
    videos = [
        p for p in sorted(READY.glob("*_final.mp4"), key=lambda f: f.stat().st_mtime)
        if p.name not in posted_names
    ]
    return videos


def clip_arg(video_path: Path) -> str:
    """Convert 'Frank tells mexican joke_final.mp4' → 'Frank tells mexican joke.mp4'."""
    stem = video_path.stem          # "Frank tells mexican joke_final"
    name = stem.removesuffix("_final")  # "Frank tells mexican joke"
    return f"{name}.mp4"


def post_to(script: str, clip_name: str) -> bool:
    """Run a posting script and return True on success."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), clip_name],
        text=True,
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Post next queued video to all platforms.")
    parser.add_argument("--list",           action="store_true", help="List queued videos and exit")
    parser.add_argument("--dry-run",        action="store_true", help="Show what would be posted without posting")
    parser.add_argument("--all",            action="store_true", help="Post all queued videos")
    parser.add_argument("--limit",          type=int, default=None, metavar="N", help="Post next N videos")
    parser.add_argument("--instagram-only", action="store_true", help="Post to Instagram only")
    parser.add_argument("--facebook-only",  action="store_true", help="Post to Facebook only")
    parser.add_argument("--youtube-only",   action="store_true", help="Post to YouTube only")
    parser.add_argument("--no-youtube",     action="store_true", help="Skip YouTube")
    parser.add_argument("--tiktok",         action="store_true", help="Also post to TikTok (requires approved app + token)")
    args = parser.parse_args()

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

    platforms = []
    if not args.facebook_only and not args.youtube_only:
        platforms.append("instagram.py")
    if not args.instagram_only and not args.youtube_only:
        platforms.append("facebook.py")
    if not args.no_youtube and not args.instagram_only and not args.facebook_only:
        platforms.append("youtube.py")
    if args.tiktok:
        platforms.append("tiktok.py")

    if args.all:
        to_post = queue
    elif args.limit:
        to_post = queue[: args.limit]
    else:
        to_post = queue[:1]

    print(f"Posting {len(to_post)} video(s) to {', '.join(p.replace('.py','') for p in platforms)}\n")

    if args.dry_run:
        for v in to_post:
            print(f"[dry-run] Would post: {clip_arg(v)}")
        return

    failed = []
    for i, video in enumerate(to_post, 1):
        clip_name = clip_arg(video)
        print(f"\n{'='*60}")
        print(f"  [{i}/{len(to_post)}]  {clip_name}")
        print(f"{'='*60}")
        clip_failed = []
        for script in platforms:
            ok = post_to(script, clip_name)
            if not ok:
                clip_failed.append(script.replace(".py", ""))

        # Archive regardless of platform success so the video is never re-queued
        ALREADY_POSTED.mkdir(parents=True, exist_ok=True)
        stem     = video.stem.removesuffix("_final")
        cap_file = Path.home() / f"TellMeAJoke/output/captions/{stem}_caption.txt"
        if video.exists():
            video.rename(ALREADY_POSTED / video.name)
        if cap_file.exists():
            cap_file.rename(ALREADY_POSTED / cap_file.name)

        if clip_failed:
            failed.append(f"{clip_name} ({', '.join(clip_failed)})")

    print(f"\n{'='*60}")
    print(f"  Done: {len(to_post) - len(failed)}/{len(to_post)} succeeded")
    if failed:
        print(f"  Failed:")
        for f in failed:
            print(f"    - {f}")
    print(f"{'='*60}\n")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
