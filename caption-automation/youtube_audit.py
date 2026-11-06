#!/usr/bin/env python3
"""
Read-only audit of the YouTube channel.

Fetches every uploaded video, flags risky titles/transcripts, and writes
a CSV for manual review. Does NOT modify any YouTube content.

Usage:
    python3 caption-automation/youtube_audit.py
    python3 caption-automation/youtube_audit.py --out output/audit.csv
    python3 caption-automation/youtube_audit.py --no-gpt   # skip OpenAI calls
"""

import argparse
import csv
import difflib
import json
import re
import time
from pathlib import Path

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CONFIG       = Path.home() / "TellMeAJoke/config.json"
TRANSCRIPTS  = Path.home() / "TellMeAJoke/content/transcripts.csv"
DEFAULT_OUT  = Path.home() / "TellMeAJoke/output/youtube_audit.csv"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# Keywords to flag in title or description
FLAG_WORDS = [
    "ethnic", "gay", "retarded", "black", "jewish", "mexican",
    "italian", "polish", "old lady", "gasp",
]

from moderation import first_match, CONFIDENCE_THRESHOLD

# Protected categories for GPT prompt
PROTECTED_CATEGORIES = (
    "race, ethnicity, nationality, religion, sexual orientation, "
    "gender identity, disability, or age"
)

RISK_ORDER = {
    "audio_targets_group":       0,
    "blonde":                    1,  # uncle decides separately
    "title_or_description_only": 2,
    "uncertain":                 3,  # garbled/low-confidence — needs human review
    "no_transcript_match":       4,
    "clean":                     5,
}

ACTION_MAP = {
    "audio_targets_group":       "delete",
    "blonde":                    "review",
    "title_or_description_only": "rename",
    "uncertain":                 "review",
    "no_transcript_match":       "review",
    "clean":                     "keep",
}

# Word-boundary pattern for blonde (not in moderation.py BLOCK_WORDS — audit only)
_BLONDE_PATTERN = re.compile(r"\bblondes?\b", re.IGNORECASE)

# Manually confirmed clean videos overriding GPT/tag verdicts
MANUAL_OVERRIDES = {
    "eo5iY4_sLFE": {   # "John tells a genie jokeR" — pianist wordplay, not demographic targeting
        "tier": "clean",
        "gpt_result": {"targeted": False, "confidence": 1.0,
                       "new_title": "John tells a genie jokeR",
                       "reason": "manual_override: pianist wordplay joke, not targeting a group",
                       "bleep_candidate": False},
    },
}


# ── helpers ──────────────────────────────────────────────────────────────────

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


NO_CAPTIONS_SENTINEL = "[no_captions_available]"


def _norm(text: str) -> str:
    """Normalise a filename stem or YouTube title for fuzzy matching."""
    t = text.lower().strip()
    t = re.sub(r"\.(mp4|mov|avi|mkv|m4v)$", "", t, flags=re.I)
    t = re.sub(r"(joke)\s*(r|pg|x|\d+)(_topjokes)?$", r"\1", t)
    t = re.sub(r"\s+(r|pg|x|\d+)\s*$", "", t)
    t = re.sub(r"[_\-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def load_transcripts() -> dict[str, str]:
    """Return {normalised_key: transcript_text}. Includes sentinel entries."""
    mapping = {}
    if not TRANSCRIPTS.exists():
        return mapping
    with open(TRANSCRIPTS, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 3 or not row[2].strip():
                continue
            key = _norm(Path(row[0]).stem)
            mapping[key] = row[2].strip()
    return mapping


def match_transcript(title: str, transcripts: dict[str, str]) -> str | None:
    """Return transcript text for a YouTube title, or None if not found."""
    key = _norm(title)
    if key in transcripts:
        return transcripts[key]
    hits = difflib.get_close_matches(key, transcripts.keys(), n=1, cutoff=0.80)
    return transcripts[hits[0]] if hits else None


def keyword_flags(title: str, description: str) -> list[str]:
    combined = (title + " " + description).lower()
    return [w for w in FLAG_WORDS if w in combined]


def gpt_analyse(transcript: str, title: str, config: dict) -> dict:
    """
    Ask GPT: is a protected group targeted? Returns:
      {targeted: bool, confidence: float, new_title: str, reason: str}
    """
    api_key = config.get("openai_api_key", "")
    if not api_key:
        return {"targeted": False, "confidence": 1.0, "new_title": title, "reason": "no OpenAI key"}

    prompt = f"""You are reviewing a short joke video for YouTube Community Guidelines compliance.

Title: {title}
Transcript: {transcript}

Answer these five things in JSON:
1. "targeted": true if a protected group ({PROTECTED_CATEGORIES}) is the PRIMARY TARGET of the joke's punchline (the group is mocked or demeaned). false if a group is merely mentioned, or is the narrator/protagonist but not mocked.
2. "confidence": float 0.0-1.0. Set BELOW 0.7 if the transcript is garbled, too short, mostly filler words, or the verdict is genuinely ambiguous. Set 0.9+ only when unambiguous.
3. "new_title": a short YouTube title (5-8 words) describing the joke's comic premise without naming any demographic group, and with no rating suffix (no R, PG, 13, X). E.g. "Genie With Bad Hearing" or "Man at Cash Register Sees Everything".
4. "reason": one sentence explaining your targeted verdict.
5. "bleep_candidate": true if the problem is limited to one or two specific slur/group words that could be bleeped (and the punchline would still land after bleeping), false if the whole premise or punchline is built around targeting a group.

Respond with valid JSON only, no markdown."""

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model":       "gpt-4o-mini",
                    "messages":    [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens":  300,
                },
                timeout=60,
            )
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return json.loads(text)
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)   # 1 s, then 2 s
                continue
            return {"targeted": False, "confidence": 0.5, "new_title": title,
                    "reason": f"gpt_error (retries exhausted): {e}", "bleep_candidate": False}


def all_channel_videos(yt) -> list[dict]:
    """Return all uploaded videos with snippet + statistics."""
    # Get uploads playlist ID
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Paginate through playlist items
    video_ids = []
    page_token = None
    while True:
        kwargs = dict(playlistId=uploads_id, part="snippet", maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = yt.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            vid_id = item["snippet"]["resourceId"]["videoId"]
            video_ids.append(vid_id)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    print(f"  Found {len(video_ids)} uploaded videos — fetching details...")

    # Fetch details in batches of 50
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        resp  = yt.videos().list(
            part="snippet,statistics", id=",".join(batch)
        ).execute()
        videos.extend(resp.get("items", []))

    return videos


# ── main ─────────────────────────────────────────────────────────────────────

def load_videos_from_csv(path: Path) -> list[dict]:
    """
    Re-use video metadata from an existing audit CSV instead of hitting the
    YouTube API. Deduplicates by videoId and reconstructs the snippet/stats
    shape that the main loop expects.
    """
    seen: set[str] = set()
    videos = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vid = r["videoId"]
            if vid in seen:
                continue
            seen.add(vid)
            videos.append({
                "id": vid,
                "snippet": {
                    "title":       r["current_title"],
                    "description": "",   # not stored in CSV; keyword_flags re-runs on title only
                },
                "statistics": {"viewCount": r.get("views", "0")},
            })
    return videos


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only YouTube channel audit.")
    parser.add_argument("--out",      default=str(DEFAULT_OUT), help="Output CSV path")
    parser.add_argument("--no-gpt",   action="store_true",      help="Skip GPT transcript analysis")
    parser.add_argument("--from-csv", metavar="CSV",            help="Re-use video list from an existing audit CSV (skips YouTube API fetch; useful when quota is exhausted)")
    args = parser.parse_args()

    config      = load_config()
    transcripts = load_transcripts()

    print(f"Loaded {len(transcripts)} transcripts from CSV")

    if args.from_csv:
        src = Path(args.from_csv)
        print(f"Loading video list from {src} (skipping YouTube API)…")
        videos = load_videos_from_csv(src)
    else:
        yt         = get_yt_client(config)
        print("Fetching channel videos…")
        videos_raw = all_channel_videos(yt)

        # Deduplicate by videoId — the uploads playlist can return the same video
        # multiple times across paginated results.
        seen: set[str] = set()
        videos = []
        for v in videos_raw:
            vid = v["id"]
            if vid not in seen:
                seen.add(vid)
                videos.append(v)
        if len(videos_raw) != len(videos):
            print(f"  Deduplicated {len(videos_raw)} → {len(videos)} unique videos")

    print(f"Analysing {len(videos)} videos...")

    FIELDNAMES = ["videoId", "current_title", "views", "keyword_flags",
                  "risk_tier", "suggested_action", "new_title", "reason", "bleep_candidate", "yt_url"]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".tmp.csv")

    # Write rows incrementally to a temp file; final pass sorts and renames.
    tmp_f   = open(tmp_path, "w", newline="", encoding="utf-8")
    tmp_w   = csv.DictWriter(tmp_f, fieldnames=FIELDNAMES)
    tmp_w.writeheader()

    rows = []
    for i, v in enumerate(videos, 1):
        vid_id      = v["id"]
        snippet     = v["snippet"]
        stats       = v.get("statistics", {})
        title       = snippet.get("title", "")
        description = snippet.get("description", "")
        views       = int(stats.get("viewCount", 0))

        flags       = keyword_flags(title, description)
        transcript  = match_transcript(title, transcripts)

        # Default
        risk_tier   = "no_transcript_match"
        gpt_result  = {"targeted": False, "confidence": 1.0, "new_title": title,
                       "reason": "no transcript", "bleep_candidate": False}

        # Manual overrides: confirmed false positives
        if vid_id in MANUAL_OVERRIDES:
            ov = MANUAL_OVERRIDES[vid_id]
            risk_tier  = ov["tier"]
            gpt_result = ov["gpt_result"]

        # Videos where captions.download confirmed no captions exist → uncertain
        elif transcript == NO_CAPTIONS_SENTINEL:
            risk_tier  = "uncertain"
            gpt_result = {"targeted": False, "confidence": 0.0, "new_title": title,
                          "reason": "no captions or transcript available", "bleep_candidate": False}

        # Blonde title → own tier (uncle decides separately)
        elif _BLONDE_PATTERN.search(title):
            risk_tier = "blonde"
            if transcript and not args.no_gpt:
                gpt_result = gpt_analyse(transcript, title, config)
                time.sleep(0.3)
            else:
                gpt_result = {"targeted": False, "confidence": 1.0, "new_title": title,
                              "reason": "blonde joke — uncle to decide", "bleep_candidate": False}

        # Title contains a block word — verify with GPT if transcript available
        elif (tag := first_match(title)):
            if transcript and not args.no_gpt:
                gpt_result = gpt_analyse(transcript, title, config)
                confidence = float(gpt_result.get("confidence", 1.0))
                if gpt_result.get("targeted"):
                    risk_tier = "audio_targets_group"
                elif confidence < CONFIDENCE_THRESHOLD:
                    risk_tier = "uncertain"
                    gpt_result["reason"] = f"uncertain_block: confidence={confidence:.2f} — {gpt_result.get('reason', '')}"
                else:
                    # Tag word in title but content doesn't target a group → rename only
                    risk_tier = "title_or_description_only"
                    gpt_result["reason"] = f"title_tag '{tag}' but content ok: {gpt_result.get('reason', '')}"
                time.sleep(0.3)
            else:
                # No transcript to verify — assume worst
                risk_tier  = "audio_targets_group"
                gpt_result = {"targeted": True, "confidence": 0.7, "new_title": title,
                              "reason": f"tag_block: '{tag}' in title (no transcript to verify)",
                              "bleep_candidate": False}

        elif transcript and not args.no_gpt:
            gpt_result = gpt_analyse(transcript, title, config)
            confidence = float(gpt_result.get("confidence", 1.0))
            if gpt_result.get("targeted"):
                risk_tier = "audio_targets_group"
            elif confidence < CONFIDENCE_THRESHOLD:
                risk_tier = "uncertain"
                gpt_result["reason"] = f"uncertain_block: confidence={confidence:.2f} — {gpt_result.get('reason', '')}"
            elif flags:
                risk_tier = "title_or_description_only"
            else:
                risk_tier = "clean"
            time.sleep(0.3)  # gentle rate limit
        elif transcript and args.no_gpt:
            risk_tier = "title_or_description_only" if flags else "clean"
        elif not transcript and flags:
            risk_tier = "title_or_description_only"

        new_title = gpt_result.get("new_title", title)
        reason    = gpt_result.get("reason", "")

        bleep = "yes" if gpt_result.get("bleep_candidate") else "no"
        row = {
            "videoId":          vid_id,
            "current_title":    title,
            "views":            views,
            "keyword_flags":    "|".join(flags),
            "risk_tier":        risk_tier,
            "suggested_action": ACTION_MAP.get(risk_tier, "review"),
            "new_title":        new_title,
            "reason":           reason,
            "bleep_candidate":  bleep,
            "yt_url":           f"https://youtube.com/shorts/{vid_id}",
        }
        rows.append(row)
        tmp_w.writerow(row)
        tmp_f.flush()

        if i % 10 == 0:
            print(f"  {i}/{len(videos)}...")

    tmp_f.close()

    # Sort: risk tier first (most dangerous first), then views descending
    rows.sort(key=lambda r: (RISK_ORDER.get(r["risk_tier"], 99), -r["views"]))

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.unlink(missing_ok=True)  # clean up temp file on success

    # Summary
    by_tier = {}
    for r in rows:
        by_tier[r["risk_tier"]] = by_tier.get(r["risk_tier"], 0) + 1

    print(f"\n{'='*60}")
    print(f"  Audit complete — {len(rows)} videos")
    print(f"{'='*60}")
    for tier in sorted(RISK_ORDER, key=RISK_ORDER.get):
        count = by_tier.get(tier, 0)
        if count:
            print(f"  {tier:<30} {count:>4}")
    print(f"\n  Output: {out_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
