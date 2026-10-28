#!/usr/bin/env python3
"""
Show view counts for all posted YouTube videos and monetization status.

Usage:
    python3 caption-automation/youtube_stats.py
"""

import json
import re
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CONFIG   = Path.home() / "TellMeAJoke/config.json"
POST_LOG = Path.home() / "TellMeAJoke/output/post_log.txt"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

YPP_SUBS  = 500   # YouTube Partner Program threshold (Shorts channel)
YPP_VIEWS = 3_000_000  # 3M Shorts views in last 90 days (or 4000 watch-hours for long-form)


def load_config() -> dict:
    with open(CONFIG) as f:
        return json.load(f)


def get_credentials(config: dict) -> Credentials:
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


def get_video_ids_from_log() -> list[tuple[str, str]]:
    """Return list of (video_id, title) from post_log."""
    pairs = []
    seen = set()
    pattern = re.compile(r"^.*?\| (.+?) \| youtube \| video_id=(\S+)")
    for line in POST_LOG.read_text().splitlines():
        m = pattern.match(line)
        if m:
            title, vid_id = m.group(1), m.group(2)
            if vid_id not in seen:
                seen.add(vid_id)
                pairs.append((vid_id, title))
    return pairs


def main() -> None:
    config = load_config()
    creds  = get_credentials(config)
    yt     = build("youtube", "v3", credentials=creds)

    pairs = get_video_ids_from_log()
    if not pairs:
        print("No YouTube videos found in post_log.txt")
        return

    video_ids = [p[0] for p in pairs]
    title_map = {p[0]: p[1] for p in pairs}

    # Fetch stats in batches of 50
    items = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        resp = yt.videos().list(part="snippet,statistics", id=",".join(batch)).execute()
        items.extend(resp.get("items", []))

    def views(item):
        return int(item.get("statistics", {}).get("viewCount", 0))

    items.sort(key=views, reverse=True)

    total_views = sum(views(r) for r in items)
    total_likes = sum(int(r.get("statistics", {}).get("likeCount", 0)) for r in items)

    # Channel-level subscriber count
    ch_resp = yt.channels().list(part="statistics", mine=True).execute()
    ch_stats = ch_resp["items"][0]["statistics"] if ch_resp.get("items") else {}
    subs = int(ch_stats.get("subscriberCount", 0))

    print(f"\n{'='*68}")
    print(f"  CHANNEL SNAPSHOT")
    print(f"{'='*68}")
    print(f"  Subscribers : {subs:,}  (need {YPP_SUBS:,} for YPP)")
    print(f"  Total views : {total_views:,}  across {len(items)} posted videos")
    print(f"  Total likes : {total_likes:,}")
    print()

    # Monetization gap
    sub_pct  = min(subs / YPP_SUBS * 100, 100)
    view_pct = min(total_views / YPP_VIEWS * 100, 100)
    print(f"  YPP progress (Shorts path — 500 subs + 3M Shorts views in 90 days):")
    print(f"    Subscribers : {'#'*int(sub_pct/5):<20} {sub_pct:.1f}%  ({max(YPP_SUBS-subs,0):,} to go)")
    print(f"    Shorts views: {'#'*int(view_pct/5):<20} {view_pct:.1f}%  ({max(YPP_VIEWS-total_views,0):,} to go)")
    print()

    print(f"  {'Views':>8}  {'Likes':>5}  Title")
    print(f"  {'-'*58}")
    for r in items:
        s      = r.get("statistics", {})
        v      = int(s.get("viewCount", 0))
        l      = int(s.get("likeCount", 0))
        vid_id = r["id"]
        title  = title_map.get(vid_id, r["snippet"]["title"])[:44]
        print(f"  {v:>8,}  {l:>5,}  {title}")
        if v > 1000:
            print(f"  {'':>8}  {'':>5}  → https://youtube.com/shorts/{vid_id}")
    print(f"{'='*68}\n")


if __name__ == "__main__":
    main()
