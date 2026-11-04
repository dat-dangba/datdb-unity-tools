"""Dump a PSD's layer tree, text styles, effects and the fonts it needs as JSON.

Usage: python -I psd_inspect.py <file.psd>
"""
import json
import sys

from psd_tools import PSDImage


def color_argb(values):
    a, r, g, b = (float(v) for v in values)
    return {"r": round(r * 255), "g": round(g * 255), "b": round(b * 255), "a": round(a, 3)}


# Layer effects are read from the raw lfx2 descriptor: psd-tools' layer.effects skips every effect that lacks the
# b"present" key, which Photoshop leaves out of older or single-instance effects (a Drop Shadow on "Test" in
# PausedUI-3.psd was missing). Keys: Photoshop class id -> our type name.
EFFECT_TYPES = {b"FrFX": "Stroke", b"DrSh": "DropShadow", b"IrSh": "InnerShadow", b"OrGl": "OuterGlow",
                b"IrGl": "InnerGlow", b"ebbl": "BevelEmboss", b"ChFX": "Satin", b"SoFi": "ColorOverlay",
                b"GrFl": "GradientOverlay", b"patternFill": "PatternOverlay"}


def num(v, default=0.0):
    try:
        return float(getattr(v, "value", v))
    except (TypeError, ValueError):
        return default


def enum(v):
    e = getattr(v, "enum", v)
    return (e.decode("latin-1") if isinstance(e, bytes) else str(e)).strip()


def get(d, key, default=None):
    """Descriptor lookup by a stripped 4-char key ("Clr", "Md") or a long key ("redFloat")."""
    for k in (key.encode(), key.ljust(4).encode()):
        if k in d:
            return d[k]
    return default


def color_of(c):
    """Photoshop color descriptor -> {"Rd", "Grn", "Bl"} 0-255 (RGB, float RGB, HSB, grayscale, Lab-less book colors)."""
    if c is None:
        return {"Rd": 0, "Grn": 0, "Bl": 0}
    if get(c, "redFloat") is not None:
        return {"Rd": round(num(get(c, "redFloat")) * 255), "Grn": round(num(get(c, "greenFloat")) * 255),
                "Bl": round(num(get(c, "blueFloat")) * 255)}
    if get(c, "Rd") is not None:
        return {"Rd": round(num(get(c, "Rd"))), "Grn": round(num(get(c, "Grn"))), "Bl": round(num(get(c, "Bl")))}
    if get(c, "H") is not None:
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(num(get(c, "H")) / 360 % 1, num(get(c, "Strt")) / 100, num(get(c, "Brgh")) / 100)
        return {"Rd": round(r * 255), "Grn": round(g * 255), "Bl": round(b * 255)}
    if get(c, "Gry") is not None:
        v = round((1 - num(get(c, "Gry")) / 100) * 255)
        return {"Rd": v, "Grn": v, "Bl": v}
    return {"Rd": 0, "Grn": 0, "Bl": 0, "unknown": True}


def gradient_of(g):
    """Gradient descriptor -> {"name", "noise", "colors": [[loc0-1, r, g, b, kind]], "alphas": [[loc0-1, a0-1]]}."""
    if g is None:
        return None
    form = enum(get(g, "GrdF", "CstS"))
    colors = []
    for s in get(g, "Clrs", []) or []:
        c = color_of(get(s, "Clr"))
        colors.append([num(get(s, "Lctn")) / 4096, c["Rd"], c["Grn"], c["Bl"], enum(get(s, "Type", "UsrS"))])
    alphas = [[num(get(s, "Lctn")) / 4096, num(get(s, "Opct"), 100) / 100] for s in get(g, "Trns", []) or []]
    return {"name": str(get(g, "Nm", "")).strip("\x00"), "noise": form == "ClNs",
            "colors": sorted(colors), "alphas": sorted(alphas) or [[0, 1], [1, 1]]}


def effects_of(layer, global_angle=120.0):
    from psd_tools.constants import Tag
    blocks = layer.tagged_blocks
    data = None
    for tag in (Tag.OBJECT_BASED_EFFECTS_LAYER_INFO, Tag.OBJECT_BASED_EFFECTS_LAYER_INFO_V0,
                Tag.OBJECT_BASED_EFFECTS_LAYER_INFO_V1):
        if blocks and tag in blocks:
            data = blocks.get_data(tag)
            break
    if data is None:
        return []
    master = bool(get(data, "masterFXSwitch", True))
    out = []
    for key in data:
        items = data[key] if isinstance(data[key], list) or type(data[key]).__name__ == "List" else [data[key]]
        for it in items:
            cid = getattr(it, "classID", None)
            if cid not in EFFECT_TYPES or get(it, "present", True) is False:
                continue
            d = {"type": EFFECT_TYPES[cid], "enabled": master and bool(get(it, "enab", True)),
                 "blend": enum(get(it, "Md", "Nrml")), "opacity": num(get(it, "Opct"), 100)}
            if get(it, "Clr") is not None:
                d["color"] = color_of(get(it, "Clr"))
            if get(it, "Sz") is not None:
                d["size"] = num(get(it, "Sz"))
            if get(it, "Styl") is not None:
                d["position"] = enum(get(it, "Styl"))
            if get(it, "PntT") is not None:
                d["paint"] = enum(get(it, "PntT"))
            if cid in (b"DrSh", b"IrSh"):
                use_global = bool(get(it, "uglg", False))
                d.update(angle=global_angle if use_global else num(get(it, "lagl"), 120), distance=num(get(it, "Dstn")),
                         spread=num(get(it, "Ckmt")), blur=num(get(it, "blur")))
            if cid == b"GrFl":
                d.update(gradient=gradient_of(get(it, "Grad")), style=enum(get(it, "Type", "Lnr")),
                         angle=num(get(it, "Angl"), 90), reverse=bool(get(it, "Rvrs", False)),
                         scale=num(get(it, "Scl"), 100), align=bool(get(it, "Algn", True)),
                         dither=bool(get(it, "Dthr", False)))
            out.append(d)
    return out


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


def walk(layers, out, path="", global_angle=None):
    if global_angle is None:
        global_angle = 120.0
        try:
            from psd_tools.constants import Resource
            psd = getattr(layers, "_psd", None) or layers
            global_angle = float(psd.image_resources.get_data(Resource.GLOBAL_ANGLE, 120))
        except Exception:
            pass
    for l in layers:
        node = {
            "name": l.name, "path": f"{path}/{l.name}".lstrip("/"), "kind": l.kind,
            "visible": bool(l.visible), "opacity": int(l.opacity),
            "bbox": list(l.bbox), "blend": l.blend_mode.name,
            "clipping": bool(getattr(l, "clipping", False)), "has_mask": bool(l.has_mask()),
            "effects": effects_of(l, global_angle),
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
            walk(l, node["children"], node["path"], global_angle)
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
