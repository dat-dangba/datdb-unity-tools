"""Match design images against the sprites already in the project.

dedupe  - is each candidate image (exported PSD layer / downloaded Figma asset) already a project sprite?
          Exact md5 first, then pixel compare with a small offset search (PSD smart objects often carry a few px of
          baked shadow) at scales 1, 0.5 and 2, then 9-slice (a sprite drawn Sliced; transparent padding is trimmed
          first). Per-sprite data (md5, size, trim box, flat runs) is cached in <project>/Library/datdb-ui/
          sprite_index.json, so only new/changed files are read and a cheap pre-filter skips most pixel compares.
            python -I match_sprites.py dedupe <sprites_root> <candidate.png> [...]

locate  - find where project sprites appear (mostly unoccluded) on a flat mockup. Fast first pass only: sprites that
          are heavily covered or semi-transparent are usually NOT found here; add them with `compose`.
            python -I match_sprites.py locate <sprites_root> <reference.png> <out_dir>

compose - paint a proposed layout (bottom -> top) over white, optionally nudge each layer to the best offset, and
          report what of the mockup is still unexplained. Unexplained blobs are either text or MISSING IMAGES.
            python -I match_sprites.py compose <reference.png> <layout.json> <out_dir> [--refine N]
          layout.json: [{"name": "Popup", "sprite": "/abs/path.png", "x": 148, "y": 313, "w": 784, "h": 1195}, ...]
          (w/h optional = sprite size; x/y = top-left in reference pixels;
           optional "shadow": [dx, dy_down, r, g, b, alpha] mirrors a uGUI Shadow, e.g. [0, 4, 40, 20, 42, 0.52])
          --refine N nudges every layer by up to N px (cost grows with N^2; N=3 takes ~30 s for 9 layers).
          Entries with "type": "text" or "group" are skipped here and passed through to png_spec.py unchanged.
          The refined layout is also saved as <out_dir>/_layout.json (input of png_spec.py).

Outputs go to out_dir: _composite.png (layout render), _residual_mask.png, _unexplained_N.png crops, and JSON on
stdout. Thresholds: "same art" mean RGB diff <= 2; residual pixel when max channel diff > 60; blobs < 150 px ignored.
"""
import glob
import hashlib
import json
import os
import sys
from collections import deque

import numpy as np
from PIL import Image

SAME_ART = 2.0
SLICE_ART = 2.0   # mean |RGBA| diff of a 9-slice rebuild that still counts as the same art
COARSE_PTS = 2000  # opaque pixels sampled per offset before the full exact-match compare
FLAT = 2          # max channel step between neighbour columns/rows of a stretchable middle


def load(path, size=None):
    im = Image.open(path).convert("RGBA")
    if size and tuple(size) != im.size:
        im = im.resize(tuple(size), Image.LANCZOS)
    return np.array(im).astype(np.float32)


def flatten(rgba):
    a = rgba[..., 3:] / 255
    return rgba[..., :3] * a + 255 * (1 - a)


def sprites(root):
    return sorted(glob.glob(os.path.join(root, "**", "*.png"), recursive=True))


def md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def resized(arr, scale):
    if scale == 1.0:
        return arr
    im = Image.fromarray(arr.astype(np.uint8))
    return np.array(im.resize((max(1, round(arr.shape[1] * scale)), max(1, round(arr.shape[0] * scale))),
                              Image.LANCZOS)).astype(np.float32)


def opaque_mask(s):
    m = s[..., 3] > 245
    return m if m.sum() >= 30 else s[..., 3] > 128


# ---------------------------------------------------------------- dedupe
def dedupe(root, candidates):
    for item in dedupe_items(root, candidates):
        print(json.dumps(item))


def flat_run(arr, axis):
    """Longest run of identical lines along axis (1 = columns, 0 = rows) -> (first, last) line index, or None."""
    step = np.abs(np.diff(arr, axis=axis)).max(axis=(0, 2) if axis == 1 else (1, 2)) <= FLAT
    best, start = None, None
    for i, f in enumerate(list(step) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def slice_border(src, w, h):
    """Unity sprite border [left, bottom, right, top] that lets src stretch to w x h, or None."""
    H, W = src.shape[:2]
    lr, bt = (0, 0), (0, 0)
    if w != W:
        run = flat_run(src, 1)
        if run is None:
            return None
        lr = (run[0], W - 1 - run[1])
    if h != H:
        run = flat_run(src, 0)
        if run is None:
            return None
        bt = (H - 1 - run[1], run[0])
    if lr[0] + lr[1] >= w or bt[0] + bt[1] >= h:
        return None
    return [lr[0], bt[0], lr[1], bt[1]]


def slice_render(src, border, w, h):
    """src drawn as a Sliced Image of w x h (the middle is flat, so repeating its first line == stretching)."""
    H, W = src.shape[:2]
    L, B, R, T = border
    cols = list(range(W)) if w == W else list(range(L)) + [L] * (w - L - R) + list(range(W - R, W))
    rows = list(range(H)) if h == H else list(range(T)) + [T] * (h - T - B) + list(range(H - B, H))
    return src[np.ix_(rows, cols)]


def slice_match(src, dst):
    """-> (border, diff) when dst is src drawn Sliced at dst's size, else None."""
    if src.shape == dst.shape:
        return None
    border = slice_border(src, dst.shape[1], dst.shape[0])
    if border is None:
        return None
    rec = slice_render(src, border, dst.shape[1], dst.shape[0])
    m = (rec[..., 3] > 0) | (dst[..., 3] > 0)
    d = float(np.abs(rec[m] - dst[m]).mean()) if m.any() else 255.0
    return (border, round(d, 3)) if d <= SLICE_ART else None


def trim_box(arr):
    """[x0, y0, x1, y1] of the pixels with alpha > 0 (the whole image when it is empty)."""
    ys, xs = np.nonzero(arr[..., 3] > 0)
    if not len(xs):
        return [0, 0, arr.shape[1], arr.shape[0]]
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def slice_info(arr):
    """What the 9-slice pre-filter needs: trimmed box, flat column/row runs and the colour in their middle."""
    x0, y0, x1, y1 = trim_box(arr)
    t = arr[y0:y1, x0:x1]
    cols, rows = flat_run(t, 1), flat_run(t, 0)
    my = (rows[0] + rows[1]) // 2 if rows else t.shape[0] // 2
    mx = (cols[0] + cols[1]) // 2 if cols else t.shape[1] // 2
    return {"size": [arr.shape[1], arr.shape[0]], "box": [x0, y0, x1, y1],
            "cols": list(map(int, cols)) if cols else None, "rows": list(map(int, rows)) if rows else None,
            "mid": [int(v) for v in t[my, mx]]}


def slice_plausible(src, dst):
    """Cheap test on two slice_info dicts: can dst be src drawn Sliced? (No pixels needed.)"""
    ws, hs = src["box"][2] - src["box"][0], src["box"][3] - src["box"][1]
    wd, hd = dst["box"][2] - dst["box"][0], dst["box"][3] - dst["box"][1]
    if (ws, hs) == (wd, hd):
        return False
    if ws != wd and not (src["cols"] and dst["cols"]):
        return False
    if hs != hd and not (src["rows"] and dst["rows"]):
        return False
    return max(abs(a - b) for a, b in zip(src["mid"], dst["mid"])) <= 4


def slice_fit(src, dst, si=None, di=None):
    """slice_match on the trimmed images (transparent padding ignored).
    -> {"slice": border of the WHOLE src sprite, "diff", "offset": [dx, dy] of the Sliced rect inside dst,
        "size": [w, h] of that rect} or None."""
    si, di = si or slice_info(src), di or slice_info(dst)
    if not slice_plausible(si, di):
        return None
    sb, db = si["box"], di["box"]
    r = slice_match(src[sb[1]:sb[3], sb[0]:sb[2]], dst[db[1]:db[3], db[0]:db[2]])
    if not r:
        return None
    (l, b, rr, t), d = r
    W, H = si["size"]
    pl, pt, pr, pb = sb[0], sb[1], W - sb[2], H - sb[3]   # src padding, kept inside the Sliced rect
    sx, sy = sb[2] - sb[0] != db[2] - db[0], sb[3] - sb[1] != db[3] - db[1]
    border = [l + pl if sx else 0, b + pb if sy else 0, rr + pr if sx else 0, t + pt if sy else 0]  # unstretched axis: 0
    return {"slice": border, "diff": d, "offset": [db[0] - pl, db[1] - pt],
            "size": [db[2] - db[0] + pl + pr, db[3] - db[1] + pt + pb]}


def index_path(root):
    """Sprite index cache: <project>/Library/datdb-ui/sprite_index.json (Library is never committed), or
    ~/.cache/datdb-uienv/ when root is not inside a Unity project."""
    d = os.path.abspath(root)
    while os.path.dirname(d) != d:
        if os.path.basename(d) == "Assets":
            return os.path.join(os.path.dirname(d), "Library", "datdb-ui", "sprite_index.json")
        d = os.path.dirname(d)
    key = hashlib.md5(os.path.abspath(root).encode()).hexdigest()[:12]
    return os.path.join(os.path.expanduser("~"), ".cache", "datdb-uienv", f"sprite_index_{key}.json")


INDEX_VERSION = 1


def sprite_index(root):
    """{path: slice_info + "key"} for every sprite under root. Only files whose size/mtime changed are read again."""
    path = index_path(root)
    try:
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
        old = old.get("sprites", {}) if old.get("version") == INDEX_VERSION else {}
    except (OSError, ValueError):
        old = {}
    new = {}
    for p in sprites(root):
        st = os.stat(p)
        key = f"{st.st_size}:{st.st_mtime_ns}"
        e = old.get(p)
        if not e or e.get("key") != key:
            e = dict(slice_info(load(p)), key=key, md5=md5(p))
        new[p] = e
    if new != old:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump({"version": INDEX_VERSION, "sprites": new}, fh)
            os.replace(path + ".tmp", path)
        except OSError:
            pass   # the cache only saves time
    return new


def dedupe_items(root, candidates, own=None):
    """[{candidate, match|None, how|diff, offset, scale, slice?, stale?}] for each candidate png.
    Order: exact match (md5 / pixels, maybe offset or 0.5x/2x) outside `own` (this UI's folder) > 9-slice match
    (`slice` = sprite border; the stale own exact copy goes to `stale`) > exact match in `own` > nothing."""
    out = []
    index = sprite_index(root) if os.path.isdir(root) else {}   # cached per file; pixels load on first real compare
    hashes = {e["md5"]: p for p, e in index.items()}
    sizes = {p: tuple(e["size"]) for p, e in index.items()}
    loaded = {}

    def get(p):
        if p not in loaded:
            loaded[p] = load(p)
        return loaded[p]

    def is_own(p):
        return own is not None and os.path.dirname(os.path.abspath(p)) == os.path.abspath(own)

    for c in candidates:
        a = load(c)
        found = None
        h = md5(c)
        if h in hashes:
            found = {"match": hashes[h], "how": "md5", "offset": [0, 0], "scale": 1.0}
        else:
            for p, (bw, bh) in sizes.items():
                for scale in (1.0, 0.5, 2.0):
                    sw, sh = max(1, round(bw * scale)), max(1, round(bh * scale))
                    if not (0 <= a.shape[1] - sw <= 12 and 0 <= a.shape[0] - sh <= 12):
                        continue
                    b = resized(get(p), scale)
                    m = opaque_mask(b)
                    ys, xs = np.nonzero(m)
                    step = max(1, len(ys) // COARSE_PTS)
                    ys, xs = ys[::step], xs[::step]
                    bs = b[ys, xs, :3]
                    for y in range(a.shape[0] - b.shape[0] + 1):
                        for x in range(a.shape[1] - b.shape[1] + 1):
                            if float(np.abs(a[ys + y, xs + x, :3] - bs).mean()) > 3 * SAME_ART:
                                continue   # a sample of the opaque pixels is already far off: skip the full compare
                            sub = a[y:y + b.shape[0], x:x + b.shape[1]]
                            d = float(np.abs(sub[..., :3][m] - b[..., :3][m]).mean())
                            if d <= SAME_ART and (found is None or d < found["diff"]):
                                found = {"match": p, "diff": round(d, 3), "offset": [x, y], "scale": scale}
        if found is None or is_own(found["match"]):
            best = None
            ai = slice_info(a)
            for p, (bw, bh) in sizes.items():
                if (found and p == found["match"]) or (found and is_own(p)) or (bw, bh) == (a.shape[1], a.shape[0]):
                    continue
                if not slice_plausible(index[p], ai):   # no pixels read for the (many) sprites that can't match
                    continue
                r = slice_fit(get(p), a, index[p], ai)
                if r and (best is None or r["diff"] < best["diff"]):
                    best = {"match": p, "scale": 1.0, **r}
            if best:
                if found:
                    best["stale"] = found["match"]
                found = best
        out.append({"candidate": c, **(found or {"match": None})})
    return out


# ---------------------------------------------------------------- residual / blobs
def report(rgb, canvas, out_dir, extra):
    H, W = rgb.shape[:2]
    resid = np.abs(canvas - rgb).max(axis=2) > 60
    Image.fromarray((resid * 255).astype(np.uint8)).save(os.path.join(out_dir, "_residual_mask.png"))
    Image.fromarray(canvas.astype(np.uint8)).save(os.path.join(out_dir, "_composite.png"))
    grow = resid.copy()
    for _ in range(6):  # merge letters of a word / parts of one graphic
        g = grow.copy()
        g[1:] |= grow[:-1]; g[:-1] |= grow[1:]; g[:, 1:] |= grow[:, :-1]; g[:, :-1] |= grow[:, 1:]
        grow = g
    seen = np.zeros_like(grow)
    blobs = []
    for y0, x0 in zip(*np.nonzero(grow)):
        if seen[y0, x0]:
            continue
        q = deque([(y0, x0)]); seen[y0, x0] = True
        x1 = x2 = x0; y1 = y2 = y0
        while q:
            y, x = q.popleft()
            x1, x2, y1, y2 = min(x1, x), max(x2, x), min(y1, y), max(y2, y)
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < H and 0 <= nx < W and grow[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True; q.append((ny, nx))
        x2 += 1; y2 += 1
        px = int(resid[y1:y2, x1:x2].sum())
        if px < 150:
            continue
        crop = os.path.join(out_dir, f"_unexplained_{len(blobs)}.png")
        Image.fromarray(rgb[y1:y2, x1:x2].astype(np.uint8)).save(crop)
        blobs.append({"bbox": [int(x1), int(y1), int(x2 - x1), int(y2 - y1)], "pixels": px, "crop": crop})
    print(json.dumps({**extra, "mean_diff": round(float(np.abs(canvas - rgb).max(axis=2).mean()), 2),
                      "unexplained": blobs}, indent=1))


def paint(canvas, s, x, y):
    h, w = s.shape[:2]
    a = s[..., 3:] / 255
    region = canvas[y:y + h, x:x + w]
    canvas[y:y + h, x:x + w] = s[..., :3] * a + region * (1 - a)


# ---------------------------------------------------------------- locate
def locate(root, ref_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rgb = flatten(load(ref_path))
    H, W = rgb.shape[:2]
    F = 4
    small = np.array(Image.fromarray(rgb.astype(np.uint8)).resize((W // F, H // F), Image.BOX)).astype(np.float64)
    sh, sw = small.shape[:2]
    img_f = [np.fft.rfft2(small[..., c]) for c in range(3)]
    img2_f = [np.fft.rfft2(small[..., c] ** 2) for c in range(3)]

    def corr(a_f, t):
        full = np.fft.irfft2(a_f * np.fft.rfft2(t[::-1, ::-1], (sh, sw)), (sh, sw))
        return full[t.shape[0] - 1:, t.shape[1] - 1:]

    placed = []
    for p in sprites(root):
        s0 = load(p)
        for scale in (1.0, 0.5):
            s = resized(s0, scale)
            h, w = s.shape[:2]
            if h > H or w > W or h < 2 * F or w < 2 * F:
                continue
            m = s[..., 3] > 245
            if m.sum() < 30:
                continue
            ts = np.array(Image.fromarray(s.astype(np.uint8)).resize((w // F, h // F), Image.BOX)).astype(np.float64)
            tm = (ts[..., 3] > 245).astype(np.float64)
            if tm.sum() < 4:
                continue
            ssd = 0
            for c in range(3):
                tc = ts[..., c] * tm
                ssd = ssd + corr(img2_f[c], tm) - 2 * corr(img_f[c], tc) + (tc * ts[..., c]).sum()
            # circular correlation wraps around: keep only valid positions
            ssd = ssd[:sh - ts.shape[0] + 1, :sw - ts.shape[1] + 1]
            ys_m, xs_m = np.nonzero(m)
            idx = np.linspace(0, len(ys_m) - 1, min(3000, len(ys_m))).astype(int)
            ys_m, xs_m = ys_m[idx], xs_m[idx]
            col = s[ys_m, xs_m, :3]
            hits, tried = [], []
            for flat in np.argsort(ssd, axis=None)[:2000]:
                cy, cx = (int(v) * F for v in np.unravel_index(flat, ssd.shape))
                if any(abs(cx - tx) < max(8, w / 4) and abs(cy - ty) < max(8, h / 4) for tx, ty in tried):
                    continue
                tried.append((cx, cy))
                best = None
                for y in range(max(0, cy - F - 2), min(H - h, cy + F + 2) + 1):
                    for x in range(max(0, cx - F - 2), min(W - w, cx + F + 2) + 1):
                        d = np.abs(rgb[y + ys_m, x + xs_m] - col).max(axis=1)
                        cand = (round(float(np.median(d))), float(d.mean()), x, y)  # median, then mean as tie-break
                        if best is None or cand[:2] < best[:2]:
                            best = cand
                med, mean, x, y = best
                # reject matches that don't stand out from their surroundings
                # (e.g. a white star "found" on plain white background)
                patch = rgb[y:y + h, x:x + w]
                ring = m.copy()
                for _ in range(4):  # thin band just outside the sprite's opaque area
                    g = ring.copy()
                    g[1:] |= ring[:-1]; g[:-1] |= ring[1:]; g[:, 1:] |= ring[:, :-1]; g[:, :-1] |= ring[:, 1:]
                    ring = g
                ring &= s[..., 3] < 10
                contrast = float(np.abs(patch[m].mean(axis=0) - patch[ring].mean(axis=0)).max()) if ring.any() else 255
                if med <= 6 and contrast >= 15:
                    hits.append(best)
                if len(hits) >= 6 or len(tried) >= 40:
                    break
            for med, mean, x, y in hits:
                placed.append({"sprite": p, "scale": scale, "x": x, "y": y, "w": w, "h": h,
                               "mean": round(mean, 2), "median": round(med, 2)})
    # one sprite per slot: prefer lower mean diff (e.g. two versions of the same rectangle)
    placed.sort(key=lambda r: r["mean"])
    final = []
    for r in placed:
        if not any(abs(f["x"] - r["x"]) < 20 and abs(f["y"] - r["y"]) < 20 and abs(f["w"] - r["w"]) < 40
                   and abs(f["h"] - r["h"]) < 40 for f in final):
            final.append(r)
    canvas = np.full_like(rgb, 255.0)
    for r in sorted(final, key=lambda r: -r["w"] * r["h"]):
        paint(canvas, resized(load(r["sprite"]), r["scale"]) if r["scale"] != 1 else load(r["sprite"]), r["x"], r["y"])
    report(rgb, canvas, out_dir, {"placed": final})


# ---------------------------------------------------------------- compose
def compose(ref_path, layout_path, out_dir, refine):
    os.makedirs(out_dir, exist_ok=True)
    rgb = flatten(load(ref_path))
    H, W = rgb.shape[:2]
    layout = json.load(open(layout_path, encoding="utf-8"))
    layers, passthrough = [], {}
    for i, L in enumerate(layout):
        if L.get("type") in ("text", "group"):
            passthrough[i] = L
            continue
        s = load(L["sprite"], (L["w"], L["h"]) if "w" in L and "h" in L else None)
        layers.append({**L, "w": s.shape[1], "h": s.shape[0], "_s": s})

    def render(skip=None):
        c = np.full_like(rgb, 255.0)
        for i, L in enumerate(layers):
            if i == skip:
                continue
            if "shadow" in L:  # uGUI Shadow: [dx, dy_down, r, g, b, a]
                dx, dy, r, g, b, a = L["shadow"]
                sh = np.zeros_like(L["_s"])
                sh[..., 0], sh[..., 1], sh[..., 2] = r, g, b
                sh[..., 3] = L["_s"][..., 3] * a
                sx, sy = L["x"] + int(dx), L["y"] + int(dy)
                if 0 <= sx and 0 <= sy and sx + L["w"] <= W and sy + L["h"] <= H:
                    paint(c, sh, sx, sy)
            paint(c, L["_s"], L["x"], L["y"])
        return c

    if refine:
        # coordinate descent: move one layer at a time within +-refine px, minimizing error in its bbox
        for _ in range(2):
            for i, L in enumerate(layers):
                best = None
                for dy in range(-refine, refine + 1):
                    for dx in range(-refine, refine + 1):
                        x, y = L["x"] + dx, L["y"] + dy
                        if x < 0 or y < 0 or x + L["w"] > W or y + L["h"] > H:
                            continue
                        old = (L["x"], L["y"]); L["x"], L["y"] = x, y
                        c = render()
                        x1, y1 = max(0, x - refine), max(0, y - refine)
                        x2, y2 = min(W, x + L["w"] + refine), min(H, y + L["h"] + refine)
                        e = float(np.abs(c[y1:y2, x1:x2] - rgb[y1:y2, x1:x2]).mean())
                        L["x"], L["y"] = old
                        if best is None or e < best[0]:
                            best = (e, x, y)
                L["x"], L["y"] = best[1], best[2]
    out = [{k: v for k, v in L.items() if k != "_s"} for L in layers]
    for i in sorted(passthrough):   # back in their original order
        out.insert(i, passthrough[i])
    with open(os.path.join(out_dir, "_layout.json"), "w", encoding="utf-8") as f:
        json.dump({"reference": os.path.abspath(ref_path), "layout": out}, f, ensure_ascii=False, indent=1)
    report(rgb, render(), out_dir, {"layout": out})


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "dedupe":
        dedupe(sys.argv[2], sys.argv[3:])
    elif mode == "locate":
        locate(sys.argv[2], sys.argv[3], sys.argv[4])
    elif mode == "compose":
        n = int(sys.argv[sys.argv.index("--refine") + 1]) if "--refine" in sys.argv else 0
        compose(sys.argv[2], sys.argv[3], sys.argv[4], n)
    else:
        sys.exit(__doc__)
