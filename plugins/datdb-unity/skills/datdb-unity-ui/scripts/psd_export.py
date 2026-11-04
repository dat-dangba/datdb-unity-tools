"""Export every non-text PSD layer (hidden ones too) to PNG, plus the visible composite.

Usage: python -I psd_export.py <file.psd> <out_dir>
Prints one JSON line per exported layer: {name, path, file, bbox, size, visible, md5}.
"""
import hashlib
import io
import json
import os
import re
import sys

from psd_tools import PSDImage


def safe(name):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_") or "layer"


def export(psd, out):
    """Export every non-text layer of an opened PSD into out; returns the per-layer dicts."""
    os.makedirs(out, exist_ok=True)
    psd.composite().save(os.path.join(out, "_composite.png"))
    used = set()
    items = []

    def walk(layers, path=""):
        for l in layers:
            p = f"{path}/{l.name}".lstrip("/")
            if l.is_group():
                walk(l, p)
                continue
            if l.kind == "type":
                continue
            img = None
            note = ""
            if l.kind == "smartobject" and (l.width <= 1 or l.height <= 1):
                try:
                    inner = PSDImage.open(io.BytesIO(l.smart_object.data))
                    img = inner.composite()
                    note = "embedded smart object content (layer itself had no pixels)"
                except Exception as ex:
                    note = f"empty smart object: {ex}"
            if img is None:
                img = l.topil() if l.kind != "shape" else None
                if img is None:
                    img = l.composite(force=True)
            if img is None:
                items.append({"name": l.name, "path": p, "error": "no pixels"})
                continue
            fn = safe(l.name)
            while fn in used:
                fn += "_"
            used.add(fn)
            fp = os.path.join(out, fn + ".png")
            img.save(fp)
            alpha_max = img.getchannel("A").getextrema()[1] if img.mode == "RGBA" else 255
            items.append({
                "name": l.name, "path": p, "file": fp, "bbox": list(l.bbox), "size": list(img.size),
                "visible": bool(l.visible), "empty": alpha_max == 0, "note": note,
                "md5": hashlib.md5(open(fp, "rb").read()).hexdigest(),
            })

    walk(psd)
    return items


def main():
    for item in export(PSDImage.open(sys.argv[1]), sys.argv[2]):
        print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
