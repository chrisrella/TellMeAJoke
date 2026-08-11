#!/usr/bin/env python3
"""
Bulk transcription script for TMAJ keepers (rated f or c in ratings.csv).
Uses faster-whisper with the medium model for best speed/accuracy balance.

Runs continuously — safe to stop and restart at any time.
Already-transcribed videos are skipped automatically.

Usage:
    python3 transcribe.py           # transcribes all current f/c keepers
    python3 transcribe.py --dry-run # shows what would be transcribed
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

MASTER          = Path.home() / "TellMeAJoke/content/master"
RATINGS_CSV     = Path.home() / "TellMeAJoke/content/ratings.csv"
TRANSCRIPTS_CSV = Path.home() / "TellMeAJoke/content/transcripts.csv"
KEEPER_RATINGS  = {"f", "c"}
MODEL_SIZE      = "medium"


def load_keepers() -> list[str]:
    if not RATINGS_CSV.exists():
        return []
    with open(RATINGS_CSV, newline="") as f:
        return [r["filename"] for r in csv.DictReader(f) if r["rating"] in KEEPER_RATINGS]


def load_transcribed() -> set[str]:
    if not TRANSCRIPTS_CSV.exists():
        return set()
    with open(TRANSCRIPTS_CSV, newline="") as f:
        return {r["filename"] for r in csv.DictReader(f)}


def append_transcript(filename: str, transcript: str, confidence: str) -> None:
    write_header = not TRANSCRIPTS_CSV.exists()
    with open(TRANSCRIPTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "confidence", "transcript", "transcribed_at"])
        if write_header:
            writer.writeheader()
        writer.writerow({
            "filename":       filename,
            "confidence":     confidence,
            "transcript":     transcript,
            "transcribed_at": datetime.now().isoformat(timespec="seconds"),
        })


def main(dry_run: bool) -> None:
    keepers     = load_keepers()
    transcribed = load_transcribed()
    queue       = [f for f in keepers if f not in transcribed]

    print(f"Keepers (f+c)      : {len(keepers)}")
    print(f"Already transcribed: {len(transcribed)}")
    print(f"To transcribe      : {len(queue)}")
    print(f"Transcripts file   : {TRANSCRIPTS_CSV}\n")

    if not queue:
        print("Nothing to transcribe — all keepers are done.")
        return

    if dry_run:
        print("=== DRY RUN ===")
        for f in queue[:20]:
            print(f"  {f}")
        if len(queue) > 20:
            print(f"  ... and {len(queue) - 20} more")
        return

    print(f"Loading faster-whisper model: {MODEL_SIZE}")
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL_SIZE, device="auto", compute_type="auto")
    print("Model ready. Starting transcription...\n")

    done   = 0
    errors = 0

    for i, filename in enumerate(queue, start=len(transcribed) + 1):
        video_path = MASTER / filename
        if not video_path.exists():
            print(f"[{i}] MISSING: {filename}")
            errors += 1
            continue

        print(f"[{i}/{len(keepers)}] {filename}")
        try:
            segments, info = model.transcribe(
                str(video_path),
                language="en",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )

            segment_list  = list(segments)
            transcript    = " ".join(s.text.strip() for s in segment_list).strip()

            if segment_list:
                avg_logprob = sum(s.avg_logprob for s in segment_list) / len(segment_list)
                confidence  = "good" if avg_logprob > -0.5 else "uncertain" if avg_logprob > -1.0 else "poor"
            else:
                confidence = "poor"
                transcript = ""

            print(f"  [{confidence}] {transcript[:120]}{'...' if len(transcript) > 120 else ''}")
            append_transcript(filename, transcript, confidence)
            done += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

    print(f"\nDone. Transcribed: {done}  Errors: {errors}")
    print(f"Results in: {TRANSCRIPTS_CSV}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run)
