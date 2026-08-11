#!/usr/bin/env python3
"""
Post a video to Instagram as a Reel using Meta's Resumable Upload API.

No external hosting required — the video is uploaded directly to Meta's servers.

Usage:
    python3 caption-automation/instagram.py "Frank tells mexican joke.mp4"
    python3 caption-automation/instagram.py "Frank tells mexican joke.mp4" --check-token
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
CAPTIONS_DIR   = Path.home() / "TellMeAJoke/output/captions"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"
POST_LOG       = Path.home() / "TellMeAJoke/output/post_log.txt"
API            = "https://graph.facebook.com/v19.0"
POLL_INTERVAL  = 5


def load_config() -> dict:
    if not CONFIG.exists():
        print("config.json not found.")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


def check_token(token: str) -> None:
    r = requests.get(f"{API}/me", params={"access_token": token})
    data = r.json()
    if "error" in data:
        print(f"Token error: {data['error']['message']}")
        sys.exit(1)
    print(f"Token valid. Name: {data.get('name', '?')}")


def initialize_upload(ig_user_id: str, caption: str, token: str) -> tuple[str, str]:
    """Create a resumable upload session. Returns (container_id, upload_uri)."""
    print("Initializing upload session...")
    data = {
        "media_type":    "REELS",
        "upload_type":   "resumable",
        "caption":       caption,
        "share_to_feed": "true",
    }
    r = requests.post(
        f"{API}/{ig_user_id}/media",
        params={"access_token": token},
        data=data,
    )
    if not r.ok:
        print(f"Init error {r.status_code}: {r.text}")
        r.raise_for_status()
    data = r.json()
    container_id = data.get("id")
    upload_uri   = data.get("uri")
    if not container_id or not upload_uri:
        print(f"Unexpected response: {data}")
        sys.exit(1)
    print(f"  Container ID : {container_id}")
    return container_id, upload_uri


def upload_video(video_path: Path, upload_uri: str, token: str) -> None:
    """Upload the video bytes to the resumable upload URI."""
    file_size = video_path.stat().st_size
    print(f"Uploading video ({file_size / 1_000_000:.1f} MB)...")
    with open(video_path, "rb") as f:
        r = requests.post(
            upload_uri,
            headers={
                "Authorization": f"OAuth {token}",
                "offset":        "0",
                "file_size":     str(file_size),
            },
            data=f,
        )
    if not r.ok:
        print(f"Upload error {r.status_code}: {r.text}")
        r.raise_for_status()
    print("  Upload complete.")


def wait_for_container(container_id: str, token: str) -> None:
    print("Waiting for Meta to process the video ", end="", flush=True)
    while True:
        r = requests.get(
            f"{API}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
        )
        r.raise_for_status()
        data   = r.json()
        status = data.get("status_code", "")
        if status == "FINISHED":
            print(" ready.")
            return
        if status == "ERROR":
            print(f"\nContainer processing failed: {data}")
            sys.exit(1)
        print(".", end="", flush=True)
        time.sleep(POLL_INTERVAL)


def publish_container(ig_user_id: str, container_id: str, token: str) -> str:
    print("Publishing Reel...")
    r = requests.post(
        f"{API}/{ig_user_id}/media_publish",
        params={"access_token": token},
        data={"creation_id": container_id},
    )
    if not r.ok:
        print(f"Publish error {r.status_code}: {r.text}")
        r.raise_for_status()
    post_id = r.json().get("id")
    print(f"  Post ID: {post_id}")
    return post_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Post a clip to Instagram as a Reel.")
    parser.add_argument("clip",          help="Original clip filename, e.g. 'Frank tells mexican joke.mp4'")
    parser.add_argument("--check-token",   action="store_true", help="Validate token and exit")
    args = parser.parse_args()

    config = load_config()
    token  = config.get("instagram_access_token", "")
    ig_id  = config.get("instagram_user_id", "")

    if not token or not ig_id:
        print("Error: instagram_access_token and instagram_user_id must be set in config.json")
        sys.exit(1)

    if args.check_token:
        check_token(token)
        return

    stem     = Path(args.clip).stem
    video    = READY / f"{stem}_final.mp4"
    cap_file = CAPTIONS_DIR / f"{stem}_caption.txt"

    if not video.exists():
        print(f"Error: video not found:\n  {video}\nRun post_pipeline.py first.")
        sys.exit(1)
    if not cap_file.exists():
        print(f"Error: caption file not found:\n  {cap_file}\nRun post_pipeline.py first.")
        sys.exit(1)

    caption = cap_file.read_text().strip()

    print(f"\nClip    : {args.clip}")
    print(f"Video   : {video.name}")
    print(f"Caption : {caption[:80]}{'…' if len(caption) > 80 else ''}\n")

    container_id, upload_uri = initialize_upload(ig_id, caption, token)
    upload_video(video, upload_uri, token)
    wait_for_container(container_id, token)
    post_id = publish_container(ig_id, container_id, token)

    # Append to post log
    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(POST_LOG, "a") as log:
        log.write(f"{datetime.now().isoformat()} | {stem} | instagram | post_id={post_id}\n")

    print(f"\nPosted! Post ID: {post_id}")


if __name__ == "__main__":
    main()
