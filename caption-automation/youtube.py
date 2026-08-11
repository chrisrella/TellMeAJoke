#!/usr/bin/env python3
"""
Upload a video to YouTube as a Short.

Videos already in 9:16 format under 60s are automatically treated as Shorts.
Reads credentials from config.json (set up once with youtube_auth.py).

Usage:
    python3 caption-automation/youtube.py "Frank tells mexican joke.mp4"
    python3 caption-automation/youtube.py "clip.mp4" --check-token
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

CONFIG         = Path.home() / "TellMeAJoke/config.json"
READY          = Path.home() / "TellMeAJoke/output/ready_to_post"
ALREADY_POSTED = Path.home() / "TellMeAJoke/output/already_posted"
CAPTIONS_DIR   = Path.home() / "TellMeAJoke/output/captions"
POST_LOG       = Path.home() / "TellMeAJoke/output/post_log.txt"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def load_config() -> dict:
    if not CONFIG.exists():
        print("config.json not found.")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


def get_credentials(config: dict) -> Credentials:
    required = ("youtube_client_id", "youtube_client_secret", "youtube_refresh_token")
    if not all(config.get(k) for k in required):
        print("YouTube credentials not found in config.json.")
        print("Run: python3 caption-automation/youtube_auth.py")
        sys.exit(1)

    creds = Credentials(
        token=None,
        refresh_token=config["youtube_refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config["youtube_client_id"],
        client_secret=config["youtube_client_secret"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


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


def upload_video(youtube, video_path: Path, title: str, description: str) -> str:
    """Upload video and return the YouTube video ID."""
    print(f"Uploading {video_path.name} ({video_path.stat().st_size / 1_000_000:.1f} MB)...")

    body = {
        "snippet": {
            "title":       title[:100],
            "description": description,
            "tags":        ["shorts", "comedy", "jokes", "funny"],
            "categoryId":  "23",  # Comedy
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Uploading... {pct}%", end="\r")

    print(f"  Upload complete.          ")
    return response["id"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a clip to YouTube as a Short.")
    parser.add_argument("clip",          help="Original clip filename")
    parser.add_argument("--check-token", action="store_true", help="Validate credentials and exit")
    args = parser.parse_args()

    config = load_config()
    creds  = get_credentials(config)

    if args.check_token:
        print("Credentials valid. Token refreshed successfully.")
        return

    youtube = build("youtube", "v3", credentials=creds)

    stem        = Path(args.clip).stem
    video       = find_video(stem)
    caption_txt = find_caption(stem)

    title       = stem.replace("_", " ")
    description = f"{caption_txt}\n\n#Shorts" if caption_txt else "#Shorts"

    print(f"\nClip    : {args.clip}")
    print(f"Video   : {video}")
    print(f"Title   : {title[:60]}")
    print(f"Caption : {caption_txt[:80]}{'…' if len(caption_txt) > 80 else ''}\n")

    video_id = upload_video(youtube, video, title, description)

    print(f"Published! https://youtube.com/shorts/{video_id}")

    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(POST_LOG, "a") as log:
        log.write(f"{datetime.now().isoformat()} | {stem} | youtube | video_id={video_id}\n")


if __name__ == "__main__":
    main()
