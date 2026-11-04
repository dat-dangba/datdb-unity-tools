# spec.json for `DatdbUI.UIBuilder.Build`

`make_spec.py` (PSD), `figma_spec.py` (Figma) and `png_spec.py` (PNG) write this through `spec_common.py`. Edit it by
hand only when a warning needs it. `JsonUtility` parses it, so:
- Give every node all of its type's fields. Missing bools default to `false`, so always write `"visible": true`
  explicitly.
- No comments, no trailing commas.
- Colors are `[r, g, b, a]` in 0–255.

```json
{
 "name": "BoosterUI",                     // UI name = prefab name (root GameObject); also the per-UI image folder
 "prefab_dir": "Assets/_Project/Prefabs/UI",   // output: <prefab_dir>/<name>.prefab
 "frame": [1080, 1920],                   // design size = preview canvas size = render size
 "out_dir": "/abs/scratchpad/build_BoosterUI",   // renders + report.json go here
 "reference": "/abs/.../_composite.png",  // used by verify.py (PSD composite / Figma screenshot / the PNG)
 "ui_root": "Assets/_Project/Images/UI",
 "fonts_dir": "Assets/_Project/Fonts",
 "replace": false,                        // true ONLY after the user said to overwrite an existing <name>.prefab
 "fonts": ["RoundedMplus1c-Black"],       // PSD PostScript names, or Figma "family style"; text nodes add theirs too
 "move_to_common": [{"from": "Assets/.../OtherUI/X.png", "to": "Assets/.../Common/X.png"}],
 "new_sprites":    [{"from": "/abs/scratchpad/x.png", "to": "Assets/_Project/Images/UI/BoosterUI/X.png"}],
 "nodes": [ ...bottom -> top... ],
 "variants": [{"name": "hint", "show": ["booster/icon_idea", "booster/Hint"], "hide": ["booster/icon_arrow", "booster/Undo"]}]
}
```

## Nodes

Each node has `name`, a `parent` path relative to the root (`""` = the root itself, `"booster/ClaimButton"`), a
`type` and `visible`. A parent must come before its children. Coordinates are in design px, measured from the
frame's top-left, whatever the parent is.

| type | fields |
|---|---|
| `group` | `stretch: true` (fills its parent), or `x, y, w, h` |
| `image` | `sprite` (Assets path), `x, y, w, h`, `button` (adds `Button` and raycast), `empty` (disabled Image), optional `tint`, optional `shadow: [dx, dyDown, r, g, b, alpha0-1]`, optional `slice: [left, bottom, right, top]` (sprite border px → Image Type Sliced) |
| `text` | `text`, `font`, `size`, `color`, `leading` (px; 0 = font default), `align` (`left`/`center`/`right`), `place`, optional `stroke_px`, `stroke_color`, `stroke_name` (the color word in the material name: Green, Orange…) |

Text placement:
- `"place": "baseline"`: uses `anchor_x` and `baseline_y` (PSD point text). Multiply size and leading by the PSD
  `scale`.
- `"place": "rect"`: uses `x, y, w, h` (Figma text node).

Either way, UIBuilder then fits the rect to the text and turns on Auto Size (Max = `size`, Min = 50 %).

A text node for a PNG `layout.json` (also the shape of every Figma text node):
`{"type": "text", "name": "Claim", "text": "Claim", "font": "RoundedMplus1c-Black", "size": 68, "color": [255, 255, 255, 255], "leading": 0, "align": "center", "place": "rect", "x": 440, "y": 1300, "w": 200, "h": 100, "stroke_px": 4, "stroke_color": [30, 130, 20, 255], "stroke_name": "Green"}`

A button label is a text whose `parent` is the button node.

Rename map (`rename_nodes`, `rename_sprites`, run by `write_spec` first): `<source>.names.json` or `--names`,
`{"<layer name or source path>": "NewName"}`. Nodes are renamed before nesting, so nesting, variants and sprite file
names use the new names. A renamed sprite of the UI's own folder becomes a `move_to_common` entry (any
`from -> to` move: `AssetDatabase.MoveAsset`, GUID kept); a planned new sprite just gets the new `to`.

Nesting (`nest_contained`, run by `write_spec` before the variants): A becomes a child of B when they are siblings
in the source, B is drawn first, B is a visible image or a group with `x, y, w, h` (not a text, not a stretch group,
under 90 % of the frame), A with its descendants fits in B's rect ± 4 px, and A is at most 90 % of B's area. The
smallest such B wins. A sibling drawn between B and A that overlaps A blocks it (uGUI draws children over their
parent, so the order would change) unless it moves under B too; the warning names it. A text whose centre sits on a
button always becomes its label. `--no-nest` keeps only the labels. Paths are rewritten after nesting, so variants
and the report use the nested paths. Coordinates never change.

Strokes are always built as Outside, using the material `"<font asset> Outline <stroke_name>.mat"` in `fonts_dir`.
UIBuilder reuses an existing material when its atlas, outline color and computed width match. Otherwise it creates
a new one, adding a ` 2` suffix if the name is taken. If a stroke needs more texels than the atlas padding,
UIBuilder adds a warning. Ask the user before raising the padding.

Shadow: Figma `0 4 2 rgba(40,20,42,.52)` → `[0, 4, 40, 20, 42, 0.52]`.

## Variants

Each variant hides some nodes and shows others, then renders `render_<name>.png`. UIBuilder restores the original
state afterwards. Paths are relative to the root. Use variants for every mutually exclusive state the design hides
(icon, title or description swaps). `make_spec.py` finds them on its own: it looks for overlapping siblings of the
same kind where exactly one is visible.

## report.json (also returned by Build)

| field | meaning |
|---|---|
| `ok`, `errors` | Everything is validated BEFORE anything changes: fonts (`MISSING font: …`), the prefab name (`EXISTS: …`), parents listed before children, node types, sizes, every sprite (existing, or arriving through `new_sprites` / `move_to_common`, never a path that `move_to_common` moves away), sprite sources on disk and variant paths. |
| `prefab` | The saved prefab path (checked on disk). |
| `warnings` | Empty layers, texts that shrink below their design size, stroke wider than the padding, duplicate paths. |
| `sprites_sliced` | Sprites whose importer border was set (checked on the reloaded sprite). |
| `sprites_moved`, `sprites_imported`, `materials_created`, `materials_reused` | What changed. Each entry is checked on disk before it is listed. |
| `texts[]` | `path`, `design`, `rendered` size, `rect` in frame px, `stroke_px`, `visible`. |
| `renders[]` | `render.png`, `render_2x.png` (only when there are strokes), `render_<variant>.png`. |

## Notes

- `AssetDatabase.DeleteAsset` (files and folders) fails through Unity MCP ("User interactions are not supported").
- After copying a new `UIBuilder.cs`, Unity recompiles and reloads. For about 20 s, MCP calls fail with "Unity not
  detected". Wait, then check `Unity_GetConsoleLogs` for errors.
- Build works in its own preview scene (`EditorSceneManager.NewPreviewScene`): a world-space canvas of `frame` size
  and an orthographic camera, closed after `PrefabUtility.SaveAsPrefabAsset`. No scene has to be open and the open
  scene's objects are never touched. Overwriting an existing prefab keeps its GUID. Renders match the old Screen
  Space Camera renders (BoosterUI PSD: frame diff 1.53 vs 1.6).
- The class is `DatdbUI.UIBuilder`. Call it from `Unity_RunCommand` as
  `result.Log(DatdbUI.UIBuilder.Build("<spec path>"));`.
- In `Unity_RunCommand`, `result.Log` does NOT support `{0:F2}`-style formats, so use `string.Format` first.
  `Regex` and `System.Reflection` are blocked there, but not inside `UIBuilder.cs`.
- A dynamic font atlas must be readable. UIBuilder fixes that on its own.
