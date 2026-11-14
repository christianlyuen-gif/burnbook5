"""Soot score for flame images: how much of the visible flame glows yellow, orange or white rather than blue.

Blue light in a flame comes from excited molecules in the reaction zone (CH, C2). Yellow, orange and white light
is glowing soot. So the share of flame pixels in the soot colours is a simple, repeatable proxy for how sooty a
flame is. It is image processing, not AI: the same image always gives the same number.

Run from burnbook/:
    python scripts/soot_score.py MANIFEST.csv [--overlays DIR]

MANIFEST.csv columns: path, image_id, image_set, investigation, date, crop_top, exclude_reason
(crop_top = rows to ignore at the top, e.g. 80 for the SPICE/BASS video text overlay;
 exclude_reason = why an image gets no score, e.g. lit hardware in frame. Excluded images are still measured.)

Writes data/soot_scores.csv. With --overlays, also writes a copy of each image with soot pixels tinted orange and
blue pixels tinted cyan, so anyone can check what was counted.

Limits, stated in every output row's set: scores depend on camera exposure and white balance, so compare images
from the same camera set; saturated cores read as white and count as soot; bloom around bright flames adds area.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

DATA = Path(__file__).resolve().parent.parent / "data"

# thresholds (fractions of full scale); chosen by eye on overlay images, then fixed for every image
V_MIN = 0.20          # dimmer pixels are background
SAT_WHITE = 0.25      # below this saturation, a bright pixel is 'white'
V_WHITE = 0.80        # ... if it is at least this bright (a saturated incandescent core)
SOOT_HUE = (330, 75)  # degrees, wrapping through red: red, orange, yellow
BLUE_HUE = (165, 265) # cyan to blue
MIN_FLAME_PX = 2000   # fewer classified flame pixels than this (a very dim flame) and no score is given


def classify(img: Image.Image, crop_top: int = 0):
    """Return (soot_mask, blue_mask, flame_mask) as boolean arrays."""
    img = img.convert("RGB")
    if crop_top:
        img = img.crop((0, crop_top, img.width, img.height))
    img = img.filter(ImageFilter.MedianFilter(3))  # removes single hot pixels from camera noise
    hsv = np.asarray(img.convert("HSV")).astype(float) / 255.0
    h, s, v = hsv[..., 0] * 360.0, hsv[..., 1], hsv[..., 2]
    flame = v >= V_MIN
    white = flame & (s < SAT_WHITE) & (v >= V_WHITE)
    soot_hue = flame & (s >= SAT_WHITE) & ((h >= SOOT_HUE[0]) | (h <= SOOT_HUE[1]))
    soot = white | soot_hue
    blue = flame & (s >= SAT_WHITE) & (h >= BLUE_HUE[0]) & (h <= BLUE_HUE[1]) & ~soot
    return soot, blue, flame, img


def score_image(path: str, crop_top: int = 0) -> dict:
    soot, blue, flame, _ = classify(Image.open(path), crop_top)
    n_s, n_b, n_f = int(soot.sum()), int(blue.sum()), int(flame.sum())
    counted = n_s + n_b
    return {
        "soot_px": n_s, "blue_px": n_b, "flame_px": n_f,
        "unclassified_frac": round(1 - counted / n_f, 3) if n_f else None,
        "soot_score": round(n_s / counted, 3) if counted >= MIN_FLAME_PX else None,
    }


def overlay(path: str, out: Path, crop_top: int = 0, width: int = 480):
    soot, blue, flame, img = classify(Image.open(path), crop_top)
    a = np.asarray(img).astype(float)
    tint = a * 0.35
    tint[soot] = [255, 140, 20]
    tint[blue] = [40, 200, 255]
    left = img.copy()
    right = Image.fromarray(tint.astype(np.uint8))
    pair = Image.new("RGB", (img.width * 2 + 8, img.height), (255, 255, 255))
    pair.paste(left, (0, 0))
    pair.paste(right, (img.width + 8, 0))
    pair.thumbnail((width * 2, width * 2))
    pair.save(out, quality=85)


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    over = Path(argv[argv.index("--overlays") + 1]) if "--overlays" in argv else None
    if over:
        over.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(argv[1], newline="", encoding="utf-8") as f:
        for m in csv.DictReader(f):
            ct = int(m.get("crop_top") or 0)
            r = score_image(m["path"], ct)
            reason = (m.get("exclude_reason") or "").strip()
            if not reason and r["soot_score"] is None:
                reason = "too dim: fewer than %d classified flame pixels" % MIN_FLAME_PX
            if reason:
                r["soot_score"] = None
            rows.append({"image_id": m["image_id"], "image_set": m["image_set"], "investigation": m["investigation"],
                         "date": m["date"], **r, "excluded_because": reason,
                         "method": f"HSV: flame V>={V_MIN}; soot = hue {SOOT_HUE[0]}-{SOOT_HUE[1]} deg or white (S<{SAT_WHITE}, V>={V_WHITE}); blue = hue {BLUE_HUE[0]}-{BLUE_HUE[1]} deg; 3x3 median filter"})
            if over:
                overlay(m["path"], over / f"{m['image_id']}.jpg", ct)
    with open(DATA / "soot_scores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote data/soot_scores.csv ({len(rows)} images)")


if __name__ == "__main__":
    main(sys.argv)
