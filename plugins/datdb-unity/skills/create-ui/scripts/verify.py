"""Check a UIBuilder build: diff vs the reference, plus one contact sheet and one stroke close-up sheet to look at.

Usage: python -I verify.py <out_dir>        (reads spec.json + report.json written there)
Prints JSON: mean diff over the content box (where the reference or the render has ink; the white margin would
dilute it), pass (content mean <= PASS), sheet paths, text warnings.
Look at sheet.png always; strokes.png when there are outlined / shadowed / gradient texts; heatmap.png only when it fails.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

PASS = 5.0   # content-box mean; the known-good BoosterUI PSD build is 3.3 here (1.5 over the whole frame)

out = os.path.abspath(sys.argv[1])
spec = json.load(open(os.path.join(out, "spec.json"), encoding="utf-8"))
rep = json.load(open(os.path.join(out, "report.json"), encoding="utf-8"))
if not rep.get("ok"):
    print(json.dumps({"ok": False, "errors": rep.get("errors")}, indent=1))
    sys.exit(1)

ref = Image.open(spec["reference"]).convert("RGBA")
bg = Image.new("RGBA", ref.size, (255, 255, 255, 255))
bg.alpha_composite(ref)
a = np.array(bg.convert("RGB")).astype(int)
render = Image.open(os.path.join(out, "render.png")).convert("RGB").resize(ref.size)
d = np.abs(a - np.array(render).astype(int)).max(axis=2)
ink = np.nonzero((a.min(axis=2) < 250) | (np.array(render).min(axis=2) < 250))
if len(ink[0]):
    box = (max(0, ink[1].min() - 10), max(0, ink[0].min() - 10), min(ref.width, ink[1].max() + 10), min(ref.height, ink[0].max() + 10))
else:
    box = (0, 0, ref.width, ref.height)
content = d[box[1]:box[3], box[0]:box[2]]
mean = float(content.mean())
heat = Image.fromarray(np.clip(d * 4, 0, 255).astype(np.uint8)).convert("RGB")
heat.save(os.path.join(out, "heatmap.png"))

# contact sheet: render | heatmap | variants, cropped to the content
panels = [render, heat] + [Image.open(p).convert("RGB").resize(ref.size) for p in rep["renders"]
                            if os.path.basename(p).startswith("render_") and not p.endswith("_2x.png")]
crops = [p.crop(box) for p in panels]
H = 700
crops = [c.resize((max(1, round(c.width * H / c.height)), H)) for c in crops]
sheet = Image.new("RGB", (sum(c.width for c in crops) + 10 * (len(crops) - 1), H), "white")
x = 0
for c in crops:
    sheet.paste(c, (x, 0))
    x += c.width + 10
sheet.save(os.path.join(out, "sheet.png"))

# stroke close-ups from the 2x render
strokes = None
r2 = os.path.join(out, "render_2x.png")
stroked = [t for t in rep["texts"] if (t["stroke_px"] > 0 or t.get("underlay") or t.get("gradient")) and t["visible"]]
if stroked and os.path.exists(r2):
    big = Image.open(r2).convert("RGB")
    tiles = []
    for t in stroked:
        x0, y0, w, h = t["rect"]
        pad = t["stroke_px"] + (16 if t.get("underlay") else 8)
        tiles.append(big.crop((int((x0 - pad) * 2), int((y0 - pad) * 2), int((x0 + w + pad) * 2), int((y0 + h + pad) * 2))))
    sh = Image.new("RGB", (max(t.width for t in tiles), sum(t.height for t in tiles) + 6 * len(tiles)), "white")
    y = 0
    for t in tiles:
        sh.paste(t, (0, y))
        y += t.height + 6
    strokes = os.path.join(out, "strokes.png")
    sh.save(strokes)

print(json.dumps({
    "ok": True, "mean_diff": round(mean, 2), "mean_diff_frame": round(float(d.mean()), 2), "content_box": list(map(int, box)),
    "pixels_over_40": int((d > 40).sum()), "pass": mean <= PASS,
    "sheet": os.path.join(out, "sheet.png"), "strokes": strokes, "heatmap": os.path.join(out, "heatmap.png"),
    "warnings": rep.get("warnings"),
}, ensure_ascii=False, indent=1))
