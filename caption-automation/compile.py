#!/usr/bin/env python3
"""
TikTok compilation builder for TellMeAJoke.com

Picks N videos from a theme category, converts each to 9:16 (1080x1920)
with a blurred background fill, a persistent TellMeAJoke.com watermark,
an optional punchline sound effect, and assembles them into a single
TikTok-ready MP4.

Usage:
    python3 compile.py --list                    # show categories + counts
    python3 compile.py "Blonde"                  # 3-video Blonde compilation
    python3 compile.py "Knock Knock" --count 5
    python3 compile.py "Dad Jokes" --seed 42     # reproducible pick
    python3 compile.py "Blonde" --dry-run        # see which clips would be used
    python3 compile.py "Blonde" --sound rimshot  # name of .mp3 in sounds/ dir

Output: ~/TellMeAJoke/output/test-compilations/<slug>_top<n>.mp4

Sound effects go in:  ~/TellMeAJoke/caption-automation/sounds/
    Add any .mp3 file (e.g. rimshot.mp3, vine_boom.mp3, crowd_laugh.mp3)
    and reference it with --sound <name> (without extension).
    If the file is missing, the sound step is silently skipped.
"""

import argparse
import csv
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

MASTER      = Path.home() / "TellMeAJoke/content/master"
THEMES      = Path.home() / "TellMeAJoke/content/themes.csv"
TRANSCRIPTS = Path.home() / "TellMeAJoke/content/transcripts.csv"
OUTPUT      = Path.home() / "TellMeAJoke/output/test-compilations"
SOUNDS      = Path.home() / "TellMeAJoke/caption-automation/sounds"
FONTS_DIR   = Path.home() / "TellMeAJoke/caption-automation/fonts"

TW, TH    = 1080, 1920   # TikTok 9:16
FPS       = 30
MAX_CLIP  = 30.0          # trim source clips longer than this (seconds)
WATERMARK = "TellMeAJoke.com"

# Rank medal colors (RGBA)
RANK_COLORS = {
    1: (255, 215,   0, 255),   # gold
    2: (192, 192, 192, 255),   # silver
    3: (184, 115,  51, 255),   # bronze
}

_FONT_PATHS = [
    str(FONTS_DIR / "Anton-Regular.ttf"),  # downloaded via scripts/download_fonts.sh
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/Library/Fonts/Arial.ttf",
]


# ── data ─────────────────────────────────────────────────────────────────────

def get_categories() -> dict[str, list[str]]:
    """Return {category: [filename, ...]} — Fails / Bombs excluded from all lists."""
    cats: dict[str, list[str]] = {}
    with open(THEMES) as f:
        for row in csv.DictReader(f):
            themes = [t.strip() for t in row["themes"].split(",")]
            if "Fails / Bombs" in themes:
                continue
            for t in themes:
                cats.setdefault(t, []).append(row["filename"])
    return cats


def caption_from_transcript(transcript: str) -> str:
    """Extract a punchy 1-4 word label from the joke punchline (last sentence)."""
    import re
    if not transcript.strip():
        return "Watch This"
    sentences = [s.strip() for s in re.split(r"[.!?]+", transcript.strip()) if s.strip()]
    punchline = sentences[-1] if sentences else transcript
    words = [w.strip(".,!?;:()[]\"'") for w in punchline.split() if w.strip(".,!?;:()[]\"'")]
    return " ".join(words[-4:]).title() if words else "Watch This"


def load_captions(filenames: list[str]) -> dict[str, str]:
    """Return {filename: short_caption} for each filename using transcript data."""
    transcripts: dict[str, str] = {}
    if TRANSCRIPTS.exists():
        with open(TRANSCRIPTS) as f:
            for row in csv.DictReader(f):
                if row["filename"] in filenames:
                    transcripts[row["filename"]] = row.get("transcript", "")
    return {fn: caption_from_transcript(transcripts.get(fn, "")) for fn in filenames}


def video_info(path: Path) -> tuple[float, bool, int, int]:
    """Return (duration_seconds, has_audio, width, height)."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(r.stdout).get("streams", [])
    duration, has_audio = 0.0, False
    width = height = 0
    for s in streams:
        if s.get("codec_type") == "video":
            duration = float(s.get("duration", 0))
            width    = int(s.get("width",    0))
            height   = int(s.get("height",   0))
        if s.get("codec_type") == "audio":
            has_audio = True
    return duration, has_audio, width, height


def video_zone(src_w: int, src_h: int) -> tuple[int, int]:
    """Return (y_start, y_end) pixel range the video occupies in a 1080x1920 frame."""
    scale    = min(TW / src_w, TH / src_h)
    scaled_h = int(src_h * scale)
    y_start  = (TH - scaled_h) // 2
    return y_start, y_start + scaled_h


# ── image helpers (Pillow) ────────────────────────────────────────────────────

def _load_font(size: int):
    from PIL import ImageFont
    for fp in _FONT_PATHS:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_text_card_png(text: str, png_path: Path) -> None:
    """Render white text centered on a black 1080x1920 PNG."""
    from PIL import Image, ImageDraw

    img  = Image.new("RGB", (TW, TH), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    font = _load_font(72)
    # Scale down if text is wider than frame
    max_w = TW - 80
    while hasattr(font, "size") and font.size > 24:  # type: ignore[union-attr]
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            break
        font = _load_font(font.size - 4)  # type: ignore[union-attr]

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y   = (TW - tw) // 2, (TH - th) // 2

    draw.text((x + 3, y + 3), text, fill=(0, 0, 0),       font=font)  # shadow
    draw.text((x,     y    ), text, fill=(255, 255, 255), font=font)
    img.save(str(png_path))


def _text_centered(draw, text, font, y: int, fill, shadow=(0,0,0,200)):
    """Draw text horizontally centered at y, with a drop shadow."""
    b  = draw.textbbox((0, 0), text, font=font)
    tw = b[2] - b[0]
    x  = (TW - tw) // 2
    draw.text((x + 3, y + 3), text, fill=shadow,  font=font)
    draw.text((x,     y    ), text, fill=fill,     font=font)
    return b[3] - b[1]   # returns rendered height


def make_frame_overlay_png(
    category: str,
    total: int,
    revealed: list[tuple[int, str]],  # (rank, caption) pairs so far, highest rank first
    vid_y0: int,
    vid_y1: int,
    out_path: Path,
    title_override: str | None = None,
) -> None:
    """
    Full-frame 1080x1920 RGBA overlay for one clip in the compilation.

    Layout:
      Top zone   (0 → vid_y0)  : dark bg · two-tone title · progressive rank list
      Video zone (vid_y0→vid_y1): transparent — video shows through
      Bottom zone(vid_y1 → TH) : dark bg · TellMeAJoke.com watermark
    """
    from PIL import Image, ImageDraw

    img  = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    DARK   = (0, 0, 0, 175)
    WHITE  = (255, 255, 255, 255)
    YELLOW = (255, 215,   0, 255)
    ORANGE = (255, 120,   0, 255)
    DIM    = (160, 160, 160,  90)
    SHADOW = (0,   0,     0, 200)

    # ── TOP ZONE ──────────────────────────────────────────────────────────
    draw.rectangle([0, 0, TW, vid_y0], fill=DARK)

    top_h  = vid_y0
    cursor = max(int(top_h * 0.06), 12)   # top padding

    if title_override:
        # Custom title: pipe-separated rows, first row white, second orange
        rows   = [r.strip().upper() for r in title_override.split("|")]
        t_font = _load_font(78)
        while hasattr(t_font, "size") and t_font.size > 28:  # type: ignore[union-attr]
            max_w = max((draw.textbbox((0,0), r, font=t_font)[2]) for r in rows)
            if max_w <= TW - 40:
                break
            t_font = _load_font(t_font.size - 3)  # type: ignore[union-attr]
        row_colors = [WHITE, ORANGE, YELLOW]
        for ri, row in enumerate(rows):
            b  = draw.textbbox((0, 0), row, font=t_font)
            rw = b[2] - b[0];  rh = b[3] - b[1]
            sx = (TW - rw) // 2
            draw.text((sx + 3, cursor + 3), row, fill=SHADOW, font=t_font)
            draw.text((sx,     cursor    ), row, fill=row_colors[ri % len(row_colors)], font=t_font)
            cursor += rh + 6
        cursor += 14
    else:
        # Default two-row title: "RANKING " white + "TOP N FUNNIEST" yellow / "CATEGORY JOKES" orange
        r1a = "RANKING "
        r1b = f"TOP {total} FUNNIEST"
        r2  = f"{category.upper()} JOKES"

        title_font = _load_font(78)
        while hasattr(title_font, "size") and title_font.size > 28:  # type: ignore[union-attr]
            b1a = draw.textbbox((0, 0), r1a, font=title_font)
            b1b = draw.textbbox((0, 0), r1b, font=title_font)
            b2  = draw.textbbox((0, 0), r2,  font=title_font)
            row1_w = (b1a[2] - b1a[0]) + (b1b[2] - b1b[0])
            row2_w = b2[2] - b2[0]
            if max(row1_w, row2_w) <= TW - 40:
                break
            title_font = _load_font(title_font.size - 3)  # type: ignore[union-attr]

        b1a = draw.textbbox((0, 0), r1a, font=title_font)
        b1b = draw.textbbox((0, 0), r1b, font=title_font)
        aw  = b1a[2] - b1a[0];  ah = b1a[3] - b1a[1]
        bw  = b1b[2] - b1b[0]
        sx  = (TW - aw - bw) // 2
        draw.text((sx + 3,      cursor + 3), r1a, fill=SHADOW, font=title_font)
        draw.text((sx + aw + 3, cursor + 3), r1b, fill=SHADOW, font=title_font)
        draw.text((sx,          cursor    ), r1a, fill=WHITE,  font=title_font)
        draw.text((sx + aw,     cursor    ), r1b, fill=YELLOW, font=title_font)
        cursor += ah + 6

        b2  = draw.textbbox((0, 0), r2, font=title_font)
        cw  = b2[2] - b2[0];  ch = b2[3] - b2[1]
        sx2 = (TW - cw) // 2
        draw.text((sx2 + 3, cursor + 3), r2, fill=SHADOW, font=title_font)
        draw.text((sx2,     cursor    ), r2, fill=ORANGE, font=title_font)
        cursor += ch + 20

    # Ranking list: always draw all ranks 1→total top-to-bottom.
    # Revealed ranks show colored number + white caption; unrevealed are dim.
    revealed_dict = {rank: caption for rank, caption in revealed}
    LIST_MARGIN   = 90
    rank_font     = _load_font(62)

    for rank in range(1, total + 1):
        is_revealed = rank in revealed_dict
        num_color   = RANK_COLORS.get(rank, WHITE) if is_revealed else DIM
        caption     = revealed_dict[rank] if is_revealed else "???"
        cap_color   = WHITE if is_revealed else DIM

        num = f"{rank}."
        bn  = draw.textbbox((0, 0), num, font=rank_font)
        nw  = bn[2] - bn[0];  nh = bn[3] - bn[1]
        cap_x = LIST_MARGIN + nw + 18

        cap_font = rank_font
        while hasattr(cap_font, "size") and cap_font.size > 28:  # type: ignore[union-attr]
            bc = draw.textbbox((0, 0), caption, font=cap_font)
            if cap_x + (bc[2] - bc[0]) <= TW - 40:
                break
            cap_font = _load_font(cap_font.size - 3)  # type: ignore[union-attr]

        if is_revealed:
            draw.text((LIST_MARGIN + 3, cursor + 3), num,     fill=SHADOW,    font=rank_font)
            draw.text((cap_x + 3,       cursor + 3), caption, fill=SHADOW,    font=cap_font)
        draw.text((LIST_MARGIN, cursor), num,     fill=num_color, font=rank_font)
        draw.text((cap_x,       cursor), caption, fill=cap_color, font=cap_font)
        cursor += nh + 14

    # ── BOTTOM ZONE ────────────────────────────────────────────────────────
    bot_h = TH - vid_y1
    draw.rectangle([0, vid_y1, TW, TH], fill=DARK)

    wm_font = _load_font(62)
    wb      = draw.textbbox((0, 0), WATERMARK, font=wm_font)
    wh      = wb[3] - wb[1]
    wy      = vid_y1 + (bot_h - wh) // 2
    _text_centered(draw, WATERMARK, wm_font, wy, fill=(255, 255, 255, 240))

    img.save(str(out_path))


# ── ffmpeg helpers ────────────────────────────────────────────────────────────

def detect_punchline_ms(path: Path, effective_dur: float) -> int:
    """
    Run ffmpeg silencedetect to find when the joke teller stops speaking.
    The last silence_start within the clip = moment punchline was just delivered.
    Falls back to (effective_dur - 1.5s) if no clear pause is detected.
    """
    result = subprocess.run([
        "ffmpeg", "-i", str(path),
        "-af", "silencedetect=noise=-30dB:d=0.35",
        "-f", "null", "-",
    ], capture_output=True, text=True)

    silence_starts = []
    for line in result.stderr.split("\n"):
        if "silence_start" in line:
            try:
                t = float(line.split("silence_start:")[1].strip().split()[0])
                # Only count silences after the first 0.5s and before the clip ends
                if 0.5 < t <= effective_dur:
                    silence_starts.append(t)
            except (IndexError, ValueError):
                pass

    if silence_starts:
        # Last silence_start = speech just ended = punchline delivered
        return max(0, int((silence_starts[-1] - 0.05) * 1000))

    # Fallback: 1.5s before end
    return max(0, int((effective_dur - 1.5) * 1000))


def _run(cmd: list[str], label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"\nFFmpeg error in {label}:")
        print(result.stderr[-2000:])
        sys.exit(1)


def make_text_card(text: str, out: Path, duration: float = 1.5) -> None:
    """Black card with centered white text — used for intro and outro."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        png_path = Path(f.name)
    try:
        make_text_card_png(text, png_path)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(png_path),
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-r", str(FPS), "-pix_fmt", "yuv420p",
            "-shortest", str(out),
        ]
        _run(cmd, f"text card '{text}'")
    finally:
        png_path.unlink(missing_ok=True)


def process_clip(
    src: Path,
    out: Path,
    has_audio: bool,
    duration: float,
    overlay_png: Path,
    sound_path: Path | None,
) -> None:
    """
    Convert one clip to 9:16 TikTok format:
    - Blurred background fill
    - Foreground video centered
    - Full-frame RGBA overlay (rank + title top, watermark bottom)
    - Optional sound effect at punchline
    - Trims to MAX_CLIP if needed
    """
    END_TRIM      = 0.3   # seconds to cut from the end of every clip (avoids camera fade-out)
    effective_dur = max(min(duration, MAX_CLIP) - END_TRIM, 1.0)
    use_sound     = sound_path is not None and sound_path.exists()
    punch_ms      = detect_punchline_ms(src, effective_dur) if use_sound else 0

    # ── Build input list, tracking indices ────────────────────────────────
    cmd      = ["ffmpeg", "-y", "-t", str(effective_dur)]
    cmd     += ["-i", str(src)]
    src_idx  = 0
    next_idx = 1

    # Full-frame overlay PNG — single frame; eof_action=repeat holds it for full clip
    cmd        += ["-i", str(overlay_png)]
    wm_idx      = next_idx; next_idx += 1

    # Silent audio fallback (used when source has no audio)
    silence_idx = None
    if not has_audio:
        cmd        += ["-f", "lavfi", "-i",
                       f"anullsrc=r=44100:cl=stereo:d={effective_dur}"]
        silence_idx = next_idx; next_idx += 1

    # Sound effect
    sfx_idx = None
    if use_sound:
        cmd    += ["-i", str(sound_path)]
        sfx_idx = next_idx; next_idx += 1

    # ── Video filter chain ────────────────────────────────────────────────
    # Background half-res: blur at 540x960 (4x fewer pixels) then upscale
    BW, BH = TW // 2, TH // 2
    vf = (
        f"[{src_idx}:v]split=2[bg_in][fg_in];"

        # Background: downscale for blur (much faster), then upscale to fill frame
        f"[bg_in]scale=w={BW}:h={BH}:force_original_aspect_ratio=increase,"
        f"crop=w={BW}:h={BH},"
        f"boxblur=luma_radius=20:luma_power=2:chroma_radius=20:chroma_power=2,"
        f"scale=w={TW}:h={TH}[bg];"

        # Foreground: scale to FIT inside 1080x1920, centered
        f"[fg_in]scale=w={TW}:h={TH}:force_original_aspect_ratio=decrease,"
        f"setsar=1[fg];"

        # Combine bg + fg
        f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2,setsar=1[v_base];"

        # Full-frame overlay (title top + watermark bottom): sits at 0,0
        f"[v_base][{wm_idx}:v]overlay=x=0:y=0:eof_action=repeat[v]"
    )

    # ── Audio filter chain ────────────────────────────────────────────────
    audio_src = f"[{src_idx}:a]" if has_audio else f"[{silence_idx}:a]"

    if use_sound:
        af = (
            f"{audio_src}aresample=44100[orig];"
            f"[{sfx_idx}:a]adelay={punch_ms}|{punch_ms}[sfx];"
            f"[orig][sfx]amix=inputs=2:duration=first[aout]"
        )
    else:
        af = f"{audio_src}aresample=44100[aout]"

    cmd += [
        "-filter_complex", f"{vf};{af}",
        "-map", "[v]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-r", str(FPS), "-pix_fmt", "yuv420p",
        str(out),
    ]
    _run(cmd, src.name)


def concatenate(clips: list[Path], out: Path) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for c in clips:
            f.write(f"file '{c}'\n")
        list_file = f.name
    _run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", list_file, "-c", "copy", str(out)],
        "concat",
    )


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build TikTok joke compilations")
    parser.add_argument("category", nargs="?")
    parser.add_argument("--count",   type=int, default=3)
    parser.add_argument("--seed",    type=int, default=None)
    parser.add_argument("--sound",    default=None,
                        help="Lock all clips to one sound (stem name). Omit to cycle all sounds in sounds/.")
    parser.add_argument("--no-sound", action="store_true",
                        help="Disable sound effects entirely.")
    parser.add_argument("--title",    default=None,
                        help="Override title text. Use | to split into two rows: \"Row One|Row Two\".")
    parser.add_argument("--captions", default=None,
                        help="Comma-separated captions in rank order (#1 first): \"Best One, Pretty Good, Meh\".")
    parser.add_argument("--clips",    default=None,
                        help="Comma-separated filenames in rank order (#1 first). Skips random selection.")
    parser.add_argument("--overlay-theme", default=None, metavar="THEME",
                        help="Run smart_overlay.py on each clip before processing (e.g. 'mexican')")
    parser.add_argument("--list",    action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cats = get_categories()

    if args.list or not args.category:
        print(f"\n{'Category':<35} {'Videos':>7}")
        print("─" * 44)
        for cat, vids in sorted(cats.items(), key=lambda x: -len(x[1])):
            print(f"  {cat:<33} {len(vids):>5}")
        print()
        return

    # --clips bypasses category selection entirely; category arg is only used for the title
    category = args.category
    if args.clips:
        explicit = [c.strip() for c in args.clips.split(",")]
        missing  = [f for f in explicit if not (MASTER / f).exists()]
        if missing:
            print("Error: clips not found in master/:")
            for f in missing:
                print(f"  {f}")
            sys.exit(1)
        args.count = len(explicit)
        picks = list(reversed(explicit))   # picks[0] plays first = rank N
    else:
        matches = [c for c in cats if args.category.lower() in c.lower()]
        if not matches:
            print(f"Category '{args.category}' not found. Run --list to see options.")
            sys.exit(1)
        category = matches[0]
        COMPILATION_MAX_DUR = 25.0
        candidates = [
            f for f in cats[category]
            if (MASTER / f).exists() and video_info(MASTER / f)[0] <= COMPILATION_MAX_DUR
        ]
        if len(candidates) < args.count:
            print(f"Only {len(candidates)} usable videos in '{category}' (requested {args.count}).")
            sys.exit(1)
        rng   = random.Random(args.seed)
        picks = rng.sample(candidates, args.count)

    # Sound assignment: one per clip, cycling through all .mp3s in SOUNDS dir.
    # --sound <name> locks all clips to that single sound.
    available_sounds = sorted(SOUNDS.glob("*.mp3"))
    if args.no_sound:
        clip_sounds = [None] * args.count
    elif args.sound:
        sp = SOUNDS / f"{args.sound}.mp3"
        clip_sounds = [sp if sp.exists() else None] * args.count
    else:
        clip_sounds = [available_sounds[i % len(available_sounds)] if available_sounds else None
                       for i in range(args.count)]

    print(f"\nCategory : {category}")
    print(f"Clips    : {args.count}")
    print(f"Sounds   : {[s.stem if s else 'none' for s in clip_sounds]}")
    print()
    for i, fn in enumerate(picks, 1):
        print(f"  [{i}] {fn}")

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return

    OUTPUT.mkdir(parents=True, exist_ok=True)
    SOUNDS.mkdir(parents=True, exist_ok=True)

    slug      = category.lower().replace(" / ", "_").replace(" ", "_")
    final_out = OUTPUT / f"{slug}_top{args.count}.mp4"

    # Captions: custom (--captions) or auto-generated from transcripts.
    # --captions order is rank 1 first (#1 best), rank N last — matching the on-screen list top-to-bottom.
    if args.captions:
        parsed = [c.strip() for c in args.captions.split(",")]
        if len(parsed) != args.count:
            print(f"Error: --captions needs exactly {args.count} values, got {len(parsed)}.")
            sys.exit(1)
        # picks[i] = rank (count-i), parsed[0] = rank-1 caption → invert
        captions = {picks[i]: parsed[args.count - 1 - i] for i in range(args.count)}
    else:
        captions = load_captions(picks)

    print()
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp   = Path(tmp_str)
        clips: list[Path] = []

        # Process clips — countdown order: picks[0]=rank N, picks[-1]=rank 1 (best last)
        # The revealed list grows each clip so the ranking list builds on screen
        for i, filename in enumerate(picks):
            rank     = args.count - i          # 3, 2, 1 for a count-3 compilation
            src      = MASTER / filename

            if args.overlay_theme:
                overlaid = tmp / f"{i+1:02d}_overlaid.mp4"
                print(f"      → smart overlay ({args.overlay_theme})…")
                overlay_result = subprocess.run([
                    "python3", str(Path(__file__).parent / "smart_overlay.py"),
                    filename,
                    "--theme", args.overlay_theme,
                    "--output", str(overlaid),
                ], capture_output=True, text=True)
                if overlay_result.returncode == 0:
                    src = overlaid
                else:
                    print(f"      ⚠ smart_overlay failed, using original clip")

            out      = tmp / f"{i+1:02d}_clip.mp4"
            dur, has_audio, src_w, src_h = video_info(src)
            vid_y0, vid_y1 = video_zone(src_w, src_h)
            trim      = f"  (trimming to {MAX_CLIP:.0f}s)" if dur > MAX_CLIP else ""
            eff_dur    = min(dur, MAX_CLIP)
            snd        = clip_sounds[i]
            boom_t     = detect_punchline_ms(src, eff_dur) / 1000 if snd and snd.exists() else None
            boom_note  = f"  boom@{boom_t:.1f}s" if boom_t is not None else ""
            print(f"[#{rank}] {filename}  ({dur:.1f}s){trim}{boom_note}")
            print(f"      caption: \"{captions[filename]}\"  sound: {snd.stem if snd else 'none'}")

            # revealed = all clips played so far, highest rank number first (3, 2, 1)
            revealed = [(args.count - j, captions[picks[j]]) for j in range(i + 1)]

            overlay_png = tmp / f"overlay_{i+1}.png"
            make_frame_overlay_png(category, args.count, revealed, vid_y0, vid_y1, overlay_png,
                                   title_override=args.title)

            process_clip(
                src, out, has_audio, dur, overlay_png,
                snd if snd and snd.exists() else None,
            )
            clips.append(out)

        print("Concatenating...")
        concatenate(clips, final_out)

    size_mb = final_out.stat().st_size / 1_000_000
    print(f"\nDone → {final_out}  ({size_mb:.1f} MB)\n")


if __name__ == "__main__":
    main()
