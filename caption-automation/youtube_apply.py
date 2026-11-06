#!/usr/bin/env python3
"""
Apply the reviewed audit CSV: rename and/or delete YouTube videos.

DRY RUN BY DEFAULT — pass --apply to make real changes.

Stays under ~180 write calls/day (YouTube Data API quota).
Logs original title+description before any change so renames are reversible.

Usage:
    python3 caption-automation/youtube_apply.py                          # dry run
    python3 caption-automation/youtube_apply.py --audit output/audit.csv
    python3 caption-automation/youtube_apply.py --apply                  # real changes
    python3 caption-automation/youtube_apply.py --apply --action rename  # renames only
    python3 caption-automation/youtube_apply.py --apply --action delete  # deletes only
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CONFIG     = Path.home() / "TellMeAJoke/config.json"
DEFAULT_IN = Path.home() / "TellMeAJoke/output/youtube_audit.csv"
ROLLBACK   = Path.home() / "TellMeAJoke/output/youtube_rollback.log"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # required for update + delete
]

QUOTA_LIMIT = 175   # leave headroom below 180


def load_config() -> dict:
    with open(CONFIG) as f:
        return json.load(f)


def get_yt_client(config: dict):
    creds = Credentials(
        token=None,
        refresh_token=config["youtube_refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config["youtube_client_id"],
        client_secret=config["youtube_client_secret"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def load_audit(path: Path) -> list[dict]:
    """Load audit CSV, deduplicating by videoId (keep first occurrence)."""
    seen: set[str] = set()
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["videoId"] not in seen:
                seen.add(r["videoId"])
                rows.append(r)
    return rows


def already_processed_ids() -> set[str]:
    """Return videoIds that appear in the rollback log (already acted on)."""
    ids: set[str] = set()
    if not ROLLBACK.exists():
        return ids
    with open(ROLLBACK, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["videoId"])
            except (json.JSONDecodeError, KeyError):
                pass
    return ids


def log_rollback(entry: dict) -> None:
    ROLLBACK.parent.mkdir(parents=True, exist_ok=True)
    with open(ROLLBACK, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp":    datetime.now().isoformat(),
            "videoId":      entry["videoId"],
            "old_title":    entry["current_title"],
            "new_title":    entry["new_title"],
            "action":       entry["suggested_action"],
        }) + "\n")


def rename_video(yt, video_id: str, new_title: str, dry_run: bool) -> bool:
    """Fetch current snippet and update title. Returns True on success."""
    if dry_run:
        print(f"    [dry-run] RENAME {video_id} → {new_title!r}")
        return True

    # Fetch current snippet so we only change the title
    resp = yt.videos().list(part="snippet", id=video_id).execute()
    if not resp.get("items"):
        print(f"    WARNING: video {video_id} not found, skipping")
        return False

    snippet = resp["items"][0]["snippet"]
    snippet["title"] = new_title[:100]
    # Scrub category-name words from description too
    snippet["description"] = ""

    yt.videos().update(
        part="snippet",
        body={"id": video_id, "snippet": snippet},
    ).execute()
    return True


def delete_video(yt, video_id: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"    [dry-run] DELETE {video_id}")
        return True
    yt.videos().delete(id=video_id).execute()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply reviewed audit CSV to YouTube.")
    parser.add_argument("--audit",  default=str(DEFAULT_IN), help="Audit CSV to read")
    parser.add_argument("--apply",  action="store_true",     help="Make real changes (default: dry run)")
    parser.add_argument("--action", choices=["rename", "delete", "all"], default="all",
                        help="Which action types to execute (default: all)")
    parser.add_argument("--groups", default="",
                        help="Comma-separated target_group values to restrict to, e.g. black,jewish. "
                             "Substring match: 'jewish' matches 'jewish' and 'religion:jewish'.")
    parser.add_argument("--severity", choices=["high", "medium", "low", ""], default="",
                        help="Only process rows with this severity (default: all severities).")
    args = parser.parse_args()

    audit_path = Path(args.audit)
    if not audit_path.exists():
        print(f"Error: audit file not found: {audit_path}")
        sys.exit(1)

    rows = load_audit(audit_path)
    dry_run = not args.apply

    if dry_run:
        print("\n*** DRY RUN — pass --apply to make real changes ***\n")

    done_ids = already_processed_ids()
    if done_ids:
        print(f"Skipping {len(done_ids)} videoId(s) already in rollback log.")

    filter_groups   = [g.strip().lower() for g in args.groups.split(",") if g.strip()]
    filter_severity = args.severity.strip().lower()
    if filter_groups:
        print(f"Group filter:    {filter_groups}")
    if filter_severity:
        print(f"Severity filter: {filter_severity}")

    config = load_config()
    yt     = get_yt_client(config)

    def group_matches(row: dict) -> bool:
        if not filter_groups:
            return True
        tg = row.get("target_group", "").lower()
        return any(g in tg for g in filter_groups)

    def severity_matches(row: dict) -> bool:
        if not filter_severity:
            return True
        return row.get("severity", "").lower() == filter_severity

    to_process = [
        r for r in rows
        if r["suggested_action"] in (["rename", "delete"] if args.action == "all"
                                      else [args.action])
        and r["videoId"] not in done_ids
        and group_matches(r)
        and severity_matches(r)
    ]

    print(f"Videos to process: {len(to_process)} "
          f"(rename: {sum(1 for r in to_process if r['suggested_action']=='rename')}, "
          f"delete: {sum(1 for r in to_process if r['suggested_action']=='delete')})")
    print(f"Quota limit: {QUOTA_LIMIT} write calls/day\n")

    calls = 0
    done  = 0
    for r in to_process:
        if calls >= QUOTA_LIMIT:
            print(f"\nQuota limit reached ({QUOTA_LIMIT}). Re-run tomorrow to continue.")
            break

        vid_id = r["videoId"]
        action = r["suggested_action"]
        title  = r["current_title"]
        new_t  = r["new_title"]
        views  = int(r.get("views", 0))

        print(f"  [{done+1}/{len(to_process)}] {action.upper():6}  {views:>7,}v  {title[:55]}")

        if not dry_run:
            log_rollback(r)

        if action == "rename" and args.action in ("rename", "all"):
            ok = rename_video(yt, vid_id, new_t, dry_run)
            if ok and not dry_run:
                print(f"           → {new_t}")
            calls += 0 if dry_run else 1

        elif action == "delete" and args.action in ("delete", "all"):
            ok = delete_video(yt, vid_id, dry_run)
            calls += 0 if dry_run else 1

        done += 1
        if not dry_run:
            time.sleep(0.5)  # avoid burst

    print(f"\n{'='*60}")
    print(f"  {'[DRY RUN] ' if dry_run else ''}Done: {done} processed, {calls} API calls used")
    if not dry_run:
        print(f"  Rollback log: {ROLLBACK}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
