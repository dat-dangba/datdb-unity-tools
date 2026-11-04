"""Dump a PSD's layer tree, text styles, effects and the fonts it needs as JSON.

Usage: python -I psd_inspect.py <file.psd>
"""
import json
import sys

from psd_tools import PSDImage


def color_argb(values):
    a, r, g, b = (float(v) for v in values)
    return {"r": round(r * 255), "g": round(g * 255), "b": round(b * 255), "a": round(a, 3)}


def effect_info(e):
    d = {"type": type(e).__name__, "enabled": bool(e.enabled)}
    for key in ("size", "position", "opacity", "distance", "angle"):
        try:
            v = getattr(e, key)
            d[key] = v.decode() if isinstance(v, bytes) else (float(v) if isinstance(v, (int, float)) else str(v))
        except Exception:
            pass
    try:
        c = e.color
        d["color"] = {k.decode().strip(): round(float(v)) for k, v in c.items()}
    except Exception:
        pass
    return d


def text_info(layer):
    ed, rd = layer.engine_dict, layer.resource_dict
    fonts = [str(f["Name"]).strip("'") for f in rd["FontSet"]]
    runs = []
    for r in ed["StyleRun"]["RunArray"]:
        sd = r["StyleSheet"]["StyleSheetData"]
        runs.append({
            "font": fonts[int(sd.get("Font", 0))],
            "size": float(sd.get("FontSize", 0)),
            "leading": float(sd["Leading"]) if "Leading" in sd else None,
            "auto_leading": bool(sd.get("AutoLeading", True)),
            "tracking": float(sd.get("Tracking", 0)),
            "fill": color_argb(sd["FillColor"]["Values"]) if "FillColor" in sd else None,
        })
    just = ed["ParagraphRun"]["RunArray"][0]["ParagraphSheet"]["Properties"].get("Justification", 0)
    xx, xy, yx, yy, tx, ty = (float(v) for v in layer.transform)
    return {
        "text": layer.text.replace("\r", "\n"),
        "runs": runs,
        # 0 left, 1 right, 2 center
        "justification": int(just),
        # Photoshop point text: (tx, ty) is the anchor x and the FIRST baseline; scale multiplies font size
        "anchor_x": tx, "baseline_y": ty, "scale": yy,
    }


def walk(layers, out, path=""):
    for l in layers:
        node = {
            "name": l.name, "path": f"{path}/{l.name}".lstrip("/"), "kind": l.kind,
            "visible": bool(l.visible), "opacity": int(l.opacity),
            "bbox": list(l.bbox), "blend": l.blend_mode.name,
            "clipping": bool(getattr(l, "clipping", False)), "has_mask": bool(l.has_mask()),
            "effects": [effect_info(e) for e in l.effects] if l.has_effects() else [],
        }
        if l.kind == "type":
            node["text"] = text_info(l)
        if l.kind == "smartobject":
            so = l.smart_object
            node["smart_object"] = {"filename": so.filename, "embedded_bytes": len(so.data or b"")}
            if l.width <= 1 or l.height <= 1:
                node["warning"] = "smart object has no pixels (empty/broken layer)"
        if l.is_group():
            node["children"] = []
            walk(l, node["children"], node["path"])
        out.append(node)


def main():
    psd = PSDImage.open(sys.argv[1])
    tree = []
    walk(psd, tree)
    fonts = set()

    def collect(nodes):
        for n in nodes:
            if "text" in n:
                for r in n["text"]["runs"]:
                    fonts.add(r["font"])
            collect(n.get("children", []))

    collect(tree)
    print(json.dumps({"size": list(psd.size), "fonts": sorted(fonts), "layers": tree}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
