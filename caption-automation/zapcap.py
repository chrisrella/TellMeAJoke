#!/usr/bin/env python3
"""
ZapCap captioning integration for TellMeAJoke.

Usage:
    python3 caption-automation/zapcap.py video.mp4           # auto-approve, no review
    python3 caption-automation/zapcap.py video.mp4 --review  # pause for transcript review/edit
    python3 caption-automation/zapcap.py --list-templates

With --review:
  - Transcription completes, words are printed in the terminal
  - Press Enter to approve as-is, or type corrections (e.g. "3:TellMeAJoke 7:correct")
  - Edits are PUT back to ZapCap before rendering
"""

import json
import re
import sys
import time
from pathlib import Path

import requests

CONFIG        = Path.home() / "TellMeAJoke/config.json"
OUTPUT        = Path.home() / "TellMeAJoke/output/captioned"
API_BASE      = "https://api.zapcap.ai"
POLL_INTERVAL = 5


# ── config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG.exists():
        print("config.json not found.")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


def _headers(api_key: str) -> dict:
    return {"x-api-key": api_key}


# ── API ───────────────────────────────────────────────────────────────────────

def list_templates(api_key: str) -> None:
    r = requests.get(f"{API_BASE}/templates", headers=_headers(api_key))
    r.raise_for_status()
    print(f"\n{'ID':<40}  Name")
    print("─" * 65)
    for t in r.json():
        print(f"  {t['id']:<38}  {t.get('name', '')}")
    print()


def upload_video(path: Path, api_key: str) -> str:
    print(f"Uploading {path.name}  ({path.stat().st_size / 1_000_000:.1f} MB)...")
    with open(path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/videos",
            headers=_headers(api_key),
            files={"file": (path.name, f, "video/mp4")},
        )
    r.raise_for_status()
    video_id = r.json()["id"]
    print(f"  Video ID : {video_id}")
    return video_id


def create_task(video_id: str, template_id: str, api_key: str,
                font_size: int, caption_top: int, auto_approve: bool) -> str:
    print("Creating captioning task...")
    r = requests.post(
        f"{API_BASE}/videos/{video_id}/task",
        headers={**_headers(api_key), "Content-Type": "application/json"},
        json={
            "templateId": template_id,
            "autoApprove": auto_approve,
            "language": "en",
            "renderOptions": {
                "styleOptions": {
                    "fontSize": font_size,
                    "top":      caption_top,
                }
            },
        },
    )
    r.raise_for_status()
    task_id = r.json()["taskId"]
    print(f"  Task ID  : {task_id}")
    return task_id


def poll_until_status(video_id: str, task_id: str, api_key: str,
                      target: str | set) -> dict:
    targets = {target} if isinstance(target, str) else target
    print(f"Waiting for {' / '.join(targets)} ", end="", flush=True)
    while True:
        r = requests.get(
            f"{API_BASE}/videos/{video_id}/task/{task_id}",
            headers=_headers(api_key),
        )
        r.raise_for_status()
        data   = r.json()
        status = data.get("status", "")
        if status in targets:
            print(" done.")
            return data
        if status in ("failed", "error"):
            print(f"\nTask failed: {data}")
            sys.exit(1)
        print(".", end="", flush=True)
        time.sleep(POLL_INTERVAL)


def download_transcript(url: str) -> list:
    r = requests.get(url)
    r.raise_for_status()
    return r.json()


def put_transcript(video_id: str, task_id: str, api_key: str, words: list) -> None:
    r = requests.put(
        f"{API_BASE}/videos/{video_id}/task/{task_id}/transcript",
        headers={**_headers(api_key), "Content-Type": "application/json"},
        json=words,
    )
    if not r.ok:
        print(f"ZapCap error {r.status_code}: {r.text}")
        r.raise_for_status()


def approve_transcript(video_id: str, task_id: str, api_key: str) -> None:
    r = requests.post(
        f"{API_BASE}/videos/{video_id}/task/{task_id}/approve-transcript",
        headers=_headers(api_key),
    )
    r.raise_for_status()


def download_result(url: str, out_path: Path) -> None:
    print(f"Downloading to {out_path.name}...")
    r = requests.get(url, stream=True)
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"  Saved ({out_path.stat().st_size / 1_000_000:.1f} MB)")


# ── transcript review ─────────────────────────────────────────────────────────

def review_and_edit(words: list) -> list:
    """
    Print numbered word list, let user type corrections before render.
    Correction format: "3:CorrectWord 7:AnotherFix"
    Comma or space separated, index is 1-based.
    """
    only_words = [w for w in words if w.get("type") == "word"]

    print("\n─── Transcript ──────────────────────────────────────────")
    line, line_words = "", []
    for i, w in enumerate(only_words, 1):
        token = f"[{i}]{w['text']}"
        if len(line) + len(token) > 80:
            print(line)
            line = ""
        line += token + " "
    if line:
        print(line)
    print("─────────────────────────────────────────────────────────\n")

    print("Press Enter to approve as-is.")
    print("To fix words, type corrections like:  3:TellMeAJoke 7:correct 20:fo drizzle")
    raw = input("> ").strip()

    if not raw:
        return words

    # Build index → new text map (1-based over only_words)
    # Format: "3:word 7:two words 9:another" — each entry runs until the next N: or end
    corrections: dict[int, str] = {}
    for m in re.finditer(r'(\d+):(.*?)(?=\s+\d+:|$)', raw.strip()):
        try:
            corrections[int(m.group(1))] = m.group(2).strip()
        except ValueError:
            print(f"  Skipping unrecognised correction: {m.group(0)!r}")

    if not corrections:
        return words

    # Apply corrections — supports removal (empty), replacement, and expansion (multi-word)
    word_counter = 0
    remove_indices = set()
    expansions: dict[int, list[dict]] = {}  # index in words → replacement entries

    for i, w in enumerate(words):
        if w.get("type") == "word":
            word_counter += 1
            if word_counter in corrections:
                old = w["text"]
                new = corrections[word_counter]
                if new == "":
                    remove_indices.add(i)
                    print(f"  [{word_counter}] {old!r} → (removed)")
                elif " " in new:
                    # Expand one word into multiple, splitting the time range equally
                    parts = new.split()
                    dur   = (w["end_time"] - w["start_time"]) / len(parts)
                    expanded = []
                    for j, part in enumerate(parts):
                        expanded.append({**w,
                            "text":       part,
                            "start_time": round(w["start_time"] + j * dur, 3),
                            "end_time":   round(w["start_time"] + (j + 1) * dur, 3),
                        })
                    expansions[i] = expanded
                    print(f"  [{word_counter}] {old!r} → {parts}")
                else:
                    w["text"] = new
                    print(f"  [{word_counter}] {old!r} → {new!r}")

    result = []
    for i, w in enumerate(words):
        if i in remove_indices:
            continue
        if i in expansions:
            result.extend(expansions[i])
        else:
            result.append(w)
    return result


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="ZapCap captioning.")
    parser.add_argument("video",            help="Video file to caption")
    parser.add_argument("--auto",           action="store_true",
                        help="Skip transcript review and render immediately (no pause)")
    parser.add_argument("--list-templates", action="store_true")
    args = parser.parse_args()

    config  = load_config()
    api_key = config.get("zapcap_api_key", "")
    if not api_key or "YOUR" in api_key:
        print("Error: add zapcap_api_key to config.json")
        sys.exit(1)

    if args.list_templates:
        list_templates(api_key)
        return

    input_path = Path(args.video)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        sys.exit(1)

    template_id = config.get("zapcap_template_id", "")
    if not template_id or "YOUR" in template_id:
        print("Error: add zapcap_template_id to config.json")
        sys.exit(1)

    out_path    = OUTPUT / input_path.name
    font_size   = config.get("zapcap_font_size", 9)
    caption_top = config.get("zapcap_caption_top", 70)

    print(f"\nInput    : {input_path}")
    print(f"Output   : {out_path}")
    print(f"Template : {template_id}")
    review = not args.auto
    print(f"Review   : {'yes' if review else 'no (--auto)'}\n")

    video_id = upload_video(input_path, api_key)
    task_id  = create_task(video_id, template_id, api_key,
                           font_size, caption_top,
                           auto_approve=not review)

    if review:
        # Wait for transcription, then let user review/edit before rendering
        data     = poll_until_status(video_id, task_id, api_key, "transcriptionCompleted")
        words    = download_transcript(data["transcript"])
        words    = review_and_edit(words)
        print("\nSaving transcript edits...")
        put_transcript(video_id, task_id, api_key, words)
        print("Approving and triggering render...")
        approve_transcript(video_id, task_id, api_key)

    # Wait for final render
    data = poll_until_status(video_id, task_id, api_key, "completed")
    download_result(data["downloadUrl"], out_path)
    print(f"\nDone → {out_path}\n")


if __name__ == "__main__":
    main()
