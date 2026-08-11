#!/usr/bin/env python3
"""
Composite a matted joke-teller over a new background with optional timed prop overlay.

Reads fgr/pha from scratch/ (output of matte.py), composites over a background image,
and outputs a 1080x1920 TikTok-ready video to output/composited/.

Usage:
    python3 caption-automation/composite.py "John tells Italian navy joke.mp4"

    # With a specific background:
    python3 caption-automation/composite.py "clip.mp4" \\
        --background assets/animals/backgrounds/bg_01.png

    # With a timed prop overlay (appears at 4.0s, disappears at 7.0s):
    python3 caption-automation/composite.py "clip.mp4" \\
        --background assets/animals/backgrounds/bg_01.png \\
        --prop assets/animals/props/prop_01.png \\
        --prop-start 4.0 --prop-end 7.0 \\
        --prop-x 600 --prop-y 800 --prop-size 350
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRATCH = Path.home() / "TellMeAJoke/scratch"
ASSETS  = Path.home() / "TellMeAJoke/assets"
MASTER  = Path.home() / "TellMeAJoke/content/master"
OUTPUT  = Path.home() / "TellMeAJoke/output/composited"
TW, TH  = 1080, 1920


def video_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def build_filter(prop_idx: int | None, prop_start: float, prop_end: float,
                 prop_x: int, prop_y: int, prop_size: int,
                 bg_blur: float = 3.0) -> tuple[str, str]:
    """Return (filter_complex string, output stream label)."""
    blur_step = f",gblur=sigma={bg_blur}" if bg_blur > 0 else ""
    f = (
        # Scale background to exactly 1080x1920 (fill then crop), then blur for depth of field
        f"[0:v]scale={TW}:{TH}:force_original_aspect_ratio=increase,"
        f"crop={TW}:{TH},setsar=1{blur_step}[bg];"
        # Scale foreground RGB to fit width, keep aspect ratio (height auto, divisible by 2)
        f"[1:v]scale={TW}:-2[fgr_s];"
        # Scale alpha matte the same way and force grayscale
        f"[2:v]scale={TW}:-2,format=gray[pha_s];"
        # Merge foreground + alpha → RGBA person video
        f"[fgr_s][pha_s]alphamerge[person];"
        # Overlay person centred vertically on the background
        f"[bg][person]overlay=(W-w)/2:(H-h)/2[comp0]"
    )
    out_label = "comp0"

    if prop_idx is not None:
        f += (
            f";[{prop_idx}:v]scale={prop_size}:{prop_size}[prop_s];"
            f"[comp0][prop_s]overlay={prop_x}:{prop_y}:"
            f"enable='between(t,{prop_start},{prop_end})'[comp1]"
        )
        out_label = "comp1"

    return f, out_label


def main() -> None:
    parser = argparse.ArgumentParser(description="Composite matted clip over a background.")
    parser.add_argument("clip",         help="Source clip filename (e.g. 'John tells Italian navy joke.mp4')")
    parser.add_argument("--background", default=None, help="Background image (default: first found in assets/)")
    parser.add_argument("--prop",       default=None, help="Prop PNG path")
    parser.add_argument("--prop-start", type=float, default=0.0,  metavar="SEC")
    parser.add_argument("--prop-end",   type=float, default=99.0, metavar="SEC")
    parser.add_argument("--prop-x",     type=int,   default=600,  metavar="PX",  help="Prop left edge in pixels")
    parser.add_argument("--prop-y",     type=int,   default=800,  metavar="PX",  help="Prop top edge in pixels")
    parser.add_argument("--prop-size",  type=int,   default=350,  metavar="PX",  help="Prop bounding box (square)")
    parser.add_argument("--tag",        default=None, help="Suffix added to output filename, e.g. 'bg2'")
    parser.add_argument("--bg-blur",    type=float, default=3.0,  metavar="SIGMA",
                        help="Gaussian blur sigma applied to background (default: 3.0, 0 = no blur)")
    args = parser.parse_args()

    clip_name = Path(args.clip).name
    stem      = Path(args.clip).stem
    src       = MASTER / clip_name
    fgr       = SCRATCH / f"{stem}_fgr.mp4"
    pha       = SCRATCH / f"{stem}_pha.mp4"

    for path, label in [
        (src, "source clip"),
        (fgr, "foreground — run matte.py first"),
        (pha, "alpha — run matte.py first"),
    ]:
        if not path.exists():
            print(f"Error: {label} not found:\n  {path}")
            sys.exit(1)

    # Background resolution
    if args.background:
        bg_path = Path(args.background)
        if not bg_path.exists():
            print(f"Error: background not found: {bg_path}")
            sys.exit(1)
    else:
        bg_path = next(iter(sorted(ASSETS.glob("*/backgrounds/bg_*.png"))), None)
        if bg_path is None:
            print("No background found. Run generate_assets.py or pass --background <path>.")
            sys.exit(1)
        print(f"Auto-selected background: {bg_path.relative_to(Path.home() / 'TellMeAJoke')}")

    prop_path = Path(args.prop) if args.prop else None
    if prop_path and not prop_path.exists():
        print(f"Error: prop not found: {prop_path}")
        sys.exit(1)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    suffix   = f"_{args.tag}" if args.tag else ""
    out_path = OUTPUT / f"{stem}{suffix}_composite.mp4"
    duration = video_duration(fgr)

    print(f"\nClip       : {clip_name}")
    print(f"Background : {bg_path.name}")
    print(f"Prop       : {prop_path.name if prop_path else '(none)'}")
    print(f"Duration   : {duration:.2f}s")
    print(f"Output     : {out_path.name}\n")

    # Build ffmpeg inputs in order, track audio input index
    # Order: bg(0), fgr(1), pha(2), [prop(3)], audio_src(3 or 4)
    inputs: list[str] = [
        "-loop", "1", "-i", str(bg_path),  # 0: background image, looped
        "-i", str(fgr),                     # 1: foreground RGB
        "-i", str(pha),                     # 2: alpha matte
    ]
    prop_input_idx = None
    if prop_path:
        inputs += ["-i", str(prop_path)]    # 3: prop PNG
        prop_input_idx = 3
        audio_input_idx = 4
    else:
        audio_input_idx = 3
    inputs += ["-i", str(src)]              # audio source

    filt, out_label = build_filter(
        prop_input_idx,
        args.prop_start, args.prop_end,
        args.prop_x, args.prop_y, args.prop_size,
        bg_blur=args.bg_blur,
    )

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", filt,
            "-map", f"[{out_label}]",
            "-map", f"{audio_input_idx}:a?",
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    )

    print("Running ffmpeg…")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg error:\n")
        print(result.stderr[-3000:])
        sys.exit(1)

    print(f"Done → {out_path}\n")


if __name__ == "__main__":
    main()
