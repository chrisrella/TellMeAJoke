#!/usr/bin/env python3
"""
Full background-swap pipeline for a single clip:
    matte.py → composite.py → caption.py

Usage:
    python3 caption-automation/pipeline.py "John tells Italian navy joke.mp4"

    python3 caption-automation/pipeline.py "clip.mp4" \\
        --background assets/animals/backgrounds/bg_02.png \\
        --prop assets/animals/props/prop_01.png \\
        --prop-start 3.0 --prop-end 6.0
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent


def run(label: str, cmd: list[str]) -> None:
    print(f"\n{'─'*50}")
    print(f"  {label}")
    print(f"{'─'*50}\n")
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print(f"\nPipeline stopped: {label} failed.")
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full background-swap pipeline on one clip.")
    parser.add_argument("clip",         help="Source clip filename, e.g. 'John tells Italian navy joke.mp4'")
    parser.add_argument("--background", default=None, help="Background image (default: first found in assets/)")
    parser.add_argument("--prop",       default=None, help="Prop PNG path")
    parser.add_argument("--prop-start", type=float, default=0.0,  metavar="SEC")
    parser.add_argument("--prop-end",   type=float, default=99.0, metavar="SEC")
    parser.add_argument("--prop-x",     type=int,   default=600,  metavar="PX")
    parser.add_argument("--prop-y",     type=int,   default=800,  metavar="PX")
    parser.add_argument("--prop-size",  type=int,   default=350,  metavar="PX")
    parser.add_argument("--tag",        default=None, help="Suffix for output filenames, e.g. 'bg2'")
    parser.add_argument("--skip-matte", action="store_true",
                        help="Skip matting if fgr/pha already exist in scratch/")
    args = parser.parse_args()

    clip   = args.clip
    stem   = Path(clip).stem
    suffix = f"_{args.tag}" if args.tag else ""
    print(f"\nPipeline starting for: {clip}  (tag: {args.tag or 'none'})\n")

    # ── Step 1: matte ────────────────────────────────────────────────────────
    scratch   = Path.home() / "TellMeAJoke/scratch"
    fgr_exist = (scratch / f"{stem}_fgr.mp4").exists()
    pha_exist = (scratch / f"{stem}_pha.mp4").exists()
    if args.skip_matte or (fgr_exist and pha_exist):
        print("─" * 50)
        print("  Step 1/3 — Matte (skipped — already exists)")
        print("─" * 50)
    else:
        run("Step 1/3 — Background matting (RVM)", [
            "python3", str(SCRIPTS / "matte.py"), clip,
        ])

    # ── Step 2: composite ────────────────────────────────────────────────────
    composite_cmd = ["python3", str(SCRIPTS / "composite.py"), clip]
    if args.background:
        composite_cmd += ["--background", args.background]
    if args.prop:
        composite_cmd += [
            "--prop",       args.prop,
            "--prop-start", str(args.prop_start),
            "--prop-end",   str(args.prop_end),
            "--prop-x",     str(args.prop_x),
            "--prop-y",     str(args.prop_y),
            "--prop-size",  str(args.prop_size),
        ]
    if args.tag:
        composite_cmd += ["--tag", args.tag]
    run("Step 2/3 — Composite (person + background + prop)", composite_cmd)

    # ── Step 3: caption ──────────────────────────────────────────────────────
    caption_cmd = ["python3", str(SCRIPTS / "caption.py"), clip]
    if args.tag:
        caption_cmd += ["--tag", args.tag]
    run("Step 3/3 — Captions (faster-whisper)", caption_cmd)

    out_path = Path.home() / f"TellMeAJoke/output/captioned_auto/{stem}{suffix}_captioned.mp4"
    print(f"\n{'='*50}")
    print(f"  Pipeline complete!")
    print(f"  Output: {out_path}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
