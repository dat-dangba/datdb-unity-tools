// Installed by the create-ui skill (plugin datdb-unity, skills/create-ui/unity/UIBuilder.cs). Edit that
// template, not the installed copy: the skill's setup.py re-copies it into Assets/_Project/Editor/ whenever the bytes
// differ. Version is informational only (shown in report.log); bump it with every change so builds can be traced.
//
// One call builds a whole uGUI screen from a spec.json (format: reference/spec.md in the skill) and saves it as a
// prefab in prefab_dir. CheckFonts(...) runs the font step alone, so a missing font stops the skill before any export work.
//   validate everything (fonts, prefab name, node tree, sprite sources) -> move shared sprites to Common ->
//   copy + import new sprites -> 9-slice borders -> text materials (outline / underlay) -> temp instance in a PREVIEW scene (own world-space canvas +
//   camera) -> fit texts + auto size -> hide states -> renders (main, 2x, variants) -> save prefab ->
//   close the preview scene -> <out_dir>/report.json. The open scene is never touched.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using TMPro;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UImage = UnityEngine.UI.Image;

namespace DatdbUI
{
    public static class UIBuilder
    {
        public const int Version = 8;

        [Serializable] public class Move { public string from; public string to; }

        [Serializable]
        public class Node
        {
            public string name, parent, type;          // type: group | image | text
            public float x, y, w, h;                   // design px, top-left of the frame
            public bool stretch, visible, empty, button;
            public bool wrap;                          // text: wrap inside w (PSD paragraph text), top aligned
            public string sprite;                      // Assets/... path
            public float[] tint, shadow;               // tint rgba 0-255; shadow [dx, dyDown, r, g, b, a(0-1)]
            public float[] slice;                      // sprite border [left, bottom, right, top] px -> Image Type Sliced
            public string text, font, align, place;    // align left|center|right, place baseline|rect
            public float size, leading, anchor_x, baseline_y, stroke_px;
            public float[] color, stroke_color;
            public string stroke_name;
            public float[] underlay;                   // text drop shadow [dx, dyDown, r, g, b, a(0-1), blur px, dilate px] -> TMP Underlay
            public string underlay_name;               // color word in the material name
            public float[] gradient;                   // text Color Gradient: TL, TR, BL, BR as [r, g, b, a] 0-255 (16 numbers)
        }

        [Serializable] public class Variant { public string name; public string[] show; public string[] hide; }

        [Serializable]
        public class Spec
        {
            public string name, out_dir, ui_root, fonts_dir, prefab_dir, reference;
            public float[] frame;
            public bool replace;
            public string[] fonts;
            public Move[] move_to_common, new_sprites;
            public Node[] nodes;
            public Variant[] variants;
        }

        [Serializable]
        public class TextReport
        {
            public string path, material;
            public float design, rendered, stroke_px;
            public float[] rect;
            public bool visible, underlay, gradient;
        }

        [Serializable]
        public class Report
        {
            public bool ok;
            public string prefab;
            public List<string> errors = new List<string>(), warnings = new List<string>(), log = new List<string>();
            public List<string> sprites_moved = new List<string>(), sprites_imported = new List<string>();
            public List<string> sprites_sliced = new List<string>();
            public List<string> materials_created = new List<string>(), materials_reused = new List<string>();
            public List<string> renders = new List<string>();
            public List<TextReport> texts = new List<TextReport>();
        }

        class Built { public RectTransform rt; public float x, y, w, h; }
        class BuiltText { public string path; public Node node; public TextMeshProUGUI t; }

        static float FW, FH;

        // Font keys (PSD PostScript names / Figma "family style") -> "OK" lines, or "MISSING font: <key>" lines.
        public static string CheckFonts(params string[] keys)
        {
            var assets = FontAssets();
            return string.Join("\n", keys.Distinct().Select(k =>
            {
                var hit = MatchFont(assets, k);
                return hit ? "OK " + k + " -> " + AssetDatabase.GetAssetPath(hit) : "MISSING font: " + k;
            }));
        }

        // Stable order, so the same key always picks the same asset: main assets before "... Fallback" ones, then by path.
        static List<TMP_FontAsset> FontAssets()
        {
            return AssetDatabase.FindAssets("t:TMP_FontAsset")
                .Select(AssetDatabase.GUIDToAssetPath)
                .OrderBy(p => Path.GetFileName(p).IndexOf("fallback", StringComparison.OrdinalIgnoreCase) >= 0)
                .ThenBy(p => p, StringComparer.Ordinal)
                .Select(p => AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(p))
                .Where(f => f != null).ToList();
        }

        // family + style first (Figma "family style", most PSD PostScript names), then the asset name without "SDF"
        // and the source .ttf/.otf file name (PostScript names like MPLUSRounded1c-Black that differ from the family).
        static TMP_FontAsset MatchFont(List<TMP_FontAsset> assets, string key)
        {
            string k = N(key);
            return assets.FirstOrDefault(f => N(f.faceInfo.familyName + f.faceInfo.styleName) == k)
                ?? assets.FirstOrDefault(f => N(f.name.Replace("SDF", "")) == k)
                ?? assets.FirstOrDefault(f => N(Path.GetFileNameWithoutExtension(
                       AssetDatabase.GUIDToAssetPath(f.creationSettings.sourceFontFileGUID) ?? "")) == k);
        }

        public static string Build(string specPath)
        {
            var rep = new Report();
            Spec spec = null;
            try
            {
                spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
                Run(spec, rep);
            }
            catch (Exception e) { rep.errors.Add(e.ToString()); }
            rep.ok = rep.errors.Count == 0;
            // Validation errors change nothing; a failure after it does not roll back what was already done.
            var done = rep.sprites_moved.Concat(rep.sprites_imported).Concat(rep.sprites_sliced).Concat(rep.materials_created).ToList();
            if (!rep.ok && done.Count > 0)
                rep.errors.Add("PARTIAL: these changes were made before the error and were NOT rolled back: " + string.Join("; ", done));
            rep.log.Add("UIBuilder version " + Version);
            string json = JsonUtility.ToJson(rep, true);
            if (spec != null && !string.IsNullOrEmpty(spec.out_dir))
            {
                Directory.CreateDirectory(spec.out_dir);
                File.WriteAllText(Path.Combine(spec.out_dir, "report.json"), json);
            }
            return json;
        }

        static string Or(string s, string d) { return string.IsNullOrEmpty(s) ? d : s; }
        static string N(string s) { return new string((s ?? "").ToLowerInvariant().Where(char.IsLetterOrDigit).ToArray()); }
        static Color C(float[] c, Color d)
        {
            if (c == null || c.Length < 3) return d;
            return new Color(c[0] / 255f, c[1] / 255f, c[2] / 255f, c.Length > 3 ? c[3] / 255f : 1f);
        }

        static void Run(Spec s, Report rep)
        {
            if (s.frame == null || s.frame.Length < 2 || s.frame[0] <= 0 || s.frame[1] <= 0)
            {
                rep.errors.Add("spec.frame must be [width, height] > 0");
                return;
            }
            FW = s.frame[0]; FH = s.frame[1];
            string fontsDir = Or(s.fonts_dir, "Assets/_Project/Fonts");
            string uiRoot = Or(s.ui_root, "Assets/_Project/Images/UI");
            string prefabPath = Or(s.prefab_dir, "Assets/_Project/Prefabs/UI") + "/" + s.name + ".prefab";
            var nodes = s.nodes ?? new Node[0];

            // 1. validate everything BEFORE any change: fonts, prefab name, node tree, sprite sources
            var fontMap = new Dictionary<string, TMP_FontAsset>();
            matExpect.Clear();
            bool exists = File.Exists(prefabPath);
            Validate(s, rep, nodes, fontMap, prefabPath, exists);
            if (rep.errors.Count > 0) return;

            // 2. sprites: move shared ones to Common, copy + import new ones
            EnsureFolder(uiRoot + "/Common");
            foreach (var m in s.move_to_common ?? new Move[0])
            {
                EnsureFolder(Path.GetDirectoryName(m.to).Replace('\\', '/'));
                string err = AssetDatabase.MoveAsset(m.from, m.to);
                bool okDisk = File.Exists(m.to) && !File.Exists(m.from);
                if (okDisk) rep.sprites_moved.Add(m.from + " -> " + m.to);
                else { rep.errors.Add("move failed " + m.from + " -> " + m.to + " " + err); return; }
            }
            // new sprites: copy all, import them in ONE batch, set the sprite settings, reimport in ONE batch
            var news = s.new_sprites ?? new Move[0];
            foreach (var ns in news)
            {
                EnsureFolder(Path.GetDirectoryName(ns.to).Replace('\\', '/'));
                if (File.Exists(ns.to)) rep.warnings.Add("overwrote " + ns.to);
                File.Copy(ns.from, ns.to, true);
            }
            if (news.Length > 0)
            {
                Batch(() => { foreach (var ns in news) AssetDatabase.ImportAsset(ns.to); });
                Batch(() =>
                {
                    foreach (var ns in news)
                    {
                        var ti = AssetImporter.GetAtPath(ns.to) as TextureImporter;
                        if (ti == null) continue;   // reported below
                        ti.textureType = TextureImporterType.Sprite;
                        ti.spriteImportMode = SpriteImportMode.Single;
                        ti.mipmapEnabled = false;
                        ti.alphaIsTransparency = true;
                        int need = MaxSizeFor(ns.to);
                        if (need > ti.maxTextureSize) ti.maxTextureSize = need;   // never downscale a design image
                        ti.SaveAndReimport();
                    }
                });
                foreach (var ns in news)
                    if (AssetDatabase.LoadAssetAtPath<Sprite>(ns.to)) rep.sprites_imported.Add(ns.to);
                    else rep.errors.Add("import failed " + ns.to);
                if (rep.errors.Count > 0) return;
            }

            // 2b. 9-slice borders (the Sprite Editor border), set once per sprite; a different existing border is kept
            foreach (var g in nodes.Where(n => n.type == "image" && !n.empty && n.slice != null && n.slice.Length == 4).GroupBy(n => n.sprite))
            {
                var want = new Vector4(g.First().slice[0], g.First().slice[1], g.First().slice[2], g.First().slice[3]);
                var ti = (TextureImporter)AssetImporter.GetAtPath(g.Key);
                if (ti.spriteBorder == Vector4.zero)
                {
                    ti.spriteBorder = want;
                    ti.SaveAndReimport();
                    var sp = AssetDatabase.LoadAssetAtPath<Sprite>(g.Key);
                    if (sp && sp.border == want) rep.sprites_sliced.Add(g.Key + " border " + want);
                    else { rep.errors.Add("setting the sprite border failed for " + g.Key); return; }
                }
                else if ((ti.spriteBorder - want).sqrMagnitude > 4f)
                    rep.warnings.Add(g.Key + " keeps its border " + ti.spriteBorder + " (spec wants " + want + "); check the Sliced render");
            }

            // reused sprites whose importer would downscale them (Max Size below the image size)
            foreach (var sp in nodes.Where(n => n.type == "image" && !n.empty && !string.IsNullOrEmpty(n.sprite)).Select(n => n.sprite).Distinct())
            {
                var ti = AssetImporter.GetAtPath(sp) as TextureImporter;
                int need = MaxSizeFor(sp);
                if (ti != null && need > ti.maxTextureSize)
                    rep.warnings.Add(sp + ": importer Max Size " + ti.maxTextureSize + " is smaller than the image (needs " + need + "); Unity downscales it. Not changed (shared sprite): raise it by hand if it looks blurry");
            }

            foreach (var f in fontMap.Values.Distinct()) MakeReadable(f, rep);

            // 3. hierarchy in a preview scene: TMP layout and renders need a live canvas, the open scene stays untouched
            var scene = EditorSceneManager.NewPreviewScene();
            try
            {
                var cam = PreviewCamera(scene);
                var canvasGo = new GameObject("Canvas", typeof(RectTransform));
                canvasGo.layer = 5;
                SceneManager.MoveGameObjectToScene(canvasGo, scene);
                var cv = canvasGo.AddComponent<Canvas>();
                cv.renderMode = RenderMode.WorldSpace;
                cv.worldCamera = cam;
                ((RectTransform)canvasGo.transform).sizeDelta = new Vector2(FW, FH);
                var rootGo = Make(s.name, canvasGo.transform);
                BuildInstance(s, rep, nodes, fontMap, fontsDir, cam, rootGo, prefabPath, exists);
            }
            finally { EditorSceneManager.ClosePreviewScene(scene); }
        }

        static void Validate(Spec s, Report rep, Node[] nodes, Dictionary<string, TMP_FontAsset> fontMap, string prefabPath, bool exists)
        {
            if (string.IsNullOrEmpty(s.name)) rep.errors.Add("spec.name is empty");
            if (exists && !s.replace) rep.errors.Add("EXISTS: " + prefabPath + " (ask the user: replace or another name)");

            var assets = FontAssets();
            var needed = (s.fonts ?? new string[0]).Concat(nodes.Where(n => n.type == "text").Select(n => n.font)).Distinct();
            foreach (var key in needed)
            {
                var hit = string.IsNullOrEmpty(key) ? null : MatchFont(assets, key);
                if (hit) { fontMap[key] = hit; rep.log.Add("font " + key + " -> " + AssetDatabase.GetAssetPath(hit)); }
                else
                {
                    var users = nodes.Where(n => n.type == "text" && n.font == key).Select(n => n.name);
                    rep.errors.Add("MISSING font: " + key + " (texts: " + string.Join(", ", users) + ")");
                }
            }

            var moves = s.move_to_common ?? new Move[0];
            var news = s.new_sprites ?? new Move[0];
            foreach (var m in moves)
                if (!File.Exists(m.from)) rep.errors.Add("move_to_common source missing: " + m.from);
                else if (File.Exists(m.to)) rep.errors.Add("move_to_common target exists: " + m.to);
            foreach (var ns in news)
                if (!File.Exists(ns.from)) rep.errors.Add("new sprite source missing: " + ns.from);
            var coming = new HashSet<string>(moves.Select(m => m.to).Concat(news.Select(n => n.to)));
            var leaving = new HashSet<string>(moves.Select(m => m.from));

            var paths = new HashSet<string> { "" };
            foreach (var n in nodes)
            {
                string parent = n.parent ?? "";
                string path = parent == "" ? n.name : parent + "/" + n.name;
                if (string.IsNullOrEmpty(n.name)) rep.errors.Add("node with empty name under '" + parent + "'");
                if (!paths.Contains(parent)) rep.errors.Add("parent not found (or listed after its child) for " + path + ": '" + parent + "'");
                if (n.type != "group" && n.type != "image" && n.type != "text") rep.errors.Add("unknown node type '" + n.type + "' for " + path);
                if (n.type == "image" && !n.empty)
                {
                    if (string.IsNullOrEmpty(n.sprite)) rep.errors.Add("image " + path + " has no sprite (set empty: true for a placeholder)");
                    else if (leaving.Contains(n.sprite)) rep.errors.Add("image " + path + " uses " + n.sprite + ", which move_to_common moves away; use the 'to' path");
                    else if (!coming.Contains(n.sprite) && !AssetDatabase.LoadAssetAtPath<Sprite>(n.sprite)) rep.errors.Add("sprite not found for " + path + ": " + n.sprite);
                }
                if ((n.type == "image" || n.type == "text") && (n.w <= 0 || n.h <= 0) && !(n.type == "text" && n.place == "baseline"))
                    rep.errors.Add(n.type + " " + path + " has no size (w/h)");
                if (n.slice != null && n.slice.Length > 0 && (n.slice.Length != 4 || n.slice.Any(v => v < 0) ||
                    n.slice[0] + n.slice[2] > n.w || n.slice[1] + n.slice[3] > n.h))
                    rep.errors.Add("image " + path + ": slice must be [left, bottom, right, top] >= 0 and fit in w/h");
                if (!paths.Add(path)) rep.warnings.Add("duplicate path " + path + " (variants can only reach the first one)");
            }
            foreach (var v in s.variants ?? new Variant[0])
                foreach (var pth in (v.show ?? new string[0]).Concat(v.hide ?? new string[0]))
                    if (!paths.Contains(pth)) rep.errors.Add("variant " + v.name + ": no node " + pth);
        }

        static Camera PreviewCamera(Scene scene)
        {
            var go = new GameObject("PreviewCamera");
            SceneManager.MoveGameObjectToScene(go, scene);
            var cam = go.AddComponent<Camera>();
            cam.scene = scene;
            cam.enabled = false;
            cam.orthographic = true;
            cam.orthographicSize = FH / 2f;
            cam.transform.position = new Vector3(0, 0, -100);
            cam.nearClipPlane = 0.1f;
            cam.farClipPlane = 1000f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = Color.white;
            return cam;
        }

        static void BuildInstance(Spec s, Report rep, Node[] nodes, Dictionary<string, TMP_FontAsset> fontMap, string fontsDir,
                                  Camera cam, GameObject rootGo, string prefabPath, bool exists)
        {
            Stretch((RectTransform)rootGo.transform);
            var built = new Dictionary<string, Built> { { "", new Built { rt = (RectTransform)rootGo.transform, x = 0, y = 0, w = FW, h = FH } } };
            var texts = new List<BuiltText>();
            var strokes = new Dictionary<TextMeshProUGUI, float>();
            var hide = new List<GameObject>();

            foreach (var n in nodes)
            {
                string parentPath = n.parent ?? "";
                var p = built[parentPath];   // Validate checked the tree
                string path = parentPath == "" ? n.name : parentPath + "/" + n.name;
                var go = Make(n.name, p.rt);
                var rt = (RectTransform)go.transform;
                var b = new Built { rt = rt, x = n.x, y = n.y, w = n.w, h = n.h };

                if (n.type == "group")
                {
                    if (n.stretch || (n.w <= 0 && n.h <= 0)) { Stretch(rt); b.x = p.x; b.y = p.y; b.w = p.w; b.h = p.h; }
                    else Place(rt, n.x, n.y, n.w, n.h, p);
                }
                else if (n.type == "image")
                {
                    Place(rt, n.x, n.y, n.w, n.h, p);
                    var img = go.AddComponent<UImage>();
                    img.sprite = n.empty || string.IsNullOrEmpty(n.sprite) ? null : AssetDatabase.LoadAssetAtPath<Sprite>(n.sprite);
                    img.color = C(n.tint, Color.white);
                    img.raycastTarget = n.button;
                    if (img.sprite && n.slice != null && n.slice.Length == 4 && img.sprite.border != Vector4.zero)
                    {
                        img.type = UImage.Type.Sliced;
                        img.fillCenter = true;
                        img.pixelsPerUnitMultiplier = 100f / img.sprite.pixelsPerUnit;   // border in design px on a 100 PPU canvas
                    }
                    if (n.empty) { img.enabled = false; rep.warnings.Add("empty layer " + path + ": Image disabled"); }
                    if (n.shadow != null && n.shadow.Length >= 6)
                    {
                        var sh = go.AddComponent<Shadow>();
                        sh.effectColor = new Color(n.shadow[2] / 255f, n.shadow[3] / 255f, n.shadow[4] / 255f, n.shadow[5]);
                        sh.effectDistance = new Vector2(n.shadow[0], -n.shadow[1]);
                    }
                    if (n.button)
                    {
                        var btn = go.AddComponent<Button>();
                        btn.targetGraphic = img;
                    }
                }
                else if (n.type == "text")
                {
                    var font = fontMap[n.font];
                    Material mat = null;
                    if (n.stroke_px > 0 || HasUnderlay(n))
                        mat = TextMat(font, fontsDir, n, rep);
                    var t = go.AddComponent<TextMeshProUGUI>();
                    t.text = (n.text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
                    t.font = font;
                    if (mat) t.fontSharedMaterial = mat;
                    t.fontSize = n.size;
                    t.color = C(n.color, Color.black);
                    if (n.gradient != null && n.gradient.Length >= 16)
                    {
                        Func<int, Color> corner = i => new Color(n.gradient[i] / 255f, n.gradient[i + 1] / 255f, n.gradient[i + 2] / 255f, n.gradient[i + 3] / 255f);
                        t.enableVertexGradient = true;
                        t.colorGradient = new VertexGradient(corner(0), corner(4), corner(8), corner(12));
                    }
                    t.textWrappingMode = n.wrap ? TextWrappingModes.Normal : TextWrappingModes.NoWrap;
                    t.overflowMode = TextOverflowModes.Overflow;
                    t.raycastTarget = false;
                    if (n.leading > 0)
                    {
                        float defaultLine = font.faceInfo.lineHeight * n.size / font.faceInfo.pointSize;
                        t.lineSpacing = (n.leading - defaultLine) / n.size * 100f;
                    }
                    if (n.place == "rect")
                    {
                        Place(rt, n.x, n.y, n.w, n.h, p);
                        // paragraph text lays out from the top of its box, like Photoshop; Fit re-centres it after
                        t.alignment = n.wrap ? AlignTop(n.align) : Align(n.align, false);
                    }
                    else
                    {
                        // Photoshop point text: anchor_x is the LEFT edge (left), the centre (center) or the RIGHT
                        // edge (right) of the line, so the temporary rect must start, centre or end there
                        const float W = 4000f;
                        float left = n.align == "left" ? n.anchor_x : n.align == "right" ? n.anchor_x - W : n.anchor_x - W / 2f;
                        Place(rt, left, n.baseline_y, W, 0, p);
                        t.alignment = Align(n.align, true);
                    }
                    texts.Add(new BuiltText { path = path, node = n, t = t });
                    strokes[t] = n.stroke_px > 0 || HasUnderlay(n) || t.enableVertexGradient ? Mathf.Max(n.stroke_px, 0.01f) : 0f;   // > 0: render_2x close-ups
                }

                if (!built.ContainsKey(path)) built[path] = b;
                if (!n.visible) hide.Add(go);
            }

            // 5. fit texts + auto size (everything is still active here)
            Canvas.ForceUpdateCanvases();
            foreach (var bt in texts) Fit(bt.t, Align(bt.node.align, false));

            // 6. hidden states
            foreach (var go in hide) go.SetActive(false);

            foreach (var bt in texts)
            {
                var t = bt.t;
                var tr = new TextReport { path = bt.path, design = t.fontSizeMax, stroke_px = bt.node.stroke_px, material = t.fontSharedMaterial.name,
                                         visible = t.gameObject.activeInHierarchy, underlay = HasUnderlay(bt.node), gradient = t.enableVertexGradient };
                bool was = t.gameObject.activeSelf;
                var chain = Activate(t.transform, rootGo.transform);
                t.ForceMeshUpdate(true);
                tr.rendered = t.fontSize;
                tr.rect = FrameRect(t.rectTransform, (RectTransform)rootGo.transform);
                foreach (var g in chain) g.SetActive(false);
                if (tr.rendered < tr.design - 0.01f) rep.warnings.Add("text " + bt.path + " shrinks to " + tr.rendered + " (design " + tr.design + ")");
                rep.texts.Add(tr);
            }

            // 7. renders (the preview scene holds only this UI)
            if (!string.IsNullOrEmpty(s.out_dir))
                RenderAll(s, rep, cam, rootGo.transform, strokes.Values.Any(v => v > 0));

            // 8. save prefab (overwriting keeps the prefab GUID, so existing scene references survive)
            EnsureFolder(Path.GetDirectoryName(prefabPath).Replace('\\', '/'));
            bool saved;
            PrefabUtility.SaveAsPrefabAsset(rootGo, prefabPath, out saved);
            AssetDatabase.SaveAssets();
            if (!saved || !File.Exists(prefabPath)) { rep.errors.Add("prefab save failed: " + prefabPath); return; }
            CheckTextMats(rep);
            rep.prefab = prefabPath;
            rep.log.Add((exists ? "replaced " : "created ") + prefabPath + " with " + nodes.Length + " nodes");
        }

        static void RenderAll(Spec s, Report rep, Camera cam, Transform root, bool anyStroke)
        {
            Directory.CreateDirectory(s.out_dir);
            rep.renders.Add(Render(cam, Path.Combine(s.out_dir, "render.png"), 1));
            if (anyStroke) rep.renders.Add(Render(cam, Path.Combine(s.out_dir, "render_2x.png"), 2));
            foreach (var v in s.variants ?? new Variant[0])
            {
                var touched = new Dictionary<GameObject, bool>();
                Action<string[], bool> set = (paths, on) =>
                {
                    foreach (var pth in paths ?? new string[0])
                    {
                        var tf = root.Find(pth);
                        if (!tf) { rep.warnings.Add("variant " + v.name + ": not found " + pth); continue; }
                        if (!touched.ContainsKey(tf.gameObject)) touched[tf.gameObject] = tf.gameObject.activeSelf;
                        tf.gameObject.SetActive(on);
                    }
                };
                set(v.hide, false);
                set(v.show, true);
                rep.renders.Add(Render(cam, Path.Combine(s.out_dir, "render_" + v.name + ".png"), 1));
                foreach (var kv in touched) kv.Key.SetActive(kv.Value);
            }
        }

        // ------------------------------------------------------------------ helpers
        static GameObject Make(string name, Transform parent)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.layer = 5;
            go.transform.SetParent(parent, false);
            return go;
        }

        static void Stretch(RectTransform rt)
        {
            rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one; rt.pivot = new Vector2(0.5f, 0.5f);
            rt.offsetMin = rt.offsetMax = Vector2.zero;
        }

        static void Place(RectTransform rt, float x, float y, float w, float h, Built p)
        {
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
            rt.sizeDelta = new Vector2(w, h);
            rt.anchoredPosition = new Vector2((x + w / 2f) - (p.x + p.w / 2f), -((y + h / 2f) - (p.y + p.h / 2f)));
        }

        static TextAlignmentOptions Align(string a, bool baseline)
        {
            switch (a)
            {
                case "left": return baseline ? TextAlignmentOptions.BaselineLeft : TextAlignmentOptions.Left;
                case "right": return baseline ? TextAlignmentOptions.BaselineRight : TextAlignmentOptions.Right;
                default: return baseline ? TextAlignmentOptions.Baseline : TextAlignmentOptions.Center;
            }
        }

        static TextAlignmentOptions AlignTop(string a)
        {
            return a == "left" ? TextAlignmentOptions.TopLeft : a == "right" ? TextAlignmentOptions.TopRight : TextAlignmentOptions.Top;
        }

        static void Fit(TextMeshProUGUI t, TextAlignmentOptions final)
        {
            t.ForceMeshUpdate(true);
            var rt = t.rectTransform; var parent = (RectTransform)rt.parent;
            if (t.textInfo.lineCount == 0) return;
            Vector3 oldCenter = parent.InverseTransformPoint(rt.TransformPoint(t.textBounds.center));
            var info = t.textInfo;
            float blockH = info.lineInfo[0].ascender - info.lineInfo[info.lineCount - 1].descender;
            t.alignment = final;
            rt.sizeDelta = new Vector2(Mathf.Ceil(t.textBounds.size.x) + 2, Mathf.Ceil(blockH) + 2);
            t.ForceMeshUpdate(true);
            Vector3 newCenter = parent.InverseTransformPoint(rt.TransformPoint(t.textBounds.center));
            rt.anchoredPosition += (Vector2)(oldCenter - newCenter);
            float design = t.fontSize;
            t.fontSizeMax = design;
            t.fontSizeMin = Mathf.Round(design * 0.5f);
            t.enableAutoSizing = true;
            t.ForceMeshUpdate(true);
        }

        // activates t and its inactive ancestors up to root; returns what it turned on
        static List<GameObject> Activate(Transform t, Transform root)
        {
            var on = new List<GameObject>();
            for (var c = t; c != null && c != root.parent; c = c.parent)
                if (!c.gameObject.activeSelf) { c.gameObject.SetActive(true); on.Add(c.gameObject); }
            return on;
        }

        static float[] FrameRect(RectTransform rt, RectTransform root)
        {
            var corners = new Vector3[4];
            rt.GetWorldCorners(corners);
            var a = root.InverseTransformPoint(corners[0]);   // bottom-left
            var b = root.InverseTransformPoint(corners[2]);   // top-right
            return new[] { a.x + FW / 2f, FH / 2f - b.y, b.x - a.x, b.y - a.y };
        }

        static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            string parent = Path.GetDirectoryName(path).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
        }

        static void MakeReadable(TMP_FontAsset f, Report rep)
        {
            var tex = f.atlasTexture;
            if (tex == null || tex.isReadable) return;
            var so = new SerializedObject(tex);
            so.FindProperty("m_IsReadable").boolValue = true;
            so.ApplyModifiedProperties();
            AssetDatabase.SaveAssets();
            rep.warnings.Add("font " + AssetDatabase.GetAssetPath(f) + ": atlas texture set to Read/Write (needed by the dynamic atlas); this changed the font asset");
        }

        static void Batch(Action a)
        {
            AssetDatabase.StartAssetEditing();
            try { a(); }
            finally { AssetDatabase.StopAssetEditing(); }
        }

        // Image size from the PNG header (no texture load); (0, 0) when the file is not a PNG.
        internal static Vector2Int PngSize(string path)
        {
            try
            {
                using (var fs = File.OpenRead(path))
                {
                    var b = new byte[24];
                    if (fs.Read(b, 0, 24) < 24 || b[0] != 0x89 || b[1] != 0x50 || b[2] != 0x4E || b[3] != 0x47) return Vector2Int.zero;
                    return new Vector2Int((b[16] << 24) | (b[17] << 16) | (b[18] << 8) | b[19], (b[20] << 24) | (b[21] << 16) | (b[22] << 8) | b[23]);
                }
            }
            catch (IOException) { return Vector2Int.zero; }
        }

        // The smallest importer Max Size (power of two, 32..16384) that keeps the image at full size; 0 = unknown.
        static int MaxSizeFor(string path)
        {
            var sz = PngSize(path);
            int m = Mathf.Max(sz.x, sz.y);
            if (m <= 0) return 0;
            int p = 32;
            while (p < m && p < 16384) p *= 2;
            return p;
        }

        // "Outside" stroke: outward = 2 * width * ratioA * gradientScale texels; dilate == width keeps the face size.
        static float SolveWidth(Material m, float target)
        {
            float w = target;
            for (int i = 0; i < 50; i++)
            {
                m.SetFloat(ShaderUtilities.ID_OutlineWidth, w);
                m.SetFloat(ShaderUtilities.ID_FaceDilate, w);
                ShaderUtilities.UpdateShaderRatios(m);
                float eff = w * m.GetFloat(ShaderUtilities.ID_ScaleRatio_A);
                if (Mathf.Abs(eff - target) < 0.0005f) break;
                w = Mathf.Min(1f, w * target / eff);
            }
            return w;
        }

        static bool HasUnderlay(Node n) { return n.underlay != null && n.underlay.Length >= 6; }

        // Underlay offset moves u * ratioC * gradientScale texels, softness widens the edge by 2 * s * ratioC * gs texels
        // and dilate grows it by d * ratioC * gs texels (TMP_SDF.shader). ratioC depends on all three, so iterate.
        // ratioC also shrinks everything to fit the atlas padding (minus the bold-weight reserve), so the achieved
        // offset can be shorter than asked. Returns the achieved offset in texels.
        static float SolveUnderlayOnce(Material m, float dx, float dyUp, float blur, float dil, float gs)
        {
            float rc = 1f;
            for (int i = 0; i < 40; i++)
            {
                m.SetFloat(ShaderUtilities.ID_UnderlayOffsetX, Mathf.Clamp(dx / (rc * gs), -1f, 1f));
                m.SetFloat(ShaderUtilities.ID_UnderlayOffsetY, Mathf.Clamp(dyUp / (rc * gs), -1f, 1f));
                m.SetFloat(ShaderUtilities.ID_UnderlaySoftness, Mathf.Clamp01(blur / (2f * gs * rc)));
                m.SetFloat(ShaderUtilities.ID_UnderlayDilate, Mathf.Clamp(dil / (gs * rc), -1f, 1f));
                ShaderUtilities.UpdateShaderRatios(m);
                float r2 = m.GetFloat(ShaderUtilities.ID_ScaleRatio_C);
                if (r2 <= 0f || Mathf.Abs(r2 - rc) < 1e-5f) break;
                rc = r2;
            }
            rc = m.GetFloat(ShaderUtilities.ID_ScaleRatio_C);
            float ox = m.GetFloat(ShaderUtilities.ID_UnderlayOffsetX) * rc * gs, oy = m.GetFloat(ShaderUtilities.ID_UnderlayOffsetY) * rc * gs;
            return Mathf.Sqrt(ox * ox + oy * oy);
        }

        // Keeps the offset first: when the padding is too small it drops the dilate, then the blur. -> what was dropped.
        static string SolveUnderlay(Material m, float[] u, float pxToTexel, float gs, out float achieved, out float wanted)
        {
            float dx = u[0] * pxToTexel, dyUp = -u[1] * pxToTexel;
            float blur = (u.Length > 6 ? u[6] : 0f) * pxToTexel, dil = (u.Length > 7 ? u[7] : 0f) * pxToTexel;
            wanted = Mathf.Sqrt(dx * dx + dyUp * dyUp);
            achieved = SolveUnderlayOnce(m, dx, dyUp, blur, dil, gs);
            if (wanted - achieved < 0.25f * pxToTexel) return "";
            if (dil > 0f)
            {
                achieved = SolveUnderlayOnce(m, dx, dyUp, blur, 0f, gs);
                if (wanted - achieved < 0.25f * pxToTexel || blur <= 0f) return "spread";
            }
            if (blur > 0f)
            {
                achieved = SolveUnderlayOnce(m, dx, dyUp, 0f, 0f, gs);
                return dil > 0f ? "spread and blur" : "blur";
            }
            return "";
        }

        static bool Near(Color a, Color b) { return Mathf.Abs(a.r - b.r) + Mathf.Abs(a.g - b.g) + Mathf.Abs(a.b - b.b) + Mathf.Abs(a.a - b.a) < 0.02f; }
        static bool Near(Material a, Material b, int id) { return Mathf.Abs(a.GetFloat(id) - b.GetFloat(id)) < 0.002f; }

        // path -> {outline, underlay}: what CheckTextMats expects on disk
        static readonly Dictionary<string, bool[]> matExpect = new Dictionary<string, bool[]>();

        // One material per (atlas, outline color + width, underlay color + offset + softness + dilate), named
        // "<font> Outline <Color>[ Underlay <Color>].mat" or "<font> Underlay <Color>.mat"; an existing match is reused.
        static Material TextMat(TMP_FontAsset font, string dir, Node n, Report rep)
        {
            bool outline = n.stroke_px > 0, under = HasUnderlay(n);
            float pxToTexel = font.faceInfo.pointSize / n.size;
            var mat = new Material(font.material);
            mat.DisableKeyword("RATIOS_OFF");   // keep ratios ON; RATIOS_OFF caused square artifacts
            float gs = mat.GetFloat(ShaderUtilities.ID_GradientScale);
            if (outline)
            {
                float texels = n.stroke_px * pxToTexel;
                if (texels > font.atlasPadding)
                    rep.warnings.Add(font.name + ": stroke " + n.stroke_px + "px at " + n.size + " needs " + texels.ToString("F1") + " texels > atlas padding " + font.atlasPadding + " (ask the user before raising padding)");
                mat.EnableKeyword("OUTLINE_ON");
                mat.SetColor(ShaderUtilities.ID_OutlineColor, C(n.stroke_color, Color.black));
            }
            if (under)
            {
                var u = n.underlay;
                if (!mat.HasProperty(ShaderUtilities.ID_UnderlayColor))
                    rep.warnings.Add(font.name + ": shader " + mat.shader.name + " has no Underlay; drop shadow not built");
                mat.EnableKeyword("UNDERLAY_ON");
                mat.SetColor(ShaderUtilities.ID_UnderlayColor, new Color(u[2] / 255f, u[3] / 255f, u[4] / 255f, u[5]));
            }
            string dropped = "";
            float achieved = 0f, wanted = 0f;
            for (int k = 0; k < 4; k++)   // the ratios depend on both effects
            {
                if (outline) SolveWidth(mat, n.stroke_px * pxToTexel / gs / 2f);
                if (under) dropped = SolveUnderlay(mat, n.underlay, pxToTexel, gs, out achieved, out wanted);
            }
            if (under && dropped != "")
                rep.warnings.Add(font.name + " at " + n.size + ": drop shadow " + dropped + " dropped to fit the atlas padding " + font.atlasPadding);
            if (under && wanted - achieved >= 0.25f * pxToTexel)
                rep.warnings.Add(font.name + " at " + n.size + ": drop shadow offset " + (wanted / pxToTexel).ToString("F1") + "px built as "
                                 + (achieved / pxToTexel).ToString("F1") + "px (atlas padding " + font.atlasPadding + "; ask the user before raising it)");

            foreach (var g in AssetDatabase.FindAssets("t:Material", new[] { dir }))
            {
                var path = AssetDatabase.GUIDToAssetPath(g);
                var m = AssetDatabase.LoadAssetAtPath<Material>(path);
                if (m == null || m.shader != mat.shader || m.GetTexture(ShaderUtilities.ID_MainTex) != font.atlasTexture) continue;
                if (m.IsKeywordEnabled("OUTLINE_ON") != outline || m.IsKeywordEnabled("UNDERLAY_ON") != under) continue;
                if (outline && !(Near(m.GetColor(ShaderUtilities.ID_OutlineColor), mat.GetColor(ShaderUtilities.ID_OutlineColor))
                                 && Near(m, mat, ShaderUtilities.ID_OutlineWidth) && Near(m, mat, ShaderUtilities.ID_FaceDilate))) continue;
                if (under && !(Near(m.GetColor(ShaderUtilities.ID_UnderlayColor), mat.GetColor(ShaderUtilities.ID_UnderlayColor))
                               && Near(m, mat, ShaderUtilities.ID_UnderlayOffsetX) && Near(m, mat, ShaderUtilities.ID_UnderlayOffsetY)
                               && Near(m, mat, ShaderUtilities.ID_UnderlaySoftness) && Near(m, mat, ShaderUtilities.ID_UnderlayDilate))) continue;
                UnityEngine.Object.DestroyImmediate(mat);
                if (!rep.materials_reused.Contains(path)) rep.materials_reused.Add(path);
                matExpect[path] = new[] { outline, under };
                return m;
            }

            string baseName = dir + "/" + font.name + (outline ? " Outline " + Or(n.stroke_name, "Color") : "")
                              + (under ? " Underlay " + Or(n.underlay_name, "Color") : "");
            string file = baseName + ".mat";
            for (int i = 2; File.Exists(file); i++) file = baseName + " " + i + ".mat";
            // Everything is set BEFORE CreateAsset: changes made after it were lost on disk (PausedUI/BoosterUI,
            // Version 5), so the first write must already hold the effects. CheckTextMats checks the files after the build.
            AssetDatabase.CreateAsset(mat, file);
            rep.materials_created.Add(file);
            matExpect[file] = new[] { outline, under };
            return mat;
        }

        // The renders use the in-memory materials, so a material that is wrong on disk would still pass verify.py.
        static void CheckTextMats(Report rep)
        {
            foreach (var kv in matExpect)
            {
                string txt = File.Exists(kv.Key) ? File.ReadAllText(kv.Key) : "";
                if (kv.Value[0] && (!txt.Contains("OUTLINE_ON") || txt.Contains("_OutlineWidth: 0\n")))
                    rep.errors.Add("outline material not saved on disk (no OUTLINE_ON or width 0): " + kv.Key);
                if (kv.Value[1] && !txt.Contains("UNDERLAY_ON"))
                    rep.errors.Add("underlay material not saved on disk (no UNDERLAY_ON): " + kv.Key);
            }
        }

        static string Render(Camera cam, string file, int scale)
        {
            int w = (int)FW * scale, h = (int)FH * scale;
            var rt = new RenderTexture(w, h, 24);
            cam.targetTexture = rt;
            Canvas.ForceUpdateCanvases(); cam.Render();
            RenderTexture.active = rt;
            var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, w, h), 0, 0); tex.Apply();
            RenderTexture.active = null;
            cam.targetTexture = null;
            File.WriteAllBytes(file, tex.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(rt);
            UnityEngine.Object.DestroyImmediate(tex);
            return file;
        }
    }
}
