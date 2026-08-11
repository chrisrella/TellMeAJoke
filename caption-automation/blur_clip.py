#!/usr/bin/env python3
"""
Convert a single clip to 9:16 TikTok format with a blurred background fill.
Original video is centered; blurred version fills the top and bottom areas.

Usage:
    python3 caption-automation/blur_clip.py "Frank tells mexican joke.mp4"
    python3 caption-automation/blur_clip.py "clip.mp4" --output /path/to/out.mp4
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

MASTER = Path.home() / "TellMeAJoke/content/master"
OUTPUT = Path.home() / "TellMeAJoke/output/blurred"

TW, TH = 1080, 1920
FPS    = 30


def video_info(path: Path) -> tuple[float, bool]:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(r.stdout).get("streams", [])
    duration, has_audio = 0.0, False
    for s in streams:
        if s.get("codec_type") == "video":
            duration = float(s.get("duration", 0))
        if s.get("codec_type") == "audio":
            has_audio = True
    return duration, has_audio


def process(src: Path, out: Path) -> None:
    duration, has_audio = video_info(src)

    BW, BH = TW // 2, TH // 2
    vf = (
        f"[0:v]split=2[bg_in][fg_in];"
        # Blurred background: downscale, blur, upscale to fill 1080x1920
        f"[bg_in]scale=w={BW}:h={BH}:force_original_aspect_ratio=increase,"
        f"crop=w={BW}:h={BH},"
        f"boxblur=luma_radius=20:luma_power=2:chroma_radius=20:chroma_power=2,"
        f"scale=w={TW}:h={TH}[bg];"
        # Foreground: scale to fit within 1080x1920, then pad to exact size
        f"[fg_in]scale=w={TW}:h={TH}:force_original_aspect_ratio=decrease,"
        f"pad=w={TW}:h={TH}:x=(ow-iw)/2:y=(oh-ih)/2:color=black@0[fg];"
        # Layer foreground over blurred background
        f"[bg][fg]overlay=0:0,setsar=1[v]"
    )

    if has_audio:
        af = "[0:a]aresample=44100[aout]"
        inputs = ["-i", str(src)]
    else:
        af = "[1:a]aresample=44100[aout]"
        inputs = ["-i", str(src), "-f", "lavfi", "-i",
                  f"anullsrc=r=44100:cl=stereo:d={duration}"]

    cmd = [
        "ffmpeg", "-y",
        "-t", str(duration),
    ] + inputs + [
        "-filter_complex", f"{vf};{af}",
        "-map", "[v]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-r", str(FPS), "-pix_fmt", "yuv420p",
        "-s", f"{TW}x{TH}",
        str(out),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg error:\n")
        print(result.stderr[-3000:])
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-clip TikTok blur formatter.")
    parser.add_argument("clip", help="Clip filename (e.g. 'Frank tells mexican joke.mp4')")
    parser.add_argument("--output", default=None, help="Output path (default: output/blurred/)")
    args = parser.parse_args()

    clip_name = Path(args.clip).name
    src = MASTER / clip_name
    if not src.exists():
        print(f"Error: clip not found:\n  {src}")
        sys.exit(1)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        out = OUTPUT / f"{src.stem}_blurred.mp4"

    print(f"\nInput  : {clip_name}")
    print(f"Output : {out}\n")
    process(src, out)
    print(f"Done → {out}\n")


if __name__ == "__main__":
    main()
