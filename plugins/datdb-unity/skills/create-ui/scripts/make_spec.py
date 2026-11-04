"""PSD -> spec.json for UIBuilder.Build (one step: inspect + export + dedupe + spec).

Usage: python -I make_spec.py <file.psd> <project_root> <out_dir> [--name UIName] [--replace] [--no-nest] [--names N.json]
       python -I make_spec.py <file.psd> --fonts-only
--fonts-only reads only the text layers (no export, no dedupe) and prints {font: [text layer names]}, so the fonts can
be checked in Unity (UIBuilder.CheckFonts) before any slow work.
Writes <out_dir>/spec.json (format: reference/spec.md) and prints a short JSON summary.
Exported layers go to <out_dir>/psd_export; only the new ones are listed in spec.new_sprites (UIBuilder copies them).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # sibling helpers (-I drops the script dir)

from psd_tools import PSDImage  # noqa: E402

import psd_export  # noqa: E402
import psd_inspect  # noqa: E402
from spec_common import (SHADOW, SpritePlanner, color_name, load_names, parse_args, ps_drop_shadow,  # noqa: E402
                         ps_gradient_overlay, unique_name, write_spec)


def fonts_only(psd_path):
    tree = []
    psd_inspect.walk(PSDImage.open(psd_path), tree)
    fonts = {}

    def collect(nodes):
        for n in nodes:
            for r in n.get("text", {}).get("runs", []):
                users = fonts.setdefault(r["font"], [])
                if n["name"] not in users:
                    users.append(n["name"])
            collect(n.get("children", []))

    collect(tree)
    print(json.dumps({"fonts": fonts}, ensure_ascii=False, indent=1))


def main():
    if "--fonts-only" in sys.argv:
        return fonts_only(os.path.abspath(parse_args(sys.argv[1:], 1)[0][0]))
    pos, name, replace, nest, names_path = parse_args(sys.argv[1:], 3)
    psd_path, project, out = (os.path.abspath(p) for p in pos[:3])
    name = name or os.path.splitext(os.path.basename(psd_path))[0]

    psd = PSDImage.open(psd_path)
    tree = []
    psd_inspect.walk(psd, tree)
    items = psd_export.export(psd, os.path.join(out, "psd_export"))
    exported = {}   # PSD path -> exports in layer order (two layers can share a path)
    for e in items:
        exported.setdefault(e["path"], []).append(e)
    planner = SpritePlanner(project, name, [e["file"] for e in items if "file" in e and not e["empty"]])
    warnings, nodes, used = [], [], set()

    def walk(layers, parent):
        for l in layers:
            nm = unique_name(parent, l["name"], used, warnings)
            path = f"{parent}/{nm}".lstrip("/")   # spec path; exports are keyed by the PSD path l["path"]
            if l["kind"] == "group":
                nodes.append({"name": nm, "parent": parent, "type": "group", "stretch": True, "visible": l["visible"]})
                walk(l["children"], path)
                continue
            if l.get("blend") not in ("NORMAL", "PASS_THROUGH") or l.get("clipping") or l.get("has_mask") or l["opacity"] < 255:
                warnings.append(f"{path}: blend {l.get('blend')}, opacity {l['opacity']}, clipping {l.get('clipping')}, "
                                f"mask {l.get('has_mask')} not reproduced exactly; check the render")
            if l["kind"] == "type":
                t = l["text"]
                r0 = t["runs"][0]
                if any((r["font"], r["size"], r["fill"]) != (r0["font"], r0["size"], r0["fill"]) for r in t["runs"][1:]):
                    warnings.append(f"{path}: several text styles, only the first run is used")
                sc = t["scale"]
                fill = r0["fill"] or {"r": 0, "g": 0, "b": 0, "a": 1}
                node = {"name": nm, "parent": parent, "type": "text", "visible": l["visible"],
                        "text": t["text"], "font": r0["font"], "size": round(r0["size"] * sc, 3),
                        "leading": 0 if r0["auto_leading"] or not r0["leading"] else round(r0["leading"] * sc, 3),
                        "color": [fill["r"], fill["g"], fill["b"], round(fill["a"] * 255)],
                        "align": {0: "left", 1: "right"}.get(t["justification"], "center"), "place": "baseline",
                        "anchor_x": t["anchor_x"], "baseline_y": t["baseline_y"],
                        "x": l["bbox"][0], "y": l["bbox"][1], "w": l["bbox"][2] - l["bbox"][0], "h": l["bbox"][3] - l["bbox"][1]}
                if r0.get("tracking"):
                    warnings.append(f"{path}: tracking {r0['tracking']} ignored")
                for fx in l["effects"]:
                    if not fx.get("enabled"):
                        continue
                    if fx["type"] == "DropShadow":
                        if "underlay" in node:
                            warnings.append(f"{path}: several drop shadows, only the first is built")
                        else:
                            node["underlay"] = ps_drop_shadow(fx, path, warnings)
                            node["underlay_name"] = color_name(node["underlay"][2:5])
                    elif fx["type"] == "GradientOverlay":
                        if "gradient" in node:
                            warnings.append(f"{path}: several gradient overlays, only the first is built")
                            continue
                        g = ps_gradient_overlay(fx, node["w"], node["h"], node["color"], path, warnings)
                        if g:
                            node["gradient"], node["color"] = g
                    elif fx["type"] == "Stroke":
                        if "stroke_px" in node:
                            warnings.append(f"{path}: several strokes, only the first is built")
                            continue
                        if fx.get("paint", "SClr") != "SClr":
                            warnings.append(f"{path}: stroke fill {fx.get('paint')} built as its solid color")
                        if fx.get("position") != "OutF":
                            warnings.append(f"{path}: stroke position {fx.get('position')} built as Outside")
                        c = fx["color"]
                        rgb = [c.get("Rd", 0), c.get("Grn", 0), c.get("Bl", 0)]
                        node.update(stroke_px=fx["size"], stroke_color=rgb + [round(fx.get("opacity", 100) * 2.55)],
                                    stroke_name=color_name(rgb))
                    else:
                        warnings.append(f"{path}: text effect {fx['type']} not built (TMP: only Stroke, Drop Shadow, Gradient Overlay)")
                nodes.append(node)
                continue
            queue = exported.get(l["path"])
            e = queue.pop(0) if queue else None
            node = {"name": nm, "parent": parent, "type": "image", "visible": l["visible"],
                    "button": "button" in l["name"].lower()}
            if not e or "file" not in e or e["empty"]:
                warnings.append(f"{path}: layer has no pixels -> GameObject with a disabled Image")
                b = l["bbox"]
                node.update(empty=True, x=b[0], y=b[1], w=max(1, b[2] - b[0]), h=max(1, b[3] - b[1]))
            else:
                if e.get("note"):
                    warnings.append(f"{path}: {e['note']}")
                sprite, off, size = planner.sprite_for(e["file"], e["name"])
                size = size or tuple(e["size"])
                node.update(sprite=sprite, x=e["bbox"][0] + off[0], y=e["bbox"][1] + off[1], w=size[0], h=size[1])
                if 3 <= max(off) <= 7 and sprite not in planner.borders:   # a Sliced rect's offset is only padding
                    node["shadow"] = SHADOW
                    warnings.append(f"{path}: reused sprite sits {off} px inside the PSD art (baked shadow?) -> "
                                    f"Shadow {SHADOW}; compare the render")
            for fx in l["effects"]:
                if fx.get("enabled"):
                    warnings.append(f"{path}: layer effect {fx['type']} not built (bake it or add it by hand)")
            nodes.append(node)

    walk(tree, "")
    write_spec(out, name, psd.size, os.path.join(out, "psd_export", "_composite.png"), replace, nodes, planner, warnings, nest,
               load_names(names_path or os.path.splitext(psd_path)[0] + ".names.json"))


if __name__ == "__main__":
    main()
