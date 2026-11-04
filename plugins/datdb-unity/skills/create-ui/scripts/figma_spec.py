"""Figma frame -> spec.json, from the figma_dump.js result plus the downloaded images.

Usage: python -I figma_spec.py <figma_dump.json> <assets.json> <reference.png> <project_root> <out_dir>
                               [--name UIName] [--replace] [--no-nest] [--names N.json]
assets.json maps node ids to the PNGs in the scratchpad:
  {"12:34": {"file": "/abs/x.png", "kind": "fill"},     image fill downloaded by hash: effects are NOT baked
   "12:40": {"file": "/abs/y.png", "kind": "render"}}   download_assets render (bg removed): effects ARE baked,
                                                         children are baked too and are not built
Every node becomes a spec node in Figma order (bottom -> top): TEXT -> text ("place": "rect"), a node in assets ->
image, other containers -> group. A group named "...button..." whose bottom child is an image covering it becomes
that image with Button, and the rest become its children (the label). Leaves without an asset are built as a
disabled Image and reported. Dedupe, Common/ moves, variants and defaults come from spec_common.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # sibling helpers (-I drops the script dir)

from PIL import Image  # noqa: E402

from spec_common import SpritePlanner, color_name, load_names, parse_args, unique_name, write_spec  # noqa: E402

CONTAINERS = ("FRAME", "GROUP", "COMPONENT", "COMPONENT_SET", "INSTANCE", "SECTION", "BOOLEAN_OPERATION")


def solid(paints):
    if not isinstance(paints, list):
        return None
    for p in paints:
        if p.get("type") == "SOLID" and p.get("visible", True):
            return p
    return None


def main():
    pos, name, replace, nest, names_path = parse_args(sys.argv[1:], 5)
    dump_path, assets_path, ref, project, out = (os.path.abspath(p) for p in pos[:5])
    dump = json.load(open(dump_path))
    assets = json.load(open(assets_path))
    name = name or dump["frame"]["name"]
    by_id = {n["id"]: n for n in dump["nodes"]}
    kids = {}
    for n in dump["nodes"]:
        kids.setdefault(n["parent"], []).append(n)
    root = next(n for n in dump["nodes"] if n["parent"] is None)

    for nid, a in assets.items():
        if nid not in by_id:
            raise SystemExit(f"assets.json: no node {nid} in the dump")
        if not os.path.exists(a["file"]):
            raise SystemExit(f"assets.json: missing file {a['file']}")
    planner = SpritePlanner(project, name, sorted({a["file"] for a in assets.values()}))
    nodes, warnings, used = [], [], set()

    def rect_of(n, a=None):
        r = n.get("render") if a and a["kind"] == "render" and n.get("render") else n["bbox"]
        return [round(v, 2) for v in r]

    def image_node(n, a, parent, nm):
        x, y, w, h = rect_of(n, a)
        sprite, off, size = planner.sprite_for(a["file"], n["name"])
        fw, fh = Image.open(a["file"]).size
        if size and (off != [0, 0] or tuple(size) != (fw, fh)):   # extra px around a matching / Sliced sprite
            sx, sy = w / fw, h / fh
            x, y, w, h = x + off[0] * sx, y + off[1] * sy, size[0] * sx, size[1] * sy
        node = {"name": nm, "parent": parent, "type": "image", "visible": n["visible"], "sprite": sprite,
                "x": x, "y": y, "w": w, "h": h, "button": "button" in n["name"].lower()}
        if n.get("opacity", 1) < 1:
            node["tint"] = [255, 255, 255, round(255 * n["opacity"])]
        for e in n.get("effects", []):
            if not e.get("visible", True) or a["kind"] == "render":
                continue
            if e["type"] == "DROP_SHADOW":
                c = e.get("color") or [0, 0, 0, 0.25]
                node["shadow"] = [e["offset"][0], e["offset"][1], c[0], c[1], c[2], c[3]]
                if (e.get("radius") or 0) > 4:
                    warnings.append(f"{nm}: shadow blur {e['radius']} built as a hard uGUI Shadow; render the node "
                                    f"(kind render) if it looks wrong")
            else:
                warnings.append(f"{nm}: effect {e['type']} not built on an image fill; render the node instead")
        return node

    def text_node(n, parent, nm):
        x, y, w, h = n["bbox"]
        size = n["fontSize"]
        fill = solid(n.get("fills")) or {"color": [0, 0, 0]}
        alpha = fill.get("opacity", 1) * n.get("opacity", 1)
        lh = n.get("lineHeight")
        leading = 0
        if isinstance(lh, dict) and lh.get("unit") == "PIXELS":
            leading = lh["value"]
        elif isinstance(lh, dict) and lh.get("unit") == "PERCENT":
            leading = size * lh["value"] / 100
        node = {"name": nm, "parent": parent, "type": "text", "visible": n["visible"], "text": n["characters"],
                "font": n["font"], "size": size, "leading": round(leading, 3),
                "color": fill["color"] + [round(255 * alpha)],
                "align": {"LEFT": "left", "RIGHT": "right", "JUSTIFIED": "left"}.get(n.get("textAlign"), "center"),
                "place": "rect", "x": x, "y": y, "w": w, "h": h}
        if n.get("mixed"):
            warnings.append(f"{nm}: several text styles, only the first character's style is used")
        ls = n.get("letterSpacing")
        if isinstance(ls, dict) and ls.get("value"):
            warnings.append(f"{nm}: letter spacing {ls['value']} {ls.get('unit')} ignored")
        if n.get("autoResize") == "NONE" and n.get("textAlignVertical") != "CENTER":
            warnings.append(f"{nm}: fixed text box aligned {n.get('textAlignVertical')}; built centred on the text")
        st = solid(n.get("strokes"))
        if st and isinstance(n.get("strokeWeight"), (int, float)) and n["strokeWeight"] > 0:
            if n.get("strokeAlign") != "OUTSIDE":
                warnings.append(f"{nm}: stroke {n.get('strokeAlign')} built as Outside")
            node.update(stroke_px=n["strokeWeight"], stroke_color=st["color"] + [round(255 * st.get("opacity", 1))],
                        stroke_name=color_name(st["color"]))
        for e in n.get("effects", []):
            if e.get("visible", True):
                warnings.append(f"{nm}: text effect {e['type']} not built")
        return node

    def emit(n, parent):
        nm = unique_name(parent, n["name"], used, warnings)
        path = f"{parent}/{nm}".lstrip("/")
        a = assets.get(n["id"])
        children = kids.get(n["id"], [])
        if n["type"] == "TEXT":
            nodes.append(text_node(n, parent, nm))
            return
        if a:
            nodes.append(image_node(n, a, parent, nm))
            if a["kind"] == "render":
                if children:
                    warnings.append(f"{path}: rendered with its {len(children)} children baked in (not built separately)")
                return
            for c in children:
                emit(c, path)
            return
        if n["type"] in CONTAINERS or children:
            bottom = children[0] if children else None
            ba = assets.get(bottom["id"]) if bottom else None
            if "button" in n["name"].lower() and ba and bottom["type"] != "TEXT":
                bx = rect_of(bottom, ba)
                gx = n["bbox"]
                if bx[2] * bx[3] >= 0.9 * gx[2] * gx[3]:
                    img = image_node(bottom, ba, parent, nm)
                    img["button"] = True
                    img["visible"] = n["visible"] and bottom["visible"]
                    nodes.append(img)
                    for c in children[1:]:
                        emit(c, path)
                    return
            x, y, w, h = n["bbox"]
            nodes.append({"name": nm, "parent": parent, "type": "group", "visible": n["visible"],
                          "x": x, "y": y, "w": w, "h": h})
            for c in children:
                emit(c, path)
            return
        x, y, w, h = n["bbox"]
        if solid(n.get("fills")) or n.get("strokes") or n.get("effects"):
            warnings.append(f"{path}: {n['type']} has no asset -> disabled Image; render it (download_assets) and "
                            f"add it to assets.json")
        else:
            warnings.append(f"{path}: empty {n['type']} -> disabled Image")
        nodes.append({"name": nm, "parent": parent, "type": "image", "visible": n["visible"], "empty": True,
                      "x": x, "y": y, "w": max(1, w), "h": max(1, h)})

    if root["id"] in assets:   # the frame's own background
        nodes.append(image_node(root, assets[root["id"]], "", unique_name("", root["name"] + " bg", used, warnings)))
    for c in kids.get(root["id"], []):
        emit(c, "")
    write_spec(out, name, [round(root["bbox"][2]), round(root["bbox"][3])], ref, replace, nodes, planner, warnings, nest,
               load_names(names_path))


if __name__ == "__main__":
    main()
