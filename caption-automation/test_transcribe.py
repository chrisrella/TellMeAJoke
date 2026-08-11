#!/usr/bin/env python3
"""
Tests Whisper transcription on a sample of videos to judge quality before
committing to bulk captioning the full library.

Usage:
    # Transcribe specific files (recommended — pick your hardest ones):
    python3 test_transcribe.py "adam copy.mp4" "TellMeAJoke (23).mov"

    # Or transcribe N random videos from master/:
    python3 test_transcribe.py --random 10

    # Use a more accurate model (slower, bigger download):
    python3 test_transcribe.py --model medium --random 10

Models (downloads on first use):
    tiny   ~75MB   fastest, roughest
    base   ~145MB  decent for clean audio
    small  ~460MB  recommended for noisy street audio  ← default
    medium ~1.5GB  best for difficult audio
"""

import sys
import random
import csv
from pathlib import Path
from datetime import datetime

MASTER     = Path.home() / "TellMeAJoke/content/master"
OUTPUT_DIR = Path.home() / "TellMeAJoke/caption-automation/test-results"
EXTENSIONS = {".mp4", ".mov"}


def parse_args():
    args = sys.argv[1:]
    model = "small"
    random_n = None
    files = []

    i = 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] == "--random" and i + 1 < len(args):
            random_n = int(args[i + 1])
            i += 2
        else:
            files.append(args[i])
            i += 1

    return model, random_n, files


def pick_files(random_n: int | None, named: list[str]) -> list[Path]:
    if named:
        paths = []
        for name in named:
            p = MASTER / name
            if not p.exists():
                print(f"WARNING: {name} not found in master/, skipping")
            else:
                paths.append(p)
        return paths

    all_videos = [f for f in MASTER.iterdir() if f.suffix.lower() in EXTENSIONS]
    n = random_n or 10
    return random.sample(all_videos, min(n, len(all_videos)))


def main():
    model_name, random_n, named_files = parse_args()
    files = pick_files(random_n, named_files)

    if not files:
        print("No files to transcribe. Pass filenames or use --random N.")
        sys.exit(1)

    print(f"Loading Whisper model: {model_name}  (downloads on first use)")
    import whisper
    model = whisper.load_model(model_name)
    print(f"Model ready. Transcribing {len(files)} video(s)...\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for i, video in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {video.name}")
        print(f"  Transcribing...", end=" ", flush=True)

        result = model.transcribe(str(video), language="en", verbose=False)
        text = result["text"].strip()

        # Rough quality signal: avg log-prob (higher = more confident)
        avg_logprob = sum(s["avg_logprob"] for s in result["segments"]) / len(result["segments"]) if result["segments"] else -999
        quality = "good" if avg_logprob > -0.5 else "uncertain" if avg_logprob > -1.0 else "poor"

        print(f"done  [{quality} confidence: {avg_logprob:.2f}]")
        print(f"  TRANSCRIPT: {text}\n")

        results.append({
            "filename":    video.name,
            "quality":     quality,
            "avg_logprob": round(avg_logprob, 3),
            "transcript":  text,
        })

    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"test_{model_name}_{timestamp}.csv"
    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "quality", "avg_logprob", "transcript"])
        writer.writeheader()
        writer.writerows(results)

    good      = sum(1 for r in results if r["quality"] == "good")
    uncertain = sum(1 for r in results if r["quality"] == "uncertain")
    poor      = sum(1 for r in results if r["quality"] == "poor")

    print("─" * 50)
    print(f"Results: {good} good  {uncertain} uncertain  {poor} poor")
    print(f"Saved to: {out_file}")


if __name__ == "__main__":
    main()
