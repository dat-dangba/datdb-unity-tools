"""Shared pieces of the spec writers (make_spec.py for PSD, figma_spec.py for Figma, png_spec.py for PNG mockups).

Not a script. Every writer produces the same spec.json (reference/spec.md) through these helpers, so dedupe, the
Common/ moves, button labels, variants and the field defaults behave the same whatever the source.
"""
import colorsys
import json
import os
import re

import numpy as np
from PIL import Image

import match_sprites

UI_ROOT = "Assets/_Project/Images/UI"
FONTS_DIR = "Assets/_Project/Fonts"
PREFAB_DIR = "Assets/_Project/Prefabs/UI"
SHADOW = [0, 4, 40, 20, 42, 0.52]   # the project's usual drop shadow, used when a reused sprite sits 3-7 px inside


def color_name(rgb):
    r, g, b = (v / 255 for v in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h *= 360
    if v < 0.2:
        return "Black"
    if s < 0.15:
        return "White" if v > 0.85 else "Gray"
    if 15 <= h < 45 and v < 0.55:
        return "Brown"
    for limit, name in ((15, "Red"), (45, "Orange"), (70, "Yellow"), (165, "Green"), (195, "Cyan"),
                        (255, "Blue"), (290, "Purple"), (340, "Pink"), (361, "Red")):
        if h < limit:
            return name


def file_stem(name):
    return re.sub(r"[^A-Za-z0-9_\-]+", "", name) or "layer"


def same_pixels(a_path, b_path):
    a = np.asarray(Image.open(a_path).convert("RGBA")).astype(int)
    b = np.asarray(Image.open(b_path).convert("RGBA")).astype(int)
    return a.shape == b.shape and np.abs(a - b).mean() <= match_sprites.SAME_ART


def overlap_frac(a, b):
    """a, b = [x, y, w, h]; intersection / smaller area."""
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    small = min(a[2] * a[3], b[2] * b[3])
    return ix * iy / small if small > 0 else 0


def unique_name(parent, name, used, warnings):
    """Sibling names must be unique (UIBuilder and variants address nodes by path) and must not contain '/'."""
    clean = name.replace("/", "_") or "layer"
    if clean != name:
        warnings.append(f"{parent}/{name}: '/' in the name replaced by '_'".lstrip("/"))
    nm, i = clean, 2
    while f"{parent}/{nm}" in used:
        nm = f"{clean} {i}"
        i += 1
    if nm != clean:
        warnings.append(f"{parent}/{clean}: duplicate sibling name, built as '{nm}'".lstrip("/"))
    used.add(f"{parent}/{nm}")
    return nm


def path_of(n):
    return f"{n['parent']}/{n['name']}".lstrip("/")


class SpritePlanner:
    """Decides, per exported/downloaded image, which project sprite to use: an existing match (moved to Common/ when
    it lives in another UI's folder), an earlier image of this same build, or a new file in Images/UI/<name>/."""

    def __init__(self, project, name, files):
        self.project = project
        self.common = f"{UI_ROOT}/Common"
        self.own = f"{UI_ROOT}/{name}"
        self.matches = {m["candidate"]: m for m in match_sprites.dedupe_items(
            os.path.join(project, UI_ROOT), files, own=os.path.join(project, self.own))}
        self.new_sprites, self.moves, self.reused = [], [], []
        self.borders = {}        # asset path -> sprite border [l, b, r, t] a 9-slice match needs
        self.stale = set()       # own-folder copies a 9-slice match replaced (unused once built)
        self.assigned = {}       # source file -> asset path
        self.planned = set()

    def rel(self, p):
        return os.path.relpath(p, self.project).replace(os.sep, "/")

    def sprite_for(self, f, label):
        """-> (asset path, offset [dx, dy] of the sprite inside f, matched size (w, h) or None = size of f)."""
        if f in self.assigned:
            return self.assigned[f], [0, 0], None
        m = self.matches.get(f, {})
        if m.get("match"):
            path = self.rel(m["match"])
            if os.path.dirname(path) not in (self.common, self.own):
                to = f"{self.common}/{os.path.basename(path)}"
                if not any(mv["from"] == path for mv in self.moves):
                    self.moves.append({"from": path, "to": to})
                path = to
            if m.get("slice"):
                self.borders[path] = m["slice"]
                if m.get("stale"):
                    self.stale.add(self.rel(m["stale"]))
                self.reused.append(f"{label} -> {path} (Sliced, border {m['slice']}, diff {m['diff']})")
                self.assigned[f] = path
                return path, [0, 0], None
            w, h = Image.open(m["match"]).size
            sc = m.get("scale", 1.0)
            off = m.get("offset", [0, 0])
            self.reused.append(f"{label} -> {path}" + (f" (offset {off}, scale {sc})" if off != [0, 0] or sc != 1.0 else ""))
            self.assigned[f] = path
            return path, off, (round(w * sc), round(h * sc))
        for prev_file, prev in self.assigned.items():   # same art twice in this design (Shape 1 / Shape 1 copy ...)
            if same_pixels(prev_file, f):
                self.assigned[f] = prev
                return prev, [0, 0], None
        cand = match_sprites.load(f)
        for prev_file, prev in self.assigned.items():   # the same button art at two widths in this design
            r = match_sprites.slice_match(match_sprites.load(prev_file), cand)
            if r and self.borders.get(prev, r[0]) == r[0]:
                self.borders[prev] = r[0]
                self.reused.append(f"{label} -> {prev} (Sliced, border {r[0]}, diff {r[1]})")
                self.assigned[f] = prev
                return prev, [0, 0], None
        stem = file_stem(label)
        dst = f"{self.own}/{stem}.png"
        i = 2
        while dst in self.planned or os.path.exists(os.path.join(self.project, dst)):
            dst = f"{self.own}/{stem}_{i}.png"
            i += 1
        self.planned.add(dst)
        self.new_sprites.append({"from": f, "to": dst})
        self.assigned[f] = dst
        return dst, [0, 0], None


NEST_TOL = 4   # px a child may stick out of its container's rect


def nest_contained(nodes, frame, nest=True):
    """Make A a child of B when A sits inside B. Returns (nested, blocked) lists of messages.

    A moves under B when: they are siblings in the source, B is drawn first, B is a visible image or a placed group
    (not a text, not a stretch group, under 90 % of the frame), A (with its descendants) fits in B's rect +- NEST_TOL
    and is at most 90 % of B's area (same-size swaps and glows stay siblings), and no sibling drawn between them
    overlaps A unless it moves under B too (uGUI draws children over their parent, so that would change the order).
    The smallest such B wins, so Panel > Card > Icon nests in levels. A text whose centre is on a button always
    becomes its label. With nest=False only the labels are nested. Paths are rewritten, sibling names kept unique.
    """
    by_path = {path_of(n): n for n in nodes}
    kids = {}
    for n in nodes:
        kids.setdefault(n["parent"], []).append(n)

    def own(n):
        if n["type"] == "group" and (n.get("stretch") or "w" not in n):
            return None
        return [n["x"], n["y"], n["w"], n["h"]] if n.get("w", 0) > 0 and n.get("h", 0) > 0 else None

    full = {}

    def rect(n):   # own rect united with every descendant's
        if id(n) not in full:
            rs = [r for r in [own(n)] + [rect(c) for c in kids.get(path_of(n), [])] if r]
            if rs:
                x0, y0 = min(r[0] for r in rs), min(r[1] for r in rs)
                rs = [x0, y0, max(r[0] + r[2] for r in rs) - x0, max(r[1] + r[3] for r in rs) - y0]
            full[id(n)] = rs or None
        return full[id(n)]

    def area(r):
        return r[2] * r[3]

    def overlaps(a, b):
        return min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > 1 and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > 1

    container = {}   # id(A) -> new parent node

    def under(c, b):
        while c is not None:
            if c is b:
                return True
            c = container.get(id(c), by_path.get(c["parent"]))
        return False

    frame_area = frame[0] * frame[1]
    nested, blocked = [], []
    for j, a in enumerate(nodes):
        ra = rect(a)
        if ra is None:
            continue
        sibs = [(i, b) for i, b in enumerate(nodes[:j]) if b["parent"] == a["parent"]]
        cands = []
        for i, b in sibs:
            rb = own(b)
            if b["type"] == "text" or rb is None:
                continue
            cx, cy = ra[0] + ra[2] / 2, ra[1] + ra[3] / 2
            label = a["type"] == "text" and b.get("button") and rb[0] <= cx <= rb[0] + rb[2] and rb[1] <= cy <= rb[1] + rb[3]
            inside = (nest and b["visible"] and area(rb) < 0.9 * frame_area and area(ra) <= 0.9 * area(rb)
                      and rb[0] - NEST_TOL <= ra[0] and rb[1] - NEST_TOL <= ra[1]
                      and ra[0] + ra[2] <= rb[0] + rb[2] + NEST_TOL and ra[1] + ra[3] <= rb[1] + rb[3] + NEST_TOL)
            if label or inside:
                cands.append((0 if label else 1, area(rb), i, b))
        why = None
        for _, _, i, b in sorted(cands, key=lambda c: c[:3]):
            stop = next((c for k, c in sibs if k > i and not under(c, b) and rect(c) and overlaps(rect(c), ra)), None)
            if stop is None:
                container[id(a)] = b
                nested.append(f"{path_of(a)} -> {path_of(b)}")
                why = None
                break
            why = why or f"{path_of(a)} sits in {path_of(b)} but stays a sibling: {path_of(stop)} is drawn between them"
        if why:
            blocked.append(why)

    # rewrite paths top-down (parents come first in the list)
    new_path, used = {}, set()
    for n in nodes:
        p = container.get(id(n))
        parent = new_path[id(p)] if p is not None else new_path.get(id(by_path.get(n["parent"])), n["parent"])
        nm, k = n["name"], 2
        while f"{parent}/{nm}" in used:
            nm = f"{n['name']} {k}"
            k += 1
        if nm != n["name"]:
            blocked.append(f"{parent}/{n['name']}: name taken after nesting, built as '{nm}'".lstrip("/"))
        used.add(f"{parent}/{nm}")
        n["parent"], n["name"] = parent, nm
        new_path[id(n)] = path_of(n)
    return nested, blocked


def find_variants(nodes):
    """Sets of overlapping, same-kind siblings where exactly one is visible (icon / title / description swaps)."""
    def rect(n):
        return [n.get("x", 0), n.get("y", 0), n.get("w", 0), n.get("h", 0)]

    leaf = [n for n in nodes if n["type"] in ("image", "text")]
    slots, seen = [], set()
    for n in leaf:
        if n["visible"] or id(n) in seen:
            continue
        comp, stack = [], [n]
        while stack:
            c = stack.pop()
            if id(c) in seen:
                continue
            seen.add(id(c))
            comp.append(c)
            for o in leaf:
                if id(o) in seen or o["type"] != c["type"] or o["parent"] != c["parent"]:
                    continue
                if c["visible"] and o["visible"]:   # two visible layers never swap with each other
                    continue
                ra, rb = rect(c), rect(o)
                areas = sorted([ra[2] * ra[3], rb[2] * rb[3]])
                if overlap_frac(ra, rb) >= 0.5 and (c["type"] == "text" or areas[1] <= 2 * areas[0]):
                    stack.append(o)
        visible = [c for c in comp if c["visible"]]
        if len(visible) == 1:
            comp.sort(key=lambda c: nodes.index(c))
            slots.append((visible[0], [c for c in comp if not c["visible"]]))
    variants = []
    for k in range(max((len(h) for _, h in slots), default=0)):
        show, hide = [], []
        for vis, hidden in slots:
            if k < len(hidden):
                show.append(path_of(hidden[k]))
                hide.append(path_of(vis))
        label = next((t for _, h in slots if k < len(h) and h[k]["type"] == "text"
                      for t in [h[k].get("text") or h[k]["name"]] if len(t) < 20), f"variant{k + 1}")
        variants.append({"name": file_stem(label).lower() or f"variant{k + 1}", "show": show, "hide": hide})
    return variants


def load_names(path):
    """The rename map: {"<layer name or source path>": "NewName"}. {} when there is no file."""
    if not path or not os.path.exists(path):
        return {}
    names = json.load(open(path))
    bad = [k for k, v in names.items() if not isinstance(v, str) or not v or "/" in v]
    if bad:
        raise SystemExit(f"{path}: new names must be non-empty strings without '/': {bad}")
    return names


def rename_nodes(nodes, names, warnings):
    """Apply the rename map before nesting. A key is a source path ("booster/Shape 1 copy") or a bare layer name
    (every layer with that name); a path wins. An image renamed to "...Button" becomes a button (Button component).
    Returns the set of renamed nodes' ids."""
    renamed, hit, new_path = set(), set(), {}
    for n in nodes:
        old = path_of(n)
        key = old if old in names else n["name"] if n["name"] in names else None
        parent = new_path.get(n["parent"], n["parent"])
        if key is not None:
            hit.add(key)
            renamed.add(id(n))
            n["name"] = names[key]
            if n["type"] == "image" and "button" in n["name"].lower():
                n["button"] = True
        n["parent"] = parent
        new_path[old] = path_of(n)
    for k in names:
        if k not in hit:
            warnings.append(f"names: no layer '{k}' (typo, or the layer was renamed in the source)")
    return renamed


def rename_sprites(nodes, renamed, planner):
    """A sprite of this UI's own folder, used by a renamed node, takes the new name: one user -> its name, several
    (Sparkle1, Sparkle2, ...) -> their common prefix without the trailing digits. Existing files are moved
    (move_to_common entries, AssetDatabase.MoveAsset keeps the GUID); planned new files just get the new path.
    Returns ["old -> new"]."""
    users = {}
    for n in nodes:
        if n.get("sprite"):
            users.setdefault(n["sprite"], []).append(n)
    new_to = {ns["to"]: ns for ns in planner.new_sprites}
    moving = {m["from"] for m in planner.moves} | {m["to"] for m in planner.moves}
    taken = {p for p in users} | set(new_to)
    out = []
    for path, ns in users.items():
        if os.path.dirname(path) != planner.own or path in moving or not any(id(n) in renamed for n in ns):
            continue
        stems = [file_stem(n["name"]) for n in ns]
        stem = os.path.commonprefix(stems).rstrip("0123456789_- ") if len(set(stems)) > 1 else stems[0]
        stem = stem or stems[0]
        dst, i = f"{planner.own}/{stem}.png", 2
        if dst == path:
            continue
        while dst in taken or os.path.exists(os.path.join(planner.project, dst)):
            dst = f"{planner.own}/{stem}_{i}.png"
            i += 1
        taken.add(dst)
        if path in new_to:
            new_to[path]["to"] = dst
        else:
            planner.moves.append({"from": path, "to": dst})
        for n in ns:
            n["sprite"] = dst
        if path in planner.borders:
            planner.borders[dst] = planner.borders.pop(path)
        out.append(f"{path} -> {dst}")
    return out


def meta_border(project, path):
    """The sprite border already set in <path>.meta (Sprite Editor), or None."""
    meta = os.path.join(project, path + ".meta")
    if not os.path.exists(meta):
        return None
    m = re.search(r"spriteBorder: \{x: ([\d.]+), y: ([\d.]+), z: ([\d.]+), w: ([\d.]+)\}", open(meta).read())
    b = [round(float(v)) for v in m.groups()] if m else None
    return b if b and any(b) else None


def apply_slices(nodes, planner):
    """Sets node["slice"] (border [l, b, r, t]; UIBuilder sets the importer border once and uses Image Type Sliced)
    on nodes whose sprite needs a 9-slice border (a match of this build), or already has one and is drawn at its
    native size (Sliced looks the same there, and the Image stays stretchable)."""
    src = {m["to"]: m["from"] for m in planner.moves}
    for n in nodes:
        sp = n.get("sprite")
        if not sp or n.get("empty"):
            continue
        border = planner.borders.get(sp)
        if border is None:
            disk = src.get(sp, sp)
            full = os.path.join(planner.project, disk)
            border = meta_border(planner.project, disk)
            if border is None or not os.path.exists(full) or Image.open(full).size != (round(n["w"]), round(n["h"])):
                continue
        n["slice"] = border


def write_spec(out, name, frame, reference, replace, nodes, planner, warnings, nest=True, names=None, variants=None,
               extra_summary=None):
    """Rename (names map), nest contained nodes, fill every node's fields (JsonUtility needs them), write
    <out>/spec.json and print the summary."""
    renamed = rename_nodes(nodes, names or {}, warnings)
    nested, blocked = nest_contained(nodes, frame, nest)
    warnings += blocked
    sprite_renames = rename_sprites(nodes, renamed, planner)
    apply_slices(nodes, planner)
    for n in nodes:
        n.setdefault("parent", "")
        n.setdefault("visible", True)
        for key in ("stretch", "empty", "button"):
            n.setdefault(key, False)
    if variants is None:
        variants = find_variants(nodes)
    fonts = sorted({n["font"] for n in nodes if n["type"] == "text"})
    spec = {
        "name": name, "frame": list(frame), "out_dir": out, "reference": reference,
        "ui_root": UI_ROOT, "fonts_dir": FONTS_DIR, "prefab_dir": PREFAB_DIR,
        "replace": replace, "fonts": fonts,
        "move_to_common": planner.moves, "new_sprites": planner.new_sprites, "nodes": nodes, "variants": variants,
    }
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "spec.json"), "w") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    print(json.dumps({"spec": os.path.join(out, "spec.json"), "name": name, "frame": spec["frame"], "fonts": fonts,
                      "new_sprites": [s["to"] for s in planner.new_sprites], "reused": planner.reused,
                      "move_to_common": planner.moves, "renamed": len(renamed), "sprite_renames": sprite_renames,
                      "sliced": sorted({f"{path_of(n)}: {n['sprite']} {n['slice']}" for n in nodes if n.get("slice")}),
                      "unused_sprites": sorted(planner.stale - {n.get("sprite") for n in nodes}),
                      "nested": nested, "variants": variants, "warnings": warnings, **(extra_summary or {})},
                     ensure_ascii=False, indent=1))
    return spec


def parse_args(argv, n_positional):
    """-> (positional args, --name value or None, --replace, nest = not --no-nest, --names value or None)."""
    name = argv[argv.index("--name") + 1] if "--name" in argv else None
    names = argv[argv.index("--names") + 1] if "--names" in argv else None
    pos, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in ("--name", "--names"):
            skip = True
            continue
        if not a.startswith("--"):
            pos.append(a)
    if len(pos) < n_positional:
        raise SystemExit(f"need {n_positional} arguments, got {pos}")
    if names and not os.path.exists(names):
        raise SystemExit(f"--names: {names} not found")
    return pos, name, "--replace" in argv, "--no-nest" not in argv, names
