#!/usr/bin/env python3
"""
Burn faster-whisper captions into a composited video.

Since this ffmpeg build lacks libass/libfreetype, captions are rendered as
transparent RGBA PNGs with Pillow and composited via ffmpeg's overlay filter
with timed enable='between(t,start,end)' expressions.

Usage:
    python3 caption-automation/caption.py "John tells Italian navy joke.mp4"
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MASTER      = Path.home() / "TellMeAJoke/content/master"
COMPOSITED  = Path.home() / "TellMeAJoke/output/composited"
OUTPUT      = Path.home() / "TellMeAJoke/output/captioned_auto"
SCRATCH     = Path.home() / "TellMeAJoke/scratch"
FONTS_DIR   = Path.home() / "TellMeAJoke/caption-automation/fonts"

TW, TH      = 1080, 1920
CAPTION_Y   = 1580   # top edge of caption strip in the 1920px frame
CAPTION_H   = 240    # height of the caption image strip
FONT_SIZE   = 82
STROKE_W    = 6
WORDS_PER_CHUNK = 3
MAX_CHUNK_DUR   = 2.0


# ── font ──────────────────────────────────────────────────────────────────────

def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        str(FONTS_DIR / "Anton-Regular.ttf"),
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


# ── transcription ─────────────────────────────────────────────────────────────

def transcribe(clip_path: Path) -> list:
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(clip_path), word_timestamps=True)
    words = []
    for seg in segments:
        if seg.words:
            words.extend(seg.words)
    return words


# ── caption chunks ────────────────────────────────────────────────────────────

def group_chunks(words: list) -> list[tuple[float, float, str]]:
    chunks: list[tuple[float, float, str]] = []
    bucket: list = []
    chunk_start: float | None = None

    for w in words:
        if chunk_start is None:
            chunk_start = w.start
        bucket.append(w)
        if len(bucket) >= WORDS_PER_CHUNK or (w.end - chunk_start) >= MAX_CHUNK_DUR:
            text = " ".join(bw.word.strip() for bw in bucket).upper()
            chunks.append((chunk_start, w.end, text))
            bucket = []
            chunk_start = None

    if bucket:
        text = " ".join(bw.word.strip() for bw in bucket).upper()
        chunks.append((chunk_start, bucket[-1].end, text))

    return chunks


# ── caption PNG rendering ─────────────────────────────────────────────────────

def render_caption_png(text: str, out_path: Path) -> None:
    """Render a full-width transparent PNG strip with styled caption text."""
    img  = Image.new("RGBA", (TW, CAPTION_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = load_font(FONT_SIZE)
    draw.text(
        (TW // 2, CAPTION_H // 2),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=STROKE_W,
        stroke_fill=(0, 0, 0, 255),
        anchor="mm",
    )
    img.save(out_path)


# ── compositing ───────────────────────────────────────────────────────────────

def video_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def burn_captions(composite: Path, chunks: list[tuple[float, float, str]],
                  out_path: Path) -> None:
    cap_dir = SCRATCH / "caption_frames"
    cap_dir.mkdir(exist_ok=True)

    # Render one PNG per unique caption text
    cap_pngs: list[Path] = []
    for i, (_, _, text) in enumerate(chunks):
        png = cap_dir / f"cap_{i:03d}.png"
        render_caption_png(text, png)
        cap_pngs.append(png)
    print(f"  Rendered {len(cap_pngs)} caption images")

    duration = video_duration(composite)

    # Build ffmpeg inputs: video first, then one image per caption chunk
    inputs: list[str] = ["-i", str(composite)]
    for png in cap_pngs:
        inputs += ["-loop", "1", "-t", str(duration), "-i", str(png)]

    # Build overlay filter chain
    # [0:v] → overlay cap[0] → overlay cap[1] → … → final
    filter_parts: list[str] = []
    prev = "0:v"
    for i, (start, end, _) in enumerate(chunks):
        idx = i + 1   # input index (0 = composite video)
        nxt = f"o{i}"
        filter_parts.append(
            f"[{prev}][{idx}:v]overlay=0:{CAPTION_Y}:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{nxt}]"
        )
        prev = nxt

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
    ] + inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[{prev}]",
        "-map", "0:a?",
        "-t", str(duration),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg error:\n")
        print(result.stderr[-3000:])
        sys.exit(1)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Burn faster-whisper captions into a composited video.")
    parser.add_argument("clip", help="Source clip filename")
    parser.add_argument("--tag", default=None, help="Must match the --tag used in composite.py")
    args = parser.parse_args()

    clip_name = Path(args.clip).name
    stem      = Path(args.clip).stem
    src       = MASTER / clip_name
    suffix    = f"_{args.tag}" if args.tag else ""
    composite = COMPOSITED / f"{stem}{suffix}_composite.mp4"

    if not src.exists():
        print(f"Error: source clip not found:\n  {src}")
        sys.exit(1)
    if not composite.exists():
        print(f"Error: composite not found:\n  {composite}\nRun composite.py first.")
        sys.exit(1)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT / f"{stem}{suffix}_captioned.mp4"

    print(f"\nSource    : {clip_name}")
    print(f"Input     : {composite.name}")
    print(f"Output    : {out_path.name}\n")

    print("Transcribing with faster-whisper…")
    words = transcribe(src)
    print(f"  {len(words)} words")

    print("Grouping into caption chunks…")
    chunks = group_chunks(words)
    print(f"  {len(chunks)} chunks")
    for s, e, t in chunks:
        print(f"    {s:.2f}s – {e:.2f}s  {t}")

    print("\nRendering and burning captions…")
    burn_captions(composite, chunks, out_path)

    print(f"\nDone → {out_path}\n")


if __name__ == "__main__":
    main()
