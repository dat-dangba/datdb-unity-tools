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
| `image` | `sprite` (Assets path), `x, y, w, h`, `button` (adds `Button` and raycast; the spec writers set it for every image whose name, after the rename map, contains `button`), `empty` (disabled Image), optional `tint`, optional `shadow: [dx, dyDown, r, g, b, alpha0-1]`, optional `slice: [left, bottom, right, top]` (sprite border px → Image Type Sliced) |
| `text` | `text`, `font`, `size`, `color`, `leading` (px; 0 = font default), `align` (`left`/`center`/`right`), `place`, `wrap` (bool), optional `stroke_px`, `stroke_color`, `stroke_name` (the color word in the material name: Green, Orange…), optional `underlay: [dx, dyDown, r, g, b, alpha0-1, blur_px, dilate_px]` + `underlay_name`, optional `gradient` (16 numbers: TL, TR, BL, BR corners as `[r, g, b, a]` 0–255) |

Text placement:
- `"place": "baseline"`: uses `anchor_x` and `baseline_y` (PSD point text). `anchor_x` is the line's left edge
  (`left`), centre (`center`) or right edge (`right`), as in Photoshop. Multiply size and leading by the PSD `scale`.
- `"place": "rect"`: uses `x, y, w, h` (Figma text node, PSD paragraph text).
- `"wrap": true` (PSD paragraph / box text): TMP wraps the lines inside `w` and lays them out from the top of the
  box, like Photoshop. Line breaks can still differ (font metrics), so the spec writer warns. Otherwise no wrapping.

Either way, UIBuilder then fits the rect to the text and turns on Auto Size (Max = `size`, Min = 50 %).

PSD justification: 0 left, 1 right, 2 center; justified paragraphs (3/4/5) use their last-line alignment and
"justify all" (6) is built as left, with a warning. Rotated, skewed or stretched text is built upright (warned).

A text node for a PNG `layout.json` (also the shape of every Figma text node):
`{"type": "text", "name": "Claim", "text": "Claim", "font": "RoundedMplus1c-Black", "size": 68, "color": [255, 255, 255, 255], "leading": 0, "align": "center", "place": "rect", "x": 440, "y": 1300, "w": 200, "h": 100, "stroke_px": 4, "stroke_color": [30, 130, 20, 255], "stroke_name": "Green"}`

A button label is a text whose `parent` is the button node.

## Conventions in detail

UI name: the spec writers replace `/ \ : * ? " < > |` and control characters with `_` (Figma frames are often
named `Popup / Shop`), because the name is the prefab file name and the `Images/UI/<name>/` folder.

Names: duplicate sibling names get a ` 2` suffix and `/` becomes `_` (warned). Every image whose final name (after
the rename map) contains `Button` gets `button: true`. A rename-map key is a layer name (every layer with it) or a
source path (wins); unused keys are warned. Sprites in this UI's own folder used by a renamed layer take the new
name (several users → their common prefix: `Sparkle1..3` → `Sparkle.png`), moved with the GUID kept.

Images and dedupe (`match_sprites.dedupe_items`, run by every spec writer): exact md5, then pixel compare with a
small offset search at scales 1, 0.5 and 2, outside this UI's own folder first. A match in another UI's folder
moves to `Common/` (`move_to_common`, `AssetDatabase.MoveAsset`, GUID kept). Two identical images of one build share
one sprite.

9-slice: when no exact match exists outside this UI's folder, dedupe also tries each sprite drawn Sliced, in
width, height or both (`match_sprites.slice_fit`: transparent padding of both images is trimmed first, the border
comes from the longest run of identical columns/rows, rebuild diff ≤ `SLICE_ART`). The node rect becomes the trimmed
art plus the sprite's own padding, so a frame exported with empty margins still lines up. A cheap pre-filter (flat
runs + middle colour) skips the pixel compare for almost every sprite, and per-sprite data is cached in
`<project>/Library/datdb-ui/sprite_index.json` (rebuilt only for new/changed files; safe to delete). A match reuses
the sprite with `"slice": [l, b, r, t]`; UIBuilder sets the Sprite Editor border once (an existing different border
is kept + warned) and uses Image Type Sliced. A node whose sprite already has a border and is drawn at native size
is Sliced too. The own-folder copy it replaces is listed in `unused_sprites`. Two new images of one build are
matched the same way.

New sprites are imported as Sprite (Single), no mipmaps, alpha is transparency, with the importer Max Size raised
to fit the image (never lowered). A reused sprite whose Max Size is below its image size is only warned.

Fonts: a font key matches a TMP asset by family + style, by the asset name without `SDF`, or by the source
`.ttf`/`.otf` name. Assets are tried in a fixed order (main assets before `… Fallback` ones, then by path).

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

Text drop shadow → `underlay` (material Underlay, `UNDERLAY_ON`), in the same material as the outline:
`"<font asset> Underlay <underlay_name>.mat"` or `"<font asset> Outline <stroke_name> Underlay <underlay_name>.mat"`.
- PSD Drop Shadow: offset from angle (or the global light) and distance, `dx = -d·cos(a)`, `dyDown = d·sin(a)`;
  spread % turns that part of the size into `dilate_px`, the rest is `blur_px`. Blend other than Normal (or Multiply
  with a dark color) is warned. psd_inspect reads effects from the raw `lfx2` descriptor because psd-tools'
  `layer.effects` drops effects without the `present` key.
- Figma `DROP_SHADOW`: `offset`, `radius` → `blur_px`, `spread` → `dilate_px`.
- TMP keeps underlay + outline + bold reserve inside the atlas padding (ratio C). UIBuilder keeps the offset first,
  then drops the dilate, then the blur, and warns when the built offset is still shorter than the design.

Text gradient → `gradient` (`enableVertexGradient` + `colorGradient`), the node `color` becomes white with the
layer's alpha so the corners are the final colors.
- PSD Gradient Overlay: the corners are sampled along the angle across the text bbox (scale, reverse, opacity
  over the fill, color + opacity stops). Non-linear styles, non-Normal blends, noise gradients and more than two
  stops are warned (only the 4 corners exist).
- Figma `GRADIENT_*` top fill: the corners come from `gradientTransform` (unit box → gradient space), composited
  over a solid fill under it.
- TMP applies the 4 corners to every glyph, not to the whole text block, so a vertical gradient restarts on each
  letter. The spec writers always warn so the render gets compared.

Other text effects are never built; the spec writers list them in `warnings`.

## Variants

Each variant hides some nodes and shows others, then renders `render_<name>.png`. UIBuilder restores the original
state afterwards. Paths are relative to the root. Use variants for every mutually exclusive state the design hides
(icon, title or description swaps). `make_spec.py` finds them on its own: it looks for overlapping siblings of the
same kind where exactly one is visible.

## report.json (also returned by Build)

| field | meaning |
|---|---|
| `ok`, `errors` | Everything is validated BEFORE anything changes: the frame, fonts (`MISSING font: …`), the prefab name (`EXISTS: …`), parents listed before children, node types, sizes, every sprite (existing, or arriving through `new_sprites` / `move_to_common`, never a path that `move_to_common` moves away), sprite sources on disk and variant paths. A failure AFTER validation is not rolled back: a `PARTIAL: …` error then lists every change already made. |
| `prefab` | The saved prefab path (checked on disk). |
| `warnings` | Empty layers, texts that shrink below their design size, stroke wider than the padding, drop shadows shortened or simplified by the padding, duplicate paths, importer Max Size below the image size, font atlases set to Read/Write. |
| `log` | Fonts matched, the prefab created/replaced, the UIBuilder version. |
| `sprites_sliced` | Sprites whose importer border was set (checked on the reloaded sprite). |
| `sprites_moved`, `sprites_imported`, `materials_created`, `materials_reused` | What changed. Each entry is checked on disk before it is listed. |
| `texts[]` | `path`, `design`, `rendered` size, `rect` in frame px, `stroke_px`, `underlay`, `gradient`, `visible`. |
| `renders[]` | `render.png`, `render_2x.png` (only when there are strokes, shadows or gradients), `render_<variant>.png`. |

## Notes

- `AssetDatabase.DeleteAsset` (files and folders) fails through Unity MCP ("User interactions are not supported").
- After copying a new `UIBuilder.cs`, Unity recompiles and reloads. For about 20 s, MCP calls fail with "Unity not
  detected". Wait, then check `Unity_GetConsoleLogs` for errors.
- Build works in its own preview scene (`EditorSceneManager.NewPreviewScene`): a world-space canvas of `frame` size
  and an orthographic camera, closed after `PrefabUtility.SaveAsPrefabAsset`. No scene has to be open and the open
  scene's objects are never touched. Overwriting an existing prefab keeps its GUID but rebuilds the hierarchy:
  components and edits added to the prefab by hand are lost, and the children get new file IDs, so scene overrides
  and references to child objects break. Renders match the old Screen Space Camera renders (BoosterUI PSD: frame
  diff 1.53 vs 1.6).
- The class is `DatdbUI.UIBuilder`. Call it from `Unity_RunCommand` as
  `result.Log(DatdbUI.UIBuilder.Build("<spec path>"));`.
- In `Unity_RunCommand`, `result.Log` does NOT support `{0:F2}`-style formats, so use `string.Format` first.
  `Regex` and `System.Reflection` are blocked there, but not inside `UIBuilder.cs`.
- A dynamic font atlas must be readable. UIBuilder fixes that on its own.
