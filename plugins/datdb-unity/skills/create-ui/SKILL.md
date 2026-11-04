---
name: create-ui
description: Build a uGUI screen as a prefab in Assets/_Project/Prefabs/UI from a Figma frame link, a PSD file or a flat PNG mockup, reusing project sprites and TMP fonts. Use when the user runs /create-ui <figma link | path/to/file.psd | path/to/file.png>.
argument-hint: <figma-url | path/to/file.psd | path/to/file.png>
allowed-tools: Read, mcp__unity-mcp__Unity_GetConsoleLogs, mcp__plugin_figma_figma__get_screenshot, mcp__plugin_figma_figma__get_design_context, mcp__plugin_figma_figma__download_assets
---

# create-ui

Builds a Unity uGUI screen as a prefab `Assets/_Project/Prefabs/UI/<UI name>.prefab` from one source given in
`$ARGUMENTS`. UIBuilder lays out and renders the UI in its own preview scene, so no scene is opened or changed.

| Argument | Source type |
|---|---|
| `https://www.figma.com/design/<fileKey>/...?node-id=A-B` | Figma frame `A:B` |
| path ending in `.psd` / `.psb` | Photoshop file |
| path ending in `.png` / `.jpg` | Flat mockup, built ONLY from sprites already in `Assets/_Project/Images/UI` |

Relative paths are resolved from the Unity project root (the working directory, the folder that holds `Assets/`).
If the argument is missing or the file doesn't exist, ask for it and stop.

Talk to the user in Vietnamese. Track the steps below in your task-list tool.

## Hard rules

- **Fonts first.** Check every font (step 1) BEFORE any export, download, dedupe or spec work. One missing: STOP,
  nothing else runs, nothing changes.
- **Never hand-write C# build code or a whole spec.json.** The spec writers write the spec;
  `UIBuilder.CheckFonts(...)` and `UIBuilder.Build(spec)` each take ONE `Unity_RunCommand`.
- **Speed.** A PSD build is about 5 tool calls (+2 when you write a rename map). Figma reads are only
  `create_session`, ONE `use_figma` (`figma_dump.js`) and one parallel batch (`get_design_context` for image URLs,
  `download_assets`, `get_screenshot`). Run independent calls in parallel. Look at images only where step 2 (PNG)
  and step 4 say to.
- **Existing prefab** (`EXISTS: …`): ASK whether to overwrite (`--replace`) or use another name (`--name X`). Say
  clearly that overwriting keeps the prefab GUID but rebuilds the whole hierarchy: components, onClick wiring and
  edits added to that prefab by hand are lost, and scene overrides or references to its child objects break.
  Never delete or rename existing prefabs or images on your own.
- **Rename map.** An existing `<source>.names.json` is used as it is: never overwrite it.
- **Report only what is checked.** UIBuilder's report lists results it checked on disk; still `ls` the new image
  folder once. A `PARTIAL:` error means changes were made before a failure and were not rolled back: list them.
- When the user only asks a question ("có được không", "nên … không"), answer it and change nothing.

## Files (`$S` = the skill's base directory, also printed by setup.py as `skill`)

Run every script with `$PY -I -B` (`$PY` = setup.py's `python`; `-B`: no `__pycache__` in the skill folder). Shell
variables don't survive between Bash calls: write both paths out in full in every command. Use forward slashes in
every path, C# strings included (macOS, Linux and Windows Git Bash).

| File | Role |
|---|---|
| `scripts/setup.py` | step 0: venv + UIBuilder install (standard library only) |
| `unity/UIBuilder.cs` | template of `Assets/_Project/Editor/UIBuilder.cs`: `DatdbUI.UIBuilder.CheckFonts(keys…)`, `DatdbUI.UIBuilder.Build(specPath)` |
| `reference/spec.md` | spec.json format, the conventions in detail (naming, images, 9-slice, nesting, text effects) and the report fields. Read it before editing a spec by hand |
| `scripts/make_spec.py` | PSD → spec.json; `--fonts-only` prints `{font: [text layers]}` (~1 s) |
| `scripts/figma_dump.js` | the ONE read-only `use_figma` script: fonts + every node |
| `scripts/figma_spec.py` | Figma dump + downloaded images → spec.json |
| `scripts/match_sprites.py` | `locate` and `compose` for PNG mockups |
| `scripts/png_spec.py` | refined `compose` layout → spec.json |
| `scripts/verify.py` | diff vs the reference, `sheet.png`, `strokes.png` |
| `scripts/spec_common.py`, `psd_inspect.py`, `psd_export.py` | shared modules |

## Conventions (summary; details in reference/spec.md)

- **UI name** = Figma frame name / PSD or PNG file name without extension (characters a file name can't hold
  become `_`; the spec writers warn). Output: one prefab per UI, root stretched full screen, meant to go under a
  Canvas. Layer names and order (bottom → top) are kept; hidden layers are built with `SetActive(false)`.
- **Nesting**: a layer inside a sibling image / placed group drawn before it becomes its child; texts on a button
  become its label. `--no-nest` keeps only the labels.
- **Names**: PascalCase role + type suffix (`PopupFrame`, `TitleBanner`, `HeartIcon`, `CloseButton`, `TitleText`;
  texts by role, not content; swaps share the stem: `HintIcon`/`UndoIcon`; the top group is `Content`). An image
  whose final name contains `Button` gets a `Button` component.
- **Images** in `Assets/_Project/Images/UI/`: `Common/` (used by 2+ UIs; keep it even when empty) and `<UI name>/`.
  Every image is deduped against `Images/UI/**` first (exact, offset/scale, 9-slice); a match in another UI's
  folder moves to `Common/` (GUID kept). Download or export into the scratchpad; only new images go into `Assets`.
  Build UIs that share a sliced sprite one after another (Build moves files).
- **Deleting is blocked** through Unity MCP: tell the user which unused sprites (`unused_sprites`) and empty
  folders to delete by hand.
- **Fonts**: TMP SDF assets in `Assets/_Project/Fonts/`; text materials next to them
  (`"<font> Outline <Color>.mat"`, `"<font> Underlay <Color>.mat"`, `"<font> Outline <Color> Underlay <Color>.mat"`),
  reused when they match.
- **Text effects**: Stroke → TMP Outline, Drop Shadow → Underlay, Gradient Overlay / gradient fill → TMP Color
  Gradient. Anything else is listed in `warnings`: tell the user it was not built.

## Step 0: Setup (first; a Figma source can run its step 1 reads in parallel)

One call, from the Unity project root (bootstrap Python: `python3` on macOS/Linux; on Windows `py -3`, or
`python` when `py` is missing):
```bash
python3 "$S/scripts/setup.py" .
```
It prints JSON: `python` (= `$PY`), `skill` (= `$S`), `uibuilder` (`up-to-date` | `INSTALLED`) and `errors`. The
first run creates `~/.cache/datdb-uienv` (about a minute).
- `errors` not empty: STOP and tell the user what it says (no Python 3.9+: install it, on Windows from python.org
  with "Add python.exe to PATH" or `winget install Python.Python.3.12`; venv module missing; broken venv: delete
  the folder it names; not a Unity project: wrong folder).
- `uibuilder` is `INSTALLED`: Unity recompiles; MCP calls fail with "Unity not detected" for about 20 s. Check
  `Unity_GetConsoleLogs` (errors) until it answers, then go on. Tell the user the file was updated.

## Step 1: Font check (blocking, before anything else)

Get the font list without exporting anything:
- PSD: `$PY -I -B $S/scripts/make_spec.py <file.psd> --fonts-only`
- Figma: load `figma:figma-use`, `create_session` with the fileKey, then run `scripts/figma_dump.js` through
  `use_figma` with `__NODE_ID__` replaced (`node-id` `A-B` → `A:B`). It returns `fonts` and every node, hidden ones
  and text strokes/effects included. Save it as `<scratchpad>/build_<name>/figma_dump.json`. On a rate-limit error
  (Starter plan), tell the user and stop.
- PNG: compare each text with the project TMP fonts by eye. A text that doesn't clearly match one is a missing font.

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
- Any `MISSING font: …`: STOP. Tell the user which fonts are missing (PostScript name / family + style), which
  texts use them, and which `.ttf`/`.otf` in `Assets/_Project/Fonts/` look like the source (TMP Font Asset Creator →
  save the SDF asset there). Nothing was changed.

## Step 2: Spec

### PSD (one call)
```bash
$PY -I -B $S/scripts/make_spec.py <file.psd> . <scratchpad>/build_<name> [--name X] [--replace] [--no-nest] [--names N.json]
```

### Figma
1. Images, from the dump (no other Figma read is needed):
   - Image fills (`fills[].imageHash`): get their URLs with ONE `get_design_context` call (load
     `figma:figma-design-to-code` first; nodeId = the frame) and `curl -sfL` them into the scratchpad. Kind `fill`:
     effects are not baked, so a drop shadow becomes a uGUI Shadow.
   - Shapes/vectors with no image fill: render them with `download_assets` as PNG (scale 2 for small vectors; Unity
     can't use SVG) and remove the frame's grey background (rounded rect: rebuild alpha from an SDF of the radius;
     white shape: `alpha = (max(rgb) − bg) / (1 − bg)`). Kind `render`: effects and children are baked in. Render
     the smallest node that holds the art (the button's rectangle, not the button with its label).
   - The reference: `get_screenshot` of the frame, in the same parallel batch.
2. Write `<scratchpad>/build_<name>/assets.json`: `{"<node id>": {"file": "/abs/x.png", "kind": "fill" | "render"}}`.
3. ```bash
   $PY -I -B $S/scripts/figma_spec.py <build>/figma_dump.json <build>/assets.json <screenshot.png> . <build> [--name X] [--replace] [--no-nest] [--names N.json]
   ```
   A `... has no asset` warning means a visible shape is missing from assets.json: render it and run it again.

### PNG (no new images allowed)
1. `match_sprites.py locate <Images/UI> <file.png> <scratch>/locate` (~10 s). It finds mostly visible sprites
   (`placed`); heavily covered and semi-transparent sprites (glows) are usually NOT found.
2. View the mockup and the `_unexplained_N.png` crops, then pick project sprites for the rest. Write `layout.json`
   (all layers bottom → top, already well named). Add `"shadow": [0, 4, 40, 20, 42, 0.52]` where the art shows a drop
   shadow. Add each text as a spec text node (`{"type": "text", "place": "rect", ...}`, reference/spec.md) at its
   place in the order.
3. `match_sprites.py compose <file.png> layout.json <scratch>/compose --refine 3` (~30 s). View EVERY remaining crop:
   - Text not added yet: add it to layout.json. An edge leftover: ignore it, or fix the layout.
   - A graphic no project sprite reproduces is a **missing image**: STOP, build nothing, report its position, size,
     a short description and the crop path. The user must add it to `Images/UI` first.
   - Two sprite versions fit one slot: keep the lower residual and say which one you chose.
4. ```bash
   $PY -I -B $S/scripts/png_spec.py <scratch>/compose/_layout.json . <build> [--name X] [--replace] [--no-nest] [--names N.json]
   ```

### Every source: read the summary
`new_sprites`, `reused`, `move_to_common`, `sliced`, `unused_sprites`, `renamed`, `sprite_renames`, `nested` and
`variants` (check that they make sense) and `warnings`. Edit `spec.json` only when a warning needs it.

### Rename map (automatic, no confirmation)
When no map exists (no `<source>.names.json`, no `--names`) and some layer names don't follow the naming rule
(auto names like `Group 5`, `Rectangle 11`, `Shape 1 copy`, or content-named texts):
1. Look at the design once (PSD: `<build>/psd_export/_composite.png`; Figma: the screenshot) to tell each layer's
   role. Exported sizes or average colors of the layers' PNGs help with layers that are hard to spot.
2. Write the map `{"<layer name or source path>": "NewName"}`: a key for every layer that needs a new name, none
   for layers already following the rule. Repeated shapes share a stem (`Sparkle1..3`). PSD/PNG: save it as
   `<source>.names.json` next to the source file; Figma: as `<build>/names.json` and pass `--names`.
3. Run the same spec command again. `renamed` should count every key; `warnings` must not list unused keys.
4. Go straight on to step 3. Do not ask the user about the names.

PNG: you name the layers yourself in `layout.json`, so skip the map.

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
- `EXISTS: …`: ask the user (see Hard rules).
- Other validation errors (`parent not found`, `sprite not found`, `variant …: no node`, …): fix the spec and run it
  again. Nothing was changed.
- `PARTIAL: …`: a failure after validation. Tell the user exactly which changes it lists, then fix the cause.
- Read `warnings`, especially texts shrinking below their design size, strokes wider than the atlas padding, drop
  shadows shortened by the padding, importer Max Size below the image size, and font atlases set to Read/Write.

## Step 4: Verify (always, before reporting)

```bash
$PY -I -B $S/scripts/verify.py <scratchpad>/build_<name>
```
- View `sheet.png` (render | heatmap | each variant) in ONE Read. With outlined, shadowed or gradient texts, Read
  `strokes.png` in the same message. There must be no square artifacts.
- `pass` means `mean_diff` (inside the content box) ≤ 5 with only thin edges differing (BoosterUI PSD: 3.3). If it
  fails, open `heatmap.png`, fix the structural problem and re-run Build with `"replace": true` (allowed for a UI
  you just built in this turn).

## Step 5: Report (Vietnamese)

- The prefab path (`report.prefab`) and its hierarchy. Say that no scene was changed.
- Images: reused, moved to `Common/`, new; unused sprites and empty folders the user should delete.
- The rename map, when you wrote one this turn: its path and an `old → new` table. The user can edit it and rebuild
  with `--replace`.
- Fonts and text materials used or created; text effects that were not built; font assets that were changed.
- Hidden layers, what still needs the user (empty layers, onClick not wired), and what you could not verify (e.g.
  strokes of hidden variants are only checked at 1×).
