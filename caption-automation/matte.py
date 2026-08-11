#!/usr/bin/env python3
"""
Run Robust Video Matting on a single clip to extract the foreground person
from the background.

Outputs two intermediate videos into scratch/:
    {stem}_fgr.mp4   — foreground (person pixels, RGB)
    {stem}_pha.mp4   — alpha matte (grayscale, white = person)

These are consumed by composite.py in the next pipeline step.

Usage:
    python3 caption-automation/matte.py "John tells Italian navy joke.mp4"
    python3 caption-automation/matte.py "clip.mp4" --mbps 8
"""

import argparse
import sys
from pathlib import Path

import torch

RVM_DIR = Path(__file__).parent / "rvm"
MASTER  = Path.home() / "TellMeAJoke/content/master"
SCRATCH = Path.home() / "TellMeAJoke/scratch"
WEIGHTS = RVM_DIR / "rvm_mobilenetv3.pth"


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract person matte from a video clip using RVM.")
    parser.add_argument("clip", help="Path to source video clip")
    parser.add_argument("--mbps", type=float, default=4.0, help="Output video bitrate in Mbps (default: 4)")
    args = parser.parse_args()

    src = Path(args.clip)
    if not src.exists():
        src = MASTER / Path(args.clip).name
    if not src.exists():
        print(f"Error: clip not found: {args.clip}")
        sys.exit(1)

    if not WEIGHTS.exists():
        print(f"Error: model weights not found at {WEIGHTS}")
        print("Run: curl -L https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3.pth -o caption-automation/rvm/rvm_mobilenetv3.pth")
        sys.exit(1)

    SCRATCH.mkdir(parents=True, exist_ok=True)

    out_fgr = SCRATCH / f"{src.stem}_fgr.mp4"
    out_pha = SCRATCH / f"{src.stem}_pha.mp4"

    device = pick_device()
    print(f"\nClip    : {src.name}")
    print(f"Device  : {device}")
    print(f"Weights : rvm_mobilenetv3.pth")
    print(f"Out fgr : {out_fgr.name}")
    print(f"Out pha : {out_pha.name}\n")

    # Import RVM from the cloned repo directory
    sys.path.insert(0, str(RVM_DIR))
    from model import MattingNetwork
    from inference import convert_video

    print("Loading model…")
    model = MattingNetwork("mobilenetv3").eval().to(device)
    model.load_state_dict(torch.load(WEIGHTS, map_location=device))

    print("Running matting…")
    convert_video(
        model,
        input_source=str(src),
        output_type="video",
        output_foreground=str(out_fgr),
        output_alpha=str(out_pha),
        output_video_mbps=args.mbps,
        seq_chunk=1,       # process one frame at a time (safe for MPS memory)
        num_workers=0,
        progress=True,
        device=device,
        dtype=torch.float32,
    )

    print(f"\nDone.")
    print(f"  Foreground : {out_fgr}")
    print(f"  Alpha      : {out_pha}")
    print(f"\nNext: python3 caption-automation/composite.py '{src.name}'\n")


if __name__ == "__main__":
    main()
