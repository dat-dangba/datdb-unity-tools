"""PNG mockup -> spec.json, from the refined layout that `match_sprites.py compose` saved.

Usage: python -I png_spec.py <compose_out>/_layout.json <project_root> <out_dir> [--name UIName] [--replace] [--no-nest] [--names N.json]
Image entries ({"name", "sprite": abs path in Images/UI, "x", "y", "w", "h", optional "shadow", "parent",
"visible"}) become image nodes; "button" is set when the name contains "button". Entries with "type": "text" or
"group" are already spec nodes (reference/spec.md) and are copied as they are, in layout order. Texts whose centre
sits on a button become its label. new_sprites stays empty: a PNG build only reuses project sprites, so a sprite
outside Images/UI is an error.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # sibling helpers (-I drops the script dir)

from PIL import Image  # noqa: E402

from spec_common import UI_ROOT, SpritePlanner, load_names, parse_args, safe_ui_name, write_spec  # noqa: E402


def main():
    pos, name, replace, nest, names_path = parse_args(sys.argv[1:], 3)
    layout_path, project, out = (os.path.abspath(p) for p in pos[:3])
    data = json.load(open(layout_path, encoding="utf-8"))
    ref = data["reference"]
    nodes, warnings, errors = [], [], []
    name = safe_ui_name(name or os.path.splitext(os.path.basename(ref))[0], warnings)
    ui_root = os.path.join(project, UI_ROOT) + os.sep

    planner = SpritePlanner(project, name, [])   # nothing to dedupe; only the Common/ move rule is used
    for L in data["layout"]:
        if L.get("type") in ("text", "group"):
            nodes.append({"parent": "", "visible": True, **L})
            continue
        sprite = os.path.normpath(os.path.join(project, L["sprite"]))   # absolute, or relative to the project
        if not sprite.startswith(ui_root):
            errors.append(f"{L['name']}: {sprite} is not a project sprite (PNG builds use only Images/UI)")
            continue
        planner.matches[sprite] = {"match": sprite, "offset": [0, 0], "scale": 1.0}
        path, _, _ = planner.sprite_for(sprite, L["name"])
        w, h = L.get("w") or Image.open(sprite).width, L.get("h") or Image.open(sprite).height
        node = {"name": L["name"], "parent": L.get("parent", ""), "type": "image", "visible": L.get("visible", True),
                "sprite": path, "x": L["x"], "y": L["y"], "w": w, "h": h,
                "button": L.get("button", "button" in L["name"].lower())}
        if L.get("shadow"):
            node["shadow"] = L["shadow"]
        nodes.append(node)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=1))
        sys.exit(1)
    if not any(n["type"] == "text" for n in nodes):
        warnings.append("no text entries in the layout: add the texts as {\"type\": \"text\", ...} entries")
    planner.reused = []   # every sprite is reused here; the list would only repeat the layout
    write_spec(out, name, Image.open(ref).size, ref, replace, nodes, planner, warnings, nest,
               load_names(names_path or os.path.splitext(ref)[0] + ".names.json"))


if __name__ == "__main__":
    main()
