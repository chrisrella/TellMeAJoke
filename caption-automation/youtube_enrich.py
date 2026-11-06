#!/usr/bin/env python3
"""
Enrich transcripts.csv to cover no_transcript_match YouTube videos.

Phase 1 (--transcribe): fuzzy-match YouTube titles → master files,
                         run faster-whisper on those missing transcripts.
Phase 2 (--captions):   pull YouTube caption tracks for videos with no master match.
                         Videos with absolutely no captions get a [no_captions] sentinel
                         so the audit puts them in the uncertain tier.
--all:                   run both phases in order.
--dry-run:               print what would happen, write nothing.

After running, re-run youtube_audit.py to get updated tier counts.
"""

import argparse
import csv
import difflib
import io
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

MASTER      = Path.home() / "TellMeAJoke/content/master"
TRANSCRIPTS = Path.home() / "TellMeAJoke/content/transcripts.csv"
AUDIT_CSV   = Path.home() / "TellMeAJoke/output/youtube_audit.csv"
CONFIG      = Path.home() / "TellMeAJoke/config.json"
ENRICH_LOG  = Path.home() / "TellMeAJoke/output/enrich.log"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# Sentinel written when a video has zero caption tracks
NO_CAPTIONS_SENTINEL = "[no_captions_available]"


# ── normalisation ─────────────────────────────────────────────────────────────

def norm(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"\.(mp4|mov|avi|mkv|m4v)$", "", t, flags=re.I)
    # Strip joke rating suffixes: jokeR  joke13  joke PG
    t = re.sub(r"(joke)\s*(r|pg|x|\d+)(_topjokes)?$", r"\1", t)
    # Strip trailing standalone rating/number
    t = re.sub(r"\s+(r|pg|x|\d+)\s*$", "", t)
    # Normalise separators and whitespace
    t = re.sub(r"[_\-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ── data loaders ──────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG) as f:
        return json.load(f)


def load_existing_transcripts() -> dict[str, str]:
    """Return {filename_stem: transcript_text}."""
    out = {}
    if not TRANSCRIPTS.exists():
        return out
    with open(TRANSCRIPTS, newline="") as f:
        for row in csv.reader(f):
            if len(row) > 2 and row[2].strip():
                out[Path(row[0]).stem] = row[2].strip()
    return out


def load_audit_no_match() -> list[dict]:
    """Return unique no_transcript_match rows from the audit CSV."""
    seen: set[str] = set()
    rows = []
    with open(AUDIT_CSV, newline="") as f:
        for r in csv.DictReader(f):
            if r["risk_tier"] == "no_transcript_match" and r["videoId"] not in seen:
                seen.add(r["videoId"])
                rows.append(r)
    return rows


def master_stems() -> dict[str, Path]:
    """Return {norm_stem: file_path} for all files in content/master."""
    out = {}
    for p in MASTER.iterdir():
        if p.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".m4v"):
            out[norm(p.stem)] = p
    return out


# ── fuzzy match ───────────────────────────────────────────────────────────────

def find_master_file(youtube_title: str, master: dict[str, Path],
                     cutoff: float = 0.80) -> Path | None:
    key = norm(youtube_title)
    if key in master:
        return master[key]
    hits = difflib.get_close_matches(key, master.keys(), n=1, cutoff=cutoff)
    return master[hits[0]] if hits else None


# ── faster-whisper transcription ──────────────────────────────────────────────

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        # int8 on CPU is the fastest option on Apple Silicon without Metal support
        _whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")
        print("  Whisper model loaded (medium / int8 / CPU)")
    return _whisper_model


def transcribe(video_path: Path) -> str:
    model = get_whisper_model()
    segs, _ = model.transcribe(str(video_path), beam_size=5)
    return " ".join(s.text.strip() for s in segs).strip()


# ── YouTube captions ──────────────────────────────────────────────────────────

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


def _parse_vtt(vtt: str) -> str:
    """Strip VTT timing lines and tags, return plain text."""
    out = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or re.match(r"^\d+$", line):
            continue
        if re.match(r"^\d{2}:\d{2}", line):  # timestamp
            continue
        line = re.sub(r"<[^>]+>", "", line)   # remove tags
        if line:
            out.append(line)
    return " ".join(out)


def fetch_captions(yt, video_id: str) -> str | None:
    """
    Try to download the best available English caption track for a video.
    Returns plain text, or None if no tracks exist, or NO_CAPTIONS_SENTINEL
    if the API confirms there are truly no captions.
    """
    try:
        resp = yt.captions().list(part="snippet", videoId=video_id).execute()
    except Exception as e:
        print(f"    captions.list failed for {video_id}: {e}")
        return None

    items = resp.get("items", [])
    if not items:
        return NO_CAPTIONS_SENTINEL

    # Prefer manually uploaded English tracks; fall back to auto-generated
    best = None
    for item in items:
        lang = item["snippet"]["language"]
        track_kind = item["snippet"].get("trackKind", "")
        if lang.startswith("en"):
            if track_kind != "asr":   # manual first
                best = item
                break
            if best is None:
                best = item
    if best is None:
        best = items[0]

    cap_id = best["id"]
    try:
        req = yt.captions().download(id=cap_id, tfmt="vtt")
        fh  = io.BytesIO()
        dl  = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return _parse_vtt(fh.getvalue().decode("utf-8"))
    except Exception as e:
        print(f"    captions.download failed for {video_id}: {e}")
        return None


# ── transcript CSV writer ─────────────────────────────────────────────────────

def append_transcript(filename: str, text: str, dry_run: bool) -> None:
    if dry_run:
        return
    with open(TRANSCRIPTS, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([filename, "good", text, datetime.now().isoformat()])


def log(msg: str) -> None:
    ENRICH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ENRICH_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")


# ── phases ────────────────────────────────────────────────────────────────────

def phase1_transcribe(dry_run: bool) -> None:
    print("\n── Phase 1: transcribe unmatched master files ───────────────────────────")
    rows   = load_audit_no_match()
    master = master_stems()
    existing = load_existing_transcripts()

    to_transcribe = []
    no_master     = []

    for row in rows:
        path = find_master_file(row["current_title"], master)
        if path is None:
            no_master.append(row)
            continue
        if path.stem in existing:
            continue   # already has a transcript
        to_transcribe.append((row, path))

    print(f"  Videos with master file, no transcript : {len(to_transcribe)}")
    print(f"  Videos with no master file match       : {len(no_master)}")
    print()

    if not to_transcribe:
        print("  Nothing to transcribe.")
        return

    done = skipped = failed = 0
    for i, (row, path) in enumerate(to_transcribe, 1):
        print(f"  [{i}/{len(to_transcribe)}] {path.name[:60]}")
        try:
            if not dry_run:
                text = transcribe(path)
                if not text.strip():
                    print(f"    empty transcript — skipping")
                    skipped += 1
                    continue
                append_transcript(path.name, text, dry_run=False)
                log(f"TRANSCRIBED {path.name}")
            else:
                text = "[dry-run]"
            print(f"    → {text[:80]}{'…' if len(text) > 80 else ''}")
            done += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            log(f"ERROR {path.name}: {e}")
            failed += 1

    print(f"\n  Done: {done} transcribed, {skipped} empty, {failed} failed")
    if dry_run:
        print("  [dry-run] pass --transcribe (without --dry-run) to write")


def phase2_captions(dry_run: bool) -> None:
    print("\n── Phase 2: pull YouTube captions for unmatched videos ──────────────────")
    rows   = load_audit_no_match()
    master = master_stems()

    # Only operate on videos with no master file
    no_master = [r for r in rows if find_master_file(r["current_title"], master) is None]
    print(f"  Videos with no master file match: {len(no_master)}")

    if not no_master:
        print("  Nothing to fetch.")
        return

    config = load_config()
    try:
        yt = get_yt_client(config)
    except Exception as e:
        print(f"  YouTube auth failed: {e}")
        print("  Re-run python3 caption-automation/youtube_auth.py to refresh the token.")
        return

    no_caps = fetched = failed = 0

    for i, row in enumerate(no_master, 1):
        vid   = row["videoId"]
        title = row["current_title"]
        print(f"  [{i}/{len(no_master)}] {title[:60]}")

        text = fetch_captions(yt, vid)
        time.sleep(0.5)

        if text is None:
            print(f"    API error — skipping")
            failed += 1
            continue
        elif text == NO_CAPTIONS_SENTINEL:
            print(f"    no captions → sentinel")
            if not dry_run:
                # Use title as synthetic filename so audit can find it
                append_transcript(f"{title}.mp4", NO_CAPTIONS_SENTINEL, dry_run=False)
                log(f"NO_CAPTIONS {vid} | {title}")
            no_caps += 1
        else:
            preview = text[:80].replace("\n", " ")
            print(f"    → {preview}{'…' if len(text) > 80 else ''}")
            if not dry_run:
                append_transcript(f"{title}.mp4", text, dry_run=False)
                log(f"CAPTIONS {vid} | {title}")
            fetched += 1

    print(f"\n  Done: {fetched} captions fetched, {no_caps} no-caption sentinels written, {failed} API errors")
    if dry_run:
        print("  [dry-run] pass --captions (without --dry-run) to write")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich transcripts for unmatched YouTube videos.")
    parser.add_argument("--transcribe", action="store_true", help="Phase 1: faster-whisper on master files")
    parser.add_argument("--captions",   action="store_true", help="Phase 2: pull YouTube caption tracks")
    parser.add_argument("--all",        action="store_true", help="Run both phases")
    parser.add_argument("--dry-run",    action="store_true", help="Print what would happen, write nothing")
    args = parser.parse_args()

    if not any([args.transcribe, args.captions, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.transcribe or args.all:
        phase1_transcribe(dry_run=args.dry_run)

    if args.captions or args.all:
        phase2_captions(dry_run=args.dry_run)

    print("\nNext step: python3 caption-automation/youtube_audit.py")


if __name__ == "__main__":
    main()
