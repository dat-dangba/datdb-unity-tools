---
name: create-ui
description: Build a uGUI screen as a prefab in Assets/_Project/Prefabs/UI from a Figma frame link, a PSD file or a flat PNG mockup, reusing project sprites and TMP fonts. Use when the user runs /create-ui <figma link | path/to/file.psd | path/to/file.png>.
argument-hint: <figma-url | path/to/file.psd | path/to/file.png>
---

# create-ui

Builds a Unity uGUI screen as a prefab `Assets/_Project/Prefabs/UI/<UI name>.prefab` from one source given in
`$ARGUMENTS`. UIBuilder lays out and renders the UI in its own preview scene (a world-space canvas and a camera
sized to the frame), so no scene has to be open. The open scene is not used or changed.

| Argument | Source type |
|---|---|
| `https://www.figma.com/design/<fileKey>/...?node-id=A-B` | Figma frame `A:B` |
| path ending in `.psd` / `.psb` | Photoshop file |
| path ending in `.png` / `.jpg` | Flat mockup. It is built ONLY from sprites already in `Assets/_Project/Images/UI` |

Relative paths are resolved from the Unity project root (the working directory, the folder that holds `Assets/`). If the argument is missing or
the file doesn't exist, ask for it and stop.

Talk to the user in Vietnamese. Use the task list (update_plan) for the steps below.

**Fonts first.** Check every font the design needs (step 1) BEFORE any export, download, dedupe or spec work. If
one is missing, STOP right there: nothing else runs, nothing changes.

**Speed rules.** A PSD build takes about 5 tool calls (two more when it writes a rename map). On Figma, the only reads are `create_session`, ONE
`use_figma` (`figma_dump.js`) and one parallel batch (`get_design_context` for image URLs, `download_assets`,
`get_screenshot`); `get_metadata` and a second `use_figma` are no longer needed.
- Run independent calls in parallel (Figma: the step 0 setup and the step 1 `use_figma` read). A PSD/PNG font
  listing needs `$PY` from step 0.
- Never hand-write C# build code or a whole spec.json. `make_spec.py`, `figma_spec.py` and `png_spec.py` write
  the spec. `UIBuilder.CheckFonts(...)` and `UIBuilder.Build(spec)` each take ONE `Unity_RunCommand`.
- Look at images only where step 4 says to (and at the PNG crops in step 2).

Helper files in this skill, relative to its base directory `$S` (the "Base directory for this skill" line, also
printed by setup.py as `skill`). Run every script with `$PY -I -B`, where `$PY` is the venv interpreter setup.py
prints as `python` (`-B`: no `__pycache__` in the skill folder). Shell variables don't survive between Bash calls,
so write both paths out in full in every command. Works on macOS, Linux and Windows (Git Bash); use forward slashes
in every path, including the C# strings.
- `scripts/setup.py`: step 0 (venv + UIBuilder install), standard library only.
- `unity/UIBuilder.cs`: the template for `Assets/_Project/Editor/UIBuilder.cs` (installed by setup.py), called as
  `DatdbUI.UIBuilder.CheckFonts(keys…)` (font step alone) and `DatdbUI.UIBuilder.Build(specPath)`. In one call it
  does: validate EVERYTHING first (fonts, prefab name, node tree, sprite sources, variant paths) → move shared
  sprites to Common → copy and import new sprites → text materials (outline / underlay) → build in a preview scene → fit texts + Auto
  Size → hidden states → renders (main, 2×, variants) → save prefab → close the preview scene → `report.json`.
  Any error found by the validation changes nothing.
- `reference/spec.md`: the spec.json format and the report fields. Read it before editing a spec by hand.
- `scripts/make_spec.py`: PSD → spec.json (inspect + export + dedupe, buttons, labels, text effects, variants).
  `--fonts-only` prints `{font: [text layers]}` (~1 s).
- `scripts/figma_dump.js`: the ONE read-only `use_figma` script: fonts + every node's properties.
- `scripts/figma_spec.py`: Figma dump + downloaded images → spec.json (same dedupe, buttons, labels, variants).
- `scripts/match_sprites.py`: `locate` and `compose` for PNG mockups (`dedupe` is used by the spec writers).
- `scripts/png_spec.py`: the refined `compose` layout → spec.json.
- `scripts/verify.py`: diff against the reference, plus `sheet.png` (render | heatmap | variants) and
  `strokes.png` (2× close-ups).
- `scripts/spec_common.py`, `psd_inspect.py`, `psd_export.py`: shared modules of the scripts above.

## Project conventions (always)

- **UI name** = the Figma frame name / the PSD file name / the PNG file name, without extension. If
  `Assets/_Project/Prefabs/UI/<UI name>.prefab` already exists (Build returns `EXISTS: …`), ASK the user whether to
  overwrite it (`--replace`, keeps the GUID) or use another name (`--name`). Never delete or rename existing
  prefabs or UI on your own.
- Output: one prefab per UI in `Assets/_Project/Prefabs/UI/` (`prefab_dir`). The root is a stretched full-screen
  RectTransform, meant to be placed under a Canvas. Nothing is added to any scene; the user places the prefab.
  The children keep the design's layer names and order (bottom → top). Duplicate sibling names get a ` 2` suffix
  and `/` becomes `_` (the spec writers warn). Hidden layers are created too, with `SetActive(false)`.
- Nesting: on top of the design's own groups, a layer that sits inside a sibling image or placed group drawn
  before it becomes that sibling's child (smallest container wins, so Panel > Card > Icon). Texts on a button
  become its label. This never changes the draw order; a layer stays a sibling when another layer drawn between
  them overlaps it (a warning says which). `--no-nest` keeps only the labels (rule: `nest_contained` in
  `spec_common.py`, reference/spec.md).
- Names: PascalCase, role + type suffix (`PopupFrame`, `TitleBanner`, `HeartIcon`, `CloseButton`, `TitleText`;
  texts by role, not content; swaps share the stem: `HintIcon`/`UndoIcon`; the top group is `Content`). Every
  image whose final name (after the rename map) contains `Button` gets a `Button` component (raycast on). Layer
  names that don't follow this come from the source. Fix them with a rename map `<source>.names.json` next to
  the PSD/PNG (picked up on its own), or `--names <file>` (Figma: always `--names`):
  `{"Group 5": "PopupFrame", "booster/Shape 1 copy": "Sparkle2"}`. A key is a layer name (every layer with it)
  or a source path (wins). Unused keys are warned. Sprites in this UI's own folder used by a renamed layer take
  the new name (several users → their common prefix: `Sparkle1..3` → `Sparkle.png`), moved with the GUID kept.
  When a design has auto names (`Group 5`, `Rectangle 11`, `Shape 1 copy`) or content-named texts and no map
  exists, write the map yourself and use it right away, without asking (step 2, "Rename map"). An existing map
  is used as it is: never overwrite it.
- Images go in `Assets/_Project/Images/UI/`:
  - `Common/`: images used by 2+ UIs. Keep this folder even when it's empty.
  - `<UI name>/`: images only this UI uses. File names follow the layer names.
  - Before adding any image, dedupe it against everything in `Images/UI/**` (the spec writers do it). Reuse
    matches. If a match lives in another UI's folder, it moves to `Common/` (`move_to_common`; UIBuilder uses
    `AssetDatabase.MoveAsset`, which keeps the GUID, and checks the disk).
  - 9-slice: when no exact match exists outside this UI's folder, dedupe also tries each sprite drawn Sliced, in
    width, height or both (`match_sprites.slice_fit`: transparent padding of both images is trimmed first, border
    from the longest run of identical columns/rows, rebuild diff ≤ `SLICE_ART`). The node rect becomes the trimmed
    art (+ the sprite's own padding), so a frame exported with empty margins still lines up. A cheap pre-filter
    (flat runs + middle colour) skips the pixel compare for almost every sprite, and per-sprite data is cached in
    `<project>/Library/datdb-ui/sprite_index.json` (rebuilt only for new/changed files; safe to delete). A match
    reuses that sprite with `"slice": [l, b, r, t]`; UIBuilder sets the
    Sprite Editor border once (an existing different border is kept + warned) and uses Image Type Sliced. A node
    whose sprite already has a border and is drawn at native size is Sliced too. The own-folder copy it replaces
    is listed in `unused_sprites`: tell the user to delete it. Two new images of one build are matched the same way.
    Build the UIs that share a sliced sprite one after another (spec → Build), since Build moves the files.
  - If a per-UI folder ends up empty, it should be deleted. `AssetDatabase.DeleteAsset` is blocked through Unity
    MCP (folders and files), so tell the user which empty folders to delete by hand.
- Download or export into the scratchpad first. Only what is actually new goes into `Assets` (`new_sprites`).
- Fonts live in `Assets/_Project/Fonts/` as TMP SDF assets. Text materials sit next to them, named
  `"<font asset> Outline <Color>.mat"`, `"<font asset> Underlay <Color>.mat"` or
  `"<font asset> Outline <Color> Underlay <Color>.mat"`. UIBuilder reuses one when font, colors and computed
  values match.
- Text effects (PSD layer styles / Figma text fills and effects): Stroke → TMP Outline, Drop Shadow → TMP Underlay
  (offset, blur → softness, spread → dilate), Gradient Overlay / gradient fill → TMP Color Gradient (4 corner
  vertex colors, applied per glyph). Every other text effect (Inner Shadow, Glow, Bevel, Satin, Color/Pattern
  Overlay, extra strokes or shadows, blend modes) is listed in `warnings`: tell the user it was not built. A font key
  matches a TMP asset by family + style, by the asset name without `SDF`, or by the source `.ttf`/`.otf` name.
- When reporting results, never claim an operation worked without checking the disk. UIBuilder's report only
  lists checked results. Still `ls` the new image folder once.
- When the user only asks a question ("có được không", "nên … không"), answer it and don't change anything.

## Step 0: Setup (first; a Figma source can run its step 1 reads in parallel)

One call, from the Unity project root (bootstrap Python: `python3` on macOS/Linux; on Windows `py -3`, or `python`
when `py` is missing):
```bash
python3 "$S/scripts/setup.py" .
```
It creates the venv `~/.cache/datdb-uienv` the first time (psd-tools, numpy, pillow; about a minute), then copies
`unity/UIBuilder.cs` to `Assets/_Project/Editor/UIBuilder.cs` whenever the installed copy differs in any way. It
prints JSON: `python` (= `$PY`), `skill` (= `$S`), `uibuilder` (`up-to-date` | `INSTALLED`) and `errors`.
- `errors` not empty: STOP and tell the user (no Python 3.9+: install it, on Windows from python.org with "Add
  python.exe to PATH" or `winget install Python.Python.3.12`; not a Unity project: wrong folder).
- `uibuilder` is `INSTALLED`: Unity recompiles. The next MCP call fails with "Unity not detected" for about 20 s;
  check `Unity_GetConsoleLogs` (errors) until it answers, then go on. Tell the user the file was updated.

## Step 1: Font check (blocking, before anything else)

Get the font list without exporting anything:
- PSD: `$PY -I -B $S/scripts/make_spec.py <file.psd> --fonts-only`
- Figma: load `figma:figma-use`, `create_session` with the fileKey, then run `scripts/figma_dump.js` through
  `use_figma` with `__NODE_ID__` replaced (`node-id` `A-B` → `A:B`). It returns `fonts` AND every node, hidden ones
  included, with text strokes and effects (which `get_design_context` drops). Save the result as
  `<scratchpad>/build_<name>/figma_dump.json`. The Starter plan has a low call limit; on a rate-limit error,
  tell the user and stop.
- PNG: compare each text with the project TMP fonts by eye. If a text doesn't clearly match any of them, it is a
  missing font.

Then check them in Unity (one call; the keys are the fonts from the list):
```csharp
using UnityEngine;
using UnityEditor;

internal class CommandScript : IRunCommand
{
    public void Execute(ExecutionResult result)
    {
        result.Log(DatdbUI.UIBuilder.CheckFonts("<font 1>", "<font 2>"));
    }
}
```
- Every line `OK …`: go on to step 2.
- Any `MISSING font: …`: STOP. Do not export, download, dedupe or write a spec. Tell the user which fonts are
  missing (PostScript name / family + style), which texts use them, and which `.ttf`/`.otf` in
  `Assets/_Project/Fonts/` look like the source (TMP Font Asset Creator → save the SDF asset there). Nothing was
  changed.

## Step 2: Spec

### PSD (one call)
```bash
$PY -I -B $S/scripts/make_spec.py <file.psd> . <scratchpad>/build_<name> [--name X] [--replace] [--no-nest] [--names N.json]
```

### Figma
1. Images, from the dump (no other Figma read is needed):
   - Image fills (`fills[].imageHash`): get their URLs with ONE `get_design_context` call (load
     `figma:figma-design-to-code` first; nodeId = the frame, skillNames `figma-design-to-code`) and `curl -sfL`
     them into the scratchpad. Kind `fill`: effects are not baked, so drop shadows become a uGUI Shadow.
   - Shapes/vectors with no image fill: render them with `download_assets` as PNG (scale 2 for small vectors;
     Unity can't use SVG), and remove the frame's grey background (rounded rect: rebuild alpha from an SDF of the
     radius; white shape: `alpha = (max(rgb) − bg) / (1 − bg)`). Kind `render`: effects and children are baked in.
     Render the smallest node that holds the art (the button's rectangle, not the whole button with its label).
   - Get the reference with `get_screenshot` of the frame, in the same parallel batch.
2. Write `<scratchpad>/build_<name>/assets.json`: `{"<node id>": {"file": "/abs/x.png", "kind": "fill" | "render"}}`.
3. ```bash
   $PY -I -B $S/scripts/figma_spec.py <build>/figma_dump.json <build>/assets.json <screenshot.png> . <build> [--name X] [--replace] [--no-nest] [--names N.json]
   ```
   A `... has no asset` warning means a visible shape is missing from assets.json: render it and run it again.

### PNG (no new images allowed)
1. `match_sprites.py locate <Images/UI> <file.png> <scratch>/locate` (~10 s). It finds mostly visible sprites
   (`placed`). Heavily covered sprites (a box under rays) and semi-transparent ones (glows) are usually NOT found.
2. View the mockup and the `_unexplained_N.png` crops, then pick project sprites for the rest. Write `layout.json`
   (all layers bottom → top). Add `"shadow": [0, 4, 40, 20, 42, 0.52]` where the art shows a drop shadow. Add each
   text as a spec text node (`{"type": "text", "place": "rect", ...}`, reference/spec.md) at its place in the
   order; `compose` skips texts and keeps them in the layout.
3. `match_sprites.py compose <file.png> layout.json <scratch>/compose --refine 3` (~30 s). View EVERY remaining
   crop:
   - Text you have not added yet: add it to layout.json.
   - An edge leftover: ignore it, or fix the layout.
   - A graphic no project sprite reproduces: that is a **missing image**. STOP, build nothing, and report its
     position, size, a short description and the crop path. The user must add it to `Images/UI` first.
   - When two sprite versions fit one slot, keep the one with the lower residual and say which one you chose.
4. ```bash
   $PY -I -B $S/scripts/png_spec.py <scratch>/compose/_layout.json . <build> [--name X] [--replace] [--no-nest] [--names N.json]
   ```
- Tested: BoosterUI.png composes to mean_diff ≈ 1.9 with only the texts left. An extra unknown red circle was
  reported as an unexplained blob.

### Every source: read the summary
- `new_sprites`, `reused` and `move_to_common`.
- `sliced` (nodes drawn Sliced, with border) and `unused_sprites` (own copies replaced by a sliced shared sprite).
- `renamed` (layers renamed by the map) and `sprite_renames` (also listed in `move_to_common`).
- `nested`: `A -> B` for every layer moved under a container. Check that they make sense.
- `variants`: check that they make sense.
- `warnings`: empty layers (built with a disabled Image; tell the user), effects that weren't built (text
  effects other than Stroke / Drop Shadow / Gradient Overlay), gradient approximations,
  blend/opacity, several text styles, renamed duplicates, baked-shadow guesses and layers that could not be nested.

Edit `spec.json` only when a warning needs it.

### Rename map (automatic, no confirmation)
When no map exists (no `<source>.names.json`, no `--names`) and some layer names in the spec don't follow the
naming rule above:
1. Look at the design once (PSD: `<build>/psd_export/_composite.png`; Figma: the screenshot) to tell each
   layer's role. Exported sizes or average colors of the layers' PNGs help with layers that are hard to spot.
2. Write the map: a key for every layer that needs a new name, and none for layers that already follow the rule
   (`CloseButton`, `HomeButton`). Shapes that repeat share a stem (`Sparkle1..3`); swaps share the stem
   (`HintIcon`/`UndoIcon`); the top group is `Content`. PSD/PNG: save it as `<source>.names.json` next to the
   source file, so the next build picks it up. Figma: save it as `<build>/names.json` and pass `--names`.
3. Run the same spec command again. `renamed` should count every key, and `warnings` must not list unused keys.
4. Go straight on to step 3. Do not ask the user about the names.

PNG: you name the layers yourself in `layout.json`, so give them the right names there and skip the map.

## Step 3: Build (ONE Unity_RunCommand)

```csharp
using UnityEngine;
using UnityEditor;

internal class CommandScript : IRunCommand
{
    public void Execute(ExecutionResult result)
    {
        result.Log(DatdbUI.UIBuilder.Build("<scratchpad>/build_<name>/spec.json"));
    }
}
```
- `MISSING font: …`: should not happen after step 1 (Build re-checks). STOP and report it the same way.
- `EXISTS: …`: the prefab already exists; ask the user to overwrite or rename.
- Other validation errors (`parent not found`, `sprite not found`, `variant …: no node`, …): fix the spec and run
  it again. Nothing was changed.
- Read `warnings`, especially any text that shrinks below its design size, any stroke wider than the padding and
  any drop shadow built shorter than its design offset or with its spread/blur dropped (atlas padding too small).

## Step 4: Verify (always, before reporting)

```bash
$PY -I -B $S/scripts/verify.py <scratchpad>/build_<name>
```
- View `sheet.png` (render | heatmap | each variant) in ONE Read. When there are outlined, shadowed or gradient texts,
  Read `strokes.png` in the same message. There must be no square artifacts.
- `mean_diff` is measured inside the content box (`mean_diff_frame` over the whole frame). `pass` means
  mean_diff ≤ 5 with only thin edges differing (the BoosterUI PSD build: 3.3, frame 1.5). If it fails, open
  `heatmap.png`, fix the structural problem, and re-run Build with `"replace": true`. That is allowed for a UI you
  just built in this turn.

## Step 5: Report (Vietnamese)

- The prefab path (`report.prefab`) and its hierarchy. Say that no scene was changed.
- Images: what was reused, what was moved to `Common/`, what is new, and empty folders the user should delete.
- The rename map, when you wrote one this turn: its path and an `old → new` table. Tell the user they can edit
  it and rebuild with `--replace`.
- Fonts and text materials (outline / underlay) used or created; text effects that were not built.
- Hidden layers, what still needs the user (empty layers, onClick not wired),
  and what you could not verify (e.g. strokes of hidden variants are only checked at 1×).
