#!/usr/bin/env python3
"""
Generate background images and transparent prop stickers for a joke theme
using OpenAI's gpt-image-1 model.

Backgrounds: 1024x1536 portrait scene images (scaled/cropped to 1080x1920 in ffmpeg)
Props:       1024x1024 transparent PNG stickers

Output layout:
    assets/{theme}/backgrounds/bg_01.png … bg_N.png
    assets/{theme}/props/prop_01.png    … prop_N.png

Usage:
    python3 caption-automation/generate_assets.py "Animals"
    python3 caption-automation/generate_assets.py "Animals" --backgrounds 3 --props 3
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI

CONFIG = Path.home() / "TellMeAJoke/config.json"
ASSETS = Path.home() / "TellMeAJoke/assets"

# ── Theme prompt library ───────────────────────────────────────────────────────
# Add new themes here as you expand the library.
THEME_DEFS: dict[str, dict[str, list[str]]] = {
    "animals": {
        "backgrounds": [
            "Dense tropical rainforest, lush green canopy, dappled sunlight filtering through leaves, photorealistic, no people, portrait orientation, cinematic",
            "Rustic wooden barn interior at golden hour, warm light, hay bales, dust particles, photorealistic, no people, portrait orientation",
            "Crystal clear shallow ocean water, colourful coral reef visible below, bright blue sky above, photorealistic, no people, portrait orientation",
            "African savanna at sunset, golden grass, silhouette of acacia tree, dramatic orange sky, photorealistic, no people, portrait orientation",
            "Misty old-growth forest, towering ancient trees, green moss, shafts of light, photorealistic, no people, portrait orientation",
        ],
        "props": [
            "A cute cartoon dog doing a big confused head-tilt, sticker style, white outline, isolated on transparent background",
            "A cartoon cat wearing oversized sunglasses, looking smug, sticker style, transparent background",
            "A cartoon chicken with a surprised wide-open beak, sticker style, transparent background",
            "A cartoon bear giving a big enthusiastic thumbs-up and grinning, sticker style, transparent background",
            "A cartoon cow with a dopey grin and crossed eyes, sticker style, transparent background",
        ],
    },
    "polish": {
        "backgrounds": [
            "Warsaw Old Town market square, colourful historic facades, cobblestone street, golden hour light, photorealistic, no people, portrait orientation",
            "Polish countryside, rolling wheat fields, wooden farmhouse, dramatic cloudy sky, photorealistic, no people, portrait orientation",
            "Wawel Castle in Kraków, stone walls, lush green hill, river below, blue sky, photorealistic, no people, portrait orientation",
            "Zakopane wooden mountain village, Tatra mountains behind, pine trees, snow on peaks, photorealistic, no people, portrait orientation",
            "Traditional Polish folk textile pattern, red and white geometric embroidery, close-up texture, photorealistic, portrait orientation",
        ],
        "props": [
            "Polish white eagle national emblem, bold heraldic style, sticker with white outline, isolated on transparent background",
            "A steaming bowl of borscht soup, cartoon sticker style, white outline, isolated on transparent background",
            "A plate of pierogi dumplings, cute cartoon sticker style, white outline, isolated on transparent background",
            "Polish red and white flag waving, cartoon sticker style, white outline, isolated on transparent background",
            "A cartoon vodka bottle with a Polish label, sticker style, white outline, isolated on transparent background",
        ],
    },
    "mexican": {
        "backgrounds": [
            "Vibrant Mexican mercado street, colourful papel picado banners, warm light, photorealistic, no people, portrait orientation",
            "Chichen Itza pyramid at sunrise, dramatic light, lush jungle surrounding, photorealistic, no people, portrait orientation",
            "Mexican hacienda courtyard, terracotta tiles, bougainvillea flowers, fountain, photorealistic, no people, portrait orientation",
            "Sonoran desert landscape, tall saguaro cacti, orange sunset sky, photorealistic, no people, portrait orientation",
            "Guanajuato colourful colonial street, pink yellow blue buildings, steep hill, photorealistic, no people, portrait orientation",
        ],
        "props": [
            "A large colourful sombrero hat, cartoon sticker style, white outline, isolated on transparent background",
            "A cartoon taco overflowing with toppings, sticker style, white outline, isolated on transparent background",
            "A smiling cartoon cactus wearing a sombrero, sticker style, white outline, isolated on transparent background",
            "Maracas pair, bright colours, cartoon sticker style, white outline, isolated on transparent background",
            "A cartoon Lucha Libre wrestling mask, colourful, sticker style, white outline, isolated on transparent background",
        ],
    },
    "chinese": {
        "backgrounds": [
            "Great Wall of China winding over misty green mountains, dramatic morning light, photorealistic, no people, portrait orientation",
            "Shanghai Bund at night, neon reflections on the Huangpu river, glittering skyline, photorealistic, no people, portrait orientation",
            "Dense bamboo forest, green light filtering through tall stalks, mist, photorealistic, no people, portrait orientation",
            "Traditional Chinese lantern festival street, hundreds of red lanterns glowing at night, photorealistic, no people, portrait orientation",
            "Zhangjiajie floating mountains, dramatic vertical pillars, pine trees, morning mist, photorealistic, no people, portrait orientation",
        ],
        "props": [
            "A cute cartoon panda bear sitting and eating bamboo, sticker style, white outline, isolated on transparent background",
            "A glowing red Chinese paper lantern, cartoon sticker style, white outline, isolated on transparent background",
            "A cartoon fortune cookie cracked open with a paper message, sticker style, white outline, isolated on transparent background",
            "A cartoon Chinese dragon, colourful and friendly, sticker style, white outline, isolated on transparent background",
            "Cartoon chopsticks holding a dumpling, sticker style, white outline, isolated on transparent background",
        ],
    },
    "blonde": {
        "backgrounds": [
            "Glittery pink and gold Hollywood-style backdrop, stars and sparkles, illustration, portrait orientation",
            "A bright sunny beach with palm trees and pastel colours, flat cartoon illustration, portrait orientation",
            "A luxury salon interior with mirrors and pink decor, cartoon style, no people, portrait orientation",
            "Confetti and balloons in pink, gold, white, festive party scene, illustration, portrait orientation",
            "A glamorous red carpet with spotlights and stars, flat illustration, no people, portrait orientation",
        ],
        "props": [
            "A cartoon diploma with a big red X through it, sticker style, transparent background",
            "A cartoon lightbulb with a question mark instead of a glow, sticker style, transparent background",
            "A cartoon thinking emoji face with exaggerated confused eyebrows, sticker style, transparent background",
            "A cartoon hair dryer blowing sparkles, sticker style, transparent background",
            "A cartoon trophy labelled 'Tried', sticker style, transparent background",
        ],
    },
    "dad_jokes": {
        "backgrounds": [
            "A cozy suburban garage with tools on a pegboard, cartoon style, no people, portrait orientation",
            "A sunny backyard barbecue scene, lawn chairs and a grill, flat illustration, no people, portrait orientation",
            "A retro 1970s living room with a plaid couch and wood panelling, cartoon style, no people, portrait orientation",
            "A cartoon newspaper front page background, black and white with bold headlines, portrait orientation",
            "A cheerful hardware store interior with shelves of tools, flat illustration, no people, portrait orientation",
        ],
        "props": [
            "A cartoon dad wearing a 'World's Greatest Dad' baseball cap, sticker style, transparent background",
            "A cartoon pair of cargo shorts with many pockets, sticker style, transparent background",
            "A cartoon groan face — eyes shut, mouth open in agony, sticker style, transparent background",
            "A cartoon wooden pun trophy with a bad joke medal, sticker style, transparent background",
            "A cartoon thumbs-up hand wearing a wedding ring, sticker style, transparent background",
        ],
    },
}


# ── Local (Pillow) asset definitions ─────────────────────────────────────────
# Each background entry: gradient top/bottom RGB.
# Each prop entry: base colour + shape key used by make_prop_sticker().

LOCAL_THEME_ASSETS: dict[str, dict] = {
    "animals": {
        "backgrounds": [
            {"label": "Jungle",    "top": (20,  90,  20),  "bottom": (70, 160,  50)},
            {"label": "Ocean",     "top": (0,   80, 180),  "bottom": (60, 190, 220)},
            {"label": "Barnyard",  "top": (180, 90,  30),  "bottom": (230, 155, 70)},
            {"label": "Savanna",   "top": (210, 175, 50),  "bottom": (165, 125, 35)},
            {"label": "Forest",    "top": (15,  55,  15),  "bottom": (45, 115,  45)},
        ],
        "props": [
            {"label": "Confused Dog",      "color": (220, 180, 100), "shape": "dog"},
            {"label": "Cool Cat",          "color": (155, 155, 165), "shape": "cat"},
            {"label": "Surprised Chicken", "color": (240, 160,  80), "shape": "chicken"},
            {"label": "Happy Bear",        "color": (160, 110,  70), "shape": "bear"},
            {"label": "Derpy Cow",         "color": (240, 240, 235), "shape": "cow"},
        ],
    },
    "blonde": {
        "backgrounds": [
            {"label": "Pink Glam",   "top": (230, 100, 170), "bottom": (255, 190, 220)},
            {"label": "Beach",       "top": (70,  180, 230), "bottom": (255, 235, 150)},
            {"label": "Salon",       "top": (245, 180, 210), "bottom": (200, 130, 170)},
            {"label": "Confetti",    "top": (255, 215,   0), "bottom": (255, 140,   0)},
            {"label": "Red Carpet",  "top": (180,  20,  20), "bottom": (90,   10,  10)},
        ],
        "props": [
            {"label": "X Diploma",   "color": (255, 230, 100), "shape": "diploma"},
            {"label": "Dim Bulb",    "color": (255, 255, 180), "shape": "bulb"},
            {"label": "Confused",    "color": (180, 220, 255), "shape": "think"},
            {"label": "Hair Dryer",  "color": (255, 160, 190), "shape": "dryer"},
            {"label": "Tried Trophy","color": (200, 170,  80), "shape": "trophy"},
        ],
    },
    "dad_jokes": {
        "backgrounds": [
            {"label": "Garage",     "top": (100, 110, 120), "bottom": (160, 165, 170)},
            {"label": "Backyard",   "top": (80,  175,  80), "bottom": (200, 230, 120)},
            {"label": "Retro LR",   "top": (160, 110,  60), "bottom": (200, 155,  90)},
            {"label": "Newspaper",  "top": (230, 225, 210), "bottom": (200, 195, 180)},
            {"label": "Hardware",   "top": (210, 140,  50), "bottom": (240, 190, 100)},
        ],
        "props": [
            {"label": "Dad Cap",    "color": (50,  100, 200), "shape": "cap"},
            {"label": "Cargo Short","color": (100, 130,  80), "shape": "shorts"},
            {"label": "Groan Face", "color": (255, 220, 100), "shape": "groan"},
            {"label": "Pun Trophy", "color": (200, 170,  60), "shape": "trophy"},
            {"label": "Thumbs Up",  "color": (255, 210, 120), "shape": "thumbsup"},
        ],
    },
}


# ── Local background generation ───────────────────────────────────────────────

def make_gradient_bg(top: tuple, bottom: tuple, w: int = 1080, h: int = 1920) -> Image.Image:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for c in range(3):
        col = np.linspace(top[c], bottom[c], h, dtype=np.float32)
        arr[:, :, c] = col[:, np.newaxis].astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    # Add a subtle vignette (darkened corners) so it reads as a scene
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for i in range(30):
        alpha = int(100 * (i / 30) ** 2)
        margin = i * 8
        vd.rectangle([margin, margin, w - margin, h - margin],
                     outline=(0, 0, 0, alpha), width=8)
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, vignette)
    return img.convert("RGB")


# ── Local prop (sticker) generation ──────────────────────────────────────────

def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/Library/Fonts/Arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _circle(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill: tuple) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def make_prop_sticker(shape: str, color: tuple, size: int = 500) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    r  = size // 2 - 25
    dk = tuple(max(0, c - 60) for c in color)   # darker shade for outlines/features
    wh = (255, 255, 255, 255)
    bl = (30, 30, 30, 255)
    c4 = (*color, 255)
    d4 = (*dk, 255)

    if shape in ("dog", "cat", "bear", "cow", "chicken"):
        # ── ears ──
        if shape == "dog":
            _circle(draw, cx - r + 15, cy - r + 30, 45, c4)
            _circle(draw, cx + r - 15, cy - r + 30, 45, c4)
        elif shape == "cat":
            # triangle ears
            draw.polygon([(cx - r + 10, cy - r + 50), (cx - r + 50, cy - r - 10),
                          (cx - r + 70, cy - r + 50)], fill=c4)
            draw.polygon([(cx + r - 10, cy - r + 50), (cx + r - 50, cy - r - 10),
                          (cx + r - 70, cy - r + 50)], fill=c4)
        elif shape == "bear":
            _circle(draw, cx - r + 20, cy - r + 20, 35, c4)
            _circle(draw, cx + r - 20, cy - r + 20, 35, c4)
        elif shape == "cow":
            _circle(draw, cx - r + 10, cy - r + 10, 40, c4)
            _circle(draw, cx + r - 10, cy - r + 10, 40, c4)

        # ── head ──
        _circle(draw, cx, cy, r, c4)

        if shape == "cow":
            # black patches
            _circle(draw, cx - 40, cy - 30, 40, bl)
            _circle(draw, cx + 50, cy + 20, 35, bl)

        # ── eyes ──
        if shape == "chicken":
            # oval beak, different face layout
            _circle(draw, cx, cy, r, (*color, 255))
            draw.ellipse([cx - 25, cy + 20, cx + 25, cy + 55],
                         fill=(240, 160, 40, 255))   # beak
            draw.ellipse([cx - 55, cy - 50, cx - 15, cy - 10], fill=wh)
            draw.ellipse([cx + 15, cy - 50, cx + 55, cy - 10], fill=wh)
            draw.ellipse([cx - 45, cy - 42, cx - 25, cy - 22], fill=bl)
            draw.ellipse([cx + 25, cy - 42, cx + 45, cy - 22], fill=bl)
            # surprised eyebrows
            draw.arc([cx - 60, cy - 75, cx - 10, cy - 45], 200, 340,
                     fill=bl, width=5)
            draw.arc([cx + 10, cy - 75, cx + 60, cy - 45], 200, 340,
                     fill=bl, width=5)
        else:
            eye_y = cy - 30
            draw.ellipse([cx - 65, eye_y - 25, cx - 20, eye_y + 20], fill=wh)
            draw.ellipse([cx + 20, eye_y - 25, cx + 65, eye_y + 20], fill=wh)
            # pupils
            if shape == "cow":   # X eyes for derpy
                draw.line([cx - 57, eye_y - 18, cx - 28, eye_y + 12], fill=bl, width=5)
                draw.line([cx - 28, eye_y - 18, cx - 57, eye_y + 12], fill=bl, width=5)
                draw.line([cx + 28, eye_y - 18, cx + 57, eye_y + 12], fill=bl, width=5)
                draw.line([cx + 57, eye_y - 18, cx + 28, eye_y + 12], fill=bl, width=5)
            else:
                draw.ellipse([cx - 52, eye_y - 12, cx - 30, eye_y + 10], fill=bl)
                draw.ellipse([cx + 30, eye_y - 12, cx + 52, eye_y + 10], fill=bl)
            # ── nose / mouth ──
            _circle(draw, cx, cy + 20, 18, d4)
            if shape == "dog":
                # confused tilted mouth
                draw.arc([cx - 35, cy + 45, cx + 10, cy + 85], 210, 330, fill=bl, width=5)
                # question mark
                draw.text((cx + 65, cy - r + 20), "?", fill=(220, 50, 50, 230), font=_font(90))
            elif shape == "cat":
                draw.arc([cx - 25, cy + 45, cx + 25, cy + 80], 190, 350, fill=bl, width=4)
                draw.text((cx + 65, cy - r + 20), "B)", fill=(50, 50, 50, 200), font=_font(60))
            elif shape == "bear":
                draw.arc([cx - 30, cy + 45, cx + 30, cy + 80], 15, 165, fill=bl, width=5)
                draw.text((cx + 60, cy + r - 60), "👍", fill=(50, 50, 50, 200), font=_font(70))
            elif shape == "cow":
                draw.arc([cx - 30, cy + 45, cx + 30, cy + 80], 15, 165, fill=bl, width=5)

    elif shape in ("diploma", "bulb", "think", "dryer", "trophy", "cap",
                   "shorts", "groan", "thumbsup"):
        # Generic sticker: coloured circle + label text
        _circle(draw, cx, cy, r, c4)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=d4, width=6)
        label_map = {
            "diploma":  "📜\n✗",  "bulb":    "💡\n?",  "think":  "🤔",
            "dryer":    "💨",      "trophy":  "🏆",     "cap":    "🧢",
            "shorts":   "👖",      "groan":   "😖",     "thumbsup": "👍",
        }
        txt = label_map.get(shape, shape)
        draw.text((cx, cy), txt, fill=bl, font=_font(120), anchor="mm")

    return img


def generate_local_batch(defs: list[dict], out_dir: Path, prefix: str, kind: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, entry in enumerate(defs):
        out_path = out_dir / f"{prefix}_{i + 1:02d}.png"
        if out_path.exists():
            print(f"  skip  {out_path.name}  (already exists)")
            continue
        print(f"  gen   {out_path.name}  ({entry['label']}) …", end=" ", flush=True)
        if kind == "background":
            img = make_gradient_bg(entry["top"], entry["bottom"])
        else:
            img = make_prop_sticker(entry["shape"], entry["color"])
        img.save(out_path)
        print("ok")


# ── helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG.exists():
        print("config.json not found. Copy config.json.example and fill in your keys.")
        sys.exit(1)
    with open(CONFIG) as f:
        return json.load(f)


def theme_slug(name: str) -> str:
    return name.lower().strip().replace(" ", "_").replace("/", "_")


def generate_image(client: OpenAI, prompt: str, size: str, transparent: bool) -> bytes:
    kwargs: dict = dict(
        model="gpt-image-1",
        prompt=prompt,
        size=size,
        quality="medium",
        n=1,
    )
    if transparent:
        kwargs["background"] = "transparent"
    response = client.images.generate(**kwargs)
    return base64.b64decode(response.data[0].b64_json)


def generate_batch(
    client: OpenAI,
    prompts: list[str],
    out_dir: Path,
    prefix: str,
    size: str,
    transparent: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, prompt in enumerate(prompts):
        out_path = out_dir / f"{prefix}_{i + 1:02d}.png"
        if out_path.exists():
            print(f"  skip  {out_path.name}  (already exists)")
            continue
        print(f"  gen   {out_path.name} …", end=" ", flush=True)
        data = generate_image(client, prompt, size, transparent)
        out_path.write_bytes(data)
        print(f"{len(data) // 1024} KB")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate background + prop assets for a joke theme."
    )
    parser.add_argument("theme", help="Theme name, e.g. 'Animals'")
    parser.add_argument("--backgrounds", type=int, default=5, metavar="N")
    parser.add_argument("--props",       type=int, default=5, metavar="N")
    parser.add_argument("--local", action="store_true",
                        help="Generate placeholder assets locally using Pillow (no API key needed).")
    args = parser.parse_args()

    slug = theme_slug(args.theme)
    base = ASSETS / slug

    print(f"\nTheme       : {args.theme}")
    print(f"Output dir  : {base}")
    print(f"Mode        : {'local (Pillow)' if args.local else 'API (gpt-image-1)'}")
    print(f"Backgrounds : {args.backgrounds}")
    print(f"Props       : {args.props}\n")

    if args.local:
        if slug not in LOCAL_THEME_ASSETS:
            available = ", ".join(LOCAL_THEME_ASSETS.keys())
            print(f"No local definitions for '{args.theme}'. Available: {available}")
            sys.exit(1)
        local_defs = LOCAL_THEME_ASSETS[slug]
        print("── Backgrounds ──")
        generate_local_batch(local_defs["backgrounds"][: args.backgrounds],
                             base / "backgrounds", "bg", "background")
        print("\n── Props ──")
        generate_local_batch(local_defs["props"][: args.props],
                             base / "props", "prop", "prop")
    else:
        config  = load_config()
        api_key = config.get("openai_api_key", "")
        if not api_key or "YOUR" in api_key:
            print("Error: set openai_api_key in config.json  (or run with --local).")
            sys.exit(1)
        client = OpenAI(api_key=api_key)
        if slug not in THEME_DEFS:
            available = ", ".join(THEME_DEFS.keys())
            print(f"No API prompts defined for '{args.theme}'. Available: {available}")
            sys.exit(1)
        defs         = THEME_DEFS[slug]
        bg_prompts   = defs["backgrounds"][: args.backgrounds]
        prop_prompts = defs["props"][: args.props]
        print("── Backgrounds ──")
        generate_batch(client, bg_prompts,   base / "backgrounds", "bg",   "1024x1536", transparent=False)
        print("\n── Props ──")
        generate_batch(client, prop_prompts, base / "props",       "prop", "1024x1024", transparent=True)

    print(f"\nDone. Assets saved to {base}/\n")


if __name__ == "__main__":
    main()
