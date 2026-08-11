#!/usr/bin/env python3
"""
Upload a video to TikTok using the Content Posting API.

Reads credentials from config.json (set up once with tiktok_auth.py).
Videos are found in ready_to_post/ or already_posted/ (Instagram archives first).

Usage:
    python3 caption-automation/tiktok.py "Frank tells mexican joke.mp4"
    python3 caption-automation/tiktok.py "clip.mp4" --private   # self-only, useful for testing
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

CONFIG         = Path.home() / "TellMeAJoke/config.json"
READY          = Path.home() / "TellMeAJoke/output/ready_to_post"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"
CAPTIONS_DIR   = Path.home() / "TellMeAJoke/output/captions"
POST_LOG       = Path.home() / "TellMeAJoke/output/post_log.txt"

API           = "https://open.tiktokapis.com/v2"
POLL_INTERVAL = 5
MAX_CHUNK     = 64 * 1024 * 1024  # 64 MB — TikTok's max chunk size


def load_config() -> dict:
    if not CONFIG.exists():
        print("config.json not found.")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


def auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json; charset=UTF-8",
    }


def find_video(stem: str) -> Path:
    filename = f"{stem}_final.mp4"
    for directory in (READY, ALREADY_POSTED):
        candidate = directory / filename
        if candidate.exists():
            return candidate
    print(f"Error: {filename} not found in ready_to_post/ or already_posted/")
    print("Run post_pipeline.py first.")
    sys.exit(1)


def find_caption(stem: str) -> str:
    for directory in (CAPTIONS_DIR, ALREADY_POSTED):
        candidate = directory / f"{stem}_caption.txt"
        if candidate.exists():
            return candidate.read_text().strip()
    return ""


def init_upload(token: str, video_size: int, title: str, privacy: str) -> tuple[str, str, int, int]:
    """Initialize the upload session. Returns (publish_id, upload_url, chunk_size, chunk_count)."""
    chunk_size  = min(video_size, MAX_CHUNK)
    chunk_count = (video_size + chunk_size - 1) // chunk_size

    print("Initializing TikTok upload...")
    r = requests.post(
        f"{API}/post/publish/video/init/",
        headers=auth_headers(token),
        json={
            "post_info": {
                "title":           title[:150],
                "privacy_level":   privacy,
                "disable_duet":    False,
                "disable_comment": False,
                "disable_stitch":  False,
            },
            "source_info": {
                "source":            "FILE_UPLOAD",
                "video_size":        video_size,
                "chunk_size":        chunk_size,
                "total_chunk_count": chunk_count,
            },
        },
    )
    data = r.json()
    if data.get("error", {}).get("code") != "ok":
        print(f"Init failed: {data}")
        sys.exit(1)
    publish_id = data["data"]["publish_id"]
    upload_url = data["data"]["upload_url"]
    print(f"  Publish ID : {publish_id}")
    return publish_id, upload_url, chunk_size, chunk_count


def upload_chunks(video_path: Path, upload_url: str, chunk_size: int, total_chunks: int) -> None:
    video_size = video_path.stat().st_size
    print(f"Uploading {video_path.name} ({video_size / 1_000_000:.1f} MB)...")

    with open(video_path, "rb") as f:
        for i in range(total_chunks):
            chunk = f.read(chunk_size)
            start = i * chunk_size
            end   = start + len(chunk) - 1
            r = requests.put(
                upload_url,
                headers={
                    "Content-Type":   "video/mp4",
                    "Content-Range":  f"bytes {start}-{end}/{video_size}",
                    "Content-Length": str(len(chunk)),
                },
                data=chunk,
            )
            if r.status_code not in (200, 201, 206):
                print(f"Chunk {i + 1} upload failed {r.status_code}: {r.text}")
                sys.exit(1)
            pct = int((i + 1) / total_chunks * 100)
            print(f"  Uploading... {pct}%", end="\r")

    print("  Upload complete.          ")


def wait_for_publish(token: str, publish_id: str) -> None:
    print("Waiting for TikTok to process ", end="", flush=True)
    while True:
        r = requests.post(
            f"{API}/post/publish/status/fetch/",
            headers=auth_headers(token),
            json={"publish_id": publish_id},
        )
        data   = r.json()
        status = data.get("data", {}).get("status", "")
        if status == "PUBLISH_COMPLETE":
            print(" done.")
            return
        if status == "FAILED":
            reason = data.get("data", {}).get("fail_reason", "unknown")
            print(f"\nPublish failed: {reason}")
            print(f"Full response: {data}")
            sys.exit(1)
        print(".", end="", flush=True)
        time.sleep(POLL_INTERVAL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a clip to TikTok.")
    parser.add_argument("clip",      help="Original clip filename, e.g. 'Frank tells mexican joke.mp4'")
    parser.add_argument("--private", action="store_true",
                        help="Post as self-only (useful for testing before going public)")
    args = parser.parse_args()

    config = load_config()
    token  = config.get("tiktok_access_token", "")

    if not token:
        print("Error: tiktok_access_token not found in config.json")
        print("Run: python3 caption-automation/tiktok_auth.py")
        sys.exit(1)

    privacy = "SELF_ONLY" if args.private else "PUBLIC_TO_EVERYONE"
    stem    = Path(args.clip).stem
    video   = find_video(stem)
    caption = find_caption(stem)
    title   = caption or stem.replace("_", " ")

    print(f"\nClip    : {args.clip}")
    print(f"Video   : {video}")
    print(f"Title   : {title[:80]}{'…' if len(title) > 80 else ''}")
    print(f"Privacy : {privacy}\n")

    video_size = video.stat().st_size
    publish_id, upload_url, chunk_size, chunk_count = init_upload(
        token, video_size, title, privacy
    )
    upload_chunks(video, upload_url, chunk_size, chunk_count)
    wait_for_publish(token, publish_id)

    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(POST_LOG, "a") as log:
        log.write(f"{datetime.now().isoformat()} | {stem} | tiktok | publish_id={publish_id}\n")

    print(f"\nPosted to TikTok! Publish ID: {publish_id}")


if __name__ == "__main__":
    main()
