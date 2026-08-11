#!/usr/bin/env python3
"""
Post a video to a Facebook Page as a Reel.

Uses the same long-lived token from config.json (instagram_access_token) —
it's a user token, and we exchange it for a Page token automatically via /me/accounts.

Looks for the video in ready_to_post/ first, then already_posted/ (in case
instagram.py already archived it in the same poster.py run).

Usage:
    python3 caption-automation/facebook.py "Frank tells mexican joke.mp4"
    python3 caption-automation/facebook.py "Frank tells mexican joke.mp4" --check-token
"""

import argparse
import json
import sys
from pathlib import Path

import requests

CONFIG         = Path.home() / "TellMeAJoke/config.json"
READY          = Path.home() / "TellMeAJoke/output/ready_to_post"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"
CAPTIONS_DIR   = Path.home() / "TellMeAJoke/output/captions"
POST_LOG       = Path.home() / "TellMeAJoke/output/post_log.txt"
API            = "https://graph.facebook.com/v19.0"
POLL_INTERVAL  = 5


def load_config() -> dict:
    if not CONFIG.exists():
        print("config.json not found.")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


def find_video(stem: str) -> Path:
    """Find the final video in ready_to_post/ or already_posted/."""
    filename = f"{stem}_final.mp4"
    for directory in (READY, ALREADY_POSTED):
        candidate = directory / filename
        if candidate.exists():
            return candidate
    print(f"Error: {filename} not found in ready_to_post/ or already_posted/")
    print("Run post_pipeline.py first.")
    sys.exit(1)


def find_caption(stem: str) -> str:
    """Read caption from captions/ or already_posted/."""
    for directory in (CAPTIONS_DIR, ALREADY_POSTED):
        candidate = directory / f"{stem}_caption.txt"
        if candidate.exists():
            return candidate.read_text().strip()
    return ""


def start_upload(page_id: str, token: str) -> tuple[str, str]:
    """Phase 1: initialize the upload session. Returns (video_id, upload_url)."""
    print("Initializing Facebook Reel upload...")
    r = requests.post(
        f"{API}/{page_id}/video_reels",
        params={"access_token": token},
        data={"upload_phase": "start"},
    )
    if not r.ok:
        print(f"Start error {r.status_code}: {r.text}")
        r.raise_for_status()
    data = r.json()
    video_id   = data.get("video_id")
    upload_url = data.get("upload_url")
    if not video_id or not upload_url:
        print(f"Unexpected response: {data}")
        sys.exit(1)
    print(f"  Video ID  : {video_id}")
    return video_id, upload_url


def upload_video(video_path: Path, upload_url: str, token: str) -> None:
    """Phase 2: upload the video bytes."""
    file_size = video_path.stat().st_size
    print(f"Uploading video ({file_size / 1_000_000:.1f} MB)...")
    with open(video_path, "rb") as f:
        r = requests.post(
            upload_url,
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


def finish_upload(page_id: str, video_id: str, caption: str,
                  title: str, token: str) -> None:
    """Phase 3: publish the Reel."""
    print("Publishing Facebook Reel...")
    r = requests.post(
        f"{API}/{page_id}/video_reels",
        params={"access_token": token},
        data={
            "upload_phase": "finish",
            "video_id":     video_id,
            "video_state":  "PUBLISHED",
            "description":  caption,
            "title":        title[:255],
        },
    )
    if not r.ok:
        print(f"Finish error {r.status_code}: {r.text}")
        r.raise_for_status()
    print(f"  Published (video_id: {video_id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Post a clip to a Facebook Page as a Reel.")
    parser.add_argument("clip",          help="Original clip filename, e.g. 'Frank tells mexican joke.mp4'")
    parser.add_argument("--check-token",   action="store_true", help="Validate token and exit")
    args = parser.parse_args()

    config  = load_config()
    token   = config.get("facebook_page_token", "")
    page_id = config.get("facebook_page_id", "")

    if not token or not page_id:
        print("Error: instagram_access_token and facebook_page_id must be set in config.json")
        sys.exit(1)

    if args.check_token:
        r = requests.get(f"{API}/{page_id}", params={"fields": "name,id", "access_token": token})
        data = r.json()
        if "error" in data:
            print(f"Token error: {data['error']['message']}")
            sys.exit(1)
        print(f"Page token valid. Page: {data.get('name')} (id: {data.get('id')})")
        return

    stem    = Path(args.clip).stem
    video   = find_video(stem)
    caption = find_caption(stem)
    title   = stem[:255]

    print(f"\nClip    : {args.clip}")
    print(f"Video   : {video}")
    print(f"Caption : {caption[:80]}{'…' if len(caption) > 80 else ''}\n")

    video_id, upload_url = start_upload(page_id, token)
    upload_video(video, upload_url, token)
    finish_upload(page_id, video_id, caption, title, token)

    # Append to post log
    from datetime import datetime
    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(POST_LOG, "a") as log:
        log.write(f"{datetime.now().isoformat()} | {stem} | facebook | video_id={video_id}\n")

    print(f"\nPosted to Facebook! Video ID: {video_id}\n")


if __name__ == "__main__":
    main()
