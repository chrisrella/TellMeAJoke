# cr - updated 08/2026
# TellMeAJoke — Video Automation Pipeline

An end-to-end pipeline that turns raw stand-up clips into published social videos: dedup and cleanup, transcription, AI-assisted captioning and tagging, TikTok-format rendering, and scheduled multi-platform posting.

cr - built to modernize and monetize an early 2000s street interview library. Started by building a CLI tool to help comb through and judge videos quickly. Then, by reformatting, captioning, and compiling videos together, they became ready-to-post for today's social media platforms. Lastly, I built a system using cron to automatically post 5 videos per weekday.

## Pipeline Overview

1. **Content prep** (`content-prep/`) — dedupes footage across formats, flags silent/unusable clips via ffprobe, and converts legacy formats (`.wmv`/`.flv`) to `.mp4`. Produces `content/master/`, the canonical clip library.
2. **Transcription & categorization** (`caption-automation/transcribe.py`, `categorize.py`) — bulk-transcribes rated keepers with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (GPU-accelerated), then tags each clip with theme categories for filtering later.
3. **Single-clip processing** (`caption-automation/post_pipeline.py`) — turns one rated clip into a ready-to-post Reel: reformats to 9:16 with a blurred background, overlays a GPT-4o-selected prop sticker, burns in captions via [ZapCap](https://zapcap.ai/), and generates an Instagram caption + hashtags with GPT-4o.
4. **Bulk processing** (`caption-automation/batch.py`) — runs that same pipeline across every approved, unprocessed clip in one pass, skipping anything already queued or posted.
5. **Compilation builder** (`caption-automation/compile.py`) — assembles ranked "Top N" countdown videos from a themed category, with overlay graphics, punchline sound effects, and a watermark. Documented in full below.
6. **Posting** (`caption-automation/poster.py`) — publishes queued videos to Instagram, Facebook, and YouTube (TikTok pending app review), designed to run unattended via cron (`gen_cron.py` generates the schedule).

See [`POSTING.md`](./POSTING.md) for the day-to-day operating workflow and cron setup.

## Tech Stack

- **Video/audio processing** — ffmpeg, Pillow, PyTorch (background matting)
- **Transcription** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper), Metal-GPU accelerated
- **AI captioning & tagging** — OpenAI GPT-4o (prop selection, Instagram captions/hashtags), [ZapCap](https://zapcap.ai/) (burned-in captions)
- **Platform APIs** — Meta Graph API (Instagram + Facebook), YouTube Data API, TikTok API, each with their own OAuth flow
- **Scheduling** — cron, driven by a generated per-day posting schedule

---

## Compilation Builder (`compile.py`)

Automatically assembles TikTok-ready joke compilation videos from the TellMeAJoke.com video library.

Each compilation features:
- Blurred background fill (9:16 format)
- Ranking overlay (gold/silver/bronze) with joke captions
- Rotating sound effects at punchline timing
- Watermark

---

## First-Time Setup

### 1. Install dependencies

You'll need Python 3.11+ and ffmpeg installed.

```
pip install -r requirements.txt
brew install ffmpeg
```

### 2. Folder structure

```
TellMeAJoke/
├── content/
│   ├── master/             ← source video files go here
│   ├── ratings.csv         ← video ratings (f=funny, c=chuckle, s=skip)
│   ├── transcripts.csv     ← auto-generated transcriptions
│   └── themes.csv          ← joke category tags
├── caption-automation/
│   ├── compile.py          ← main script
│   └── sounds/             ← .mp3 sound effects (vine-boom.mp3, etc.)
└── output/
    └── test-compilations/  ← finished videos land here
```

---

## Making a Compilation

From the `TellMeAJoke` folder, run:

```
python3 caption-automation/compile.py "Category Name" --count 3
```

**See all available categories:**
```
python3 caption-automation/compile.py --list
```

**Examples:**
```
python3 caption-automation/compile.py "Dad Jokes / Puns / Wordplay" --count 3
python3 caption-automation/compile.py "Blonde" --count 5
python3 caption-automation/compile.py "Animals" --count 3 --seed 42
```

The finished video appears in `output/test-compilations/`.

---

## Options

| Flag | What it does |
|---|---|
| `--count 5` | Number of clips (default: 3) |
| `--seed 42` | Reproducible clip selection — same seed = same clips every time |
| `--clips "..."` | Use specific clips by filename instead of random selection (see below) |
| `--title "..."` | Override the title text (see below) |
| `--captions "..."` | Override the ranking captions (see below) |
| `--sound vine-boom` | Lock all clips to one specific sound effect |
| `--dry-run` | Preview which clips would be selected without rendering |
| `--list` | Show all categories and how many clips each has |

---

## Using Specific Clips

To hand-pick exactly which clips appear, use `--clips` with a comma-separated list of filenames. List them in rank order — **#1 (best joke) first, #N last**:

```
python3 caption-automation/compile.py "Blonde" \
  --clips "best_clip.mp4, second_clip.mp4, third_clip.mp4" \
  --captions "Funniest Line, Pretty Good, Not Bad" \
  --title "Top 3 Blonde Jokes|You'll Ever Hear"
```

The script plays clips in countdown order (#N first, #1 last as the big reveal) regardless of the order you list them. You don't need `--count` when using `--clips` — it's set automatically.

---

## Customising the Title

By default the title reads "RANKING TOP 3 FUNNIEST / BLONDE JOKES". Override it with `--title`:

```
python3 caption-automation/compile.py "Blonde" --count 3 --title "Best Blonde Jokes"
```

Use `|` to split into two rows (first row white, second row orange):

```
python3 caption-automation/compile.py "Blonde" --count 3 --title "Top 3 Funniest|Blonde Jokes"
```

---

## Customising the Captions

Each clip in the ranking has a short label next to its number. Override them with `--captions`, listed in rank order — **#1 first, #N last** (matching the on-screen list top to bottom):

```
python3 caption-automation/compile.py "Blonde" --count 3 \
  --captions "The Best One, Pretty Funny, Not Bad"
```

You must provide exactly as many captions as `--count`.

---

## Reproducing a Specific Compilation

To get the exact same clips again, use `--seed`. Pick any number — the same seed always produces the same selection:

```
python3 caption-automation/compile.py "Animals" --count 3 --seed 42
```

Run with `--dry-run` first to preview which clips will be selected without rendering the video:

```
python3 caption-automation/compile.py "Animals" --count 3 --seed 42 --dry-run
```

---

## Adding Sound Effects

Drop any `.mp3` file into `caption-automation/sounds/`. The script automatically cycles through all available sounds, one per clip. Use `--sound <name>` (without `.mp3`) to lock all clips to one sound.

---

## Troubleshooting

**"Only X usable videos in category"** — That category doesn't have enough short clips (under 25 seconds). Try a bigger category like Dad Jokes or pick fewer clips with `--count`.

**ffmpeg not found** — Run `brew install ffmpeg` in the terminal.
