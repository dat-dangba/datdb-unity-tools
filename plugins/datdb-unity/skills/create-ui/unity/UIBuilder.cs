// Installed by the create-ui skill (plugin datdb-unity, skills/create-ui/unity/UIBuilder.cs). Edit that
// template and bump Version; the skill's setup.py re-copies it into Assets/_Project/Editor/ whenever the files differ.
//
// One call builds a whole uGUI screen from a spec.json (format: reference/spec.md in the skill) and saves it as a
// prefab in prefab_dir. CheckFonts(...) runs the font step alone, so a missing font stops the skill before any export work.
//   validate everything (fonts, prefab name, node tree, sprite sources) -> move shared sprites to Common ->
//   copy + import new sprites -> 9-slice borders -> outline materials -> temp instance in a PREVIEW scene (own world-space canvas +
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
        public const int Version = 5;

        [Serializable] public class Move { public string from; public string to; }

        [Serializable]
        public class Node
        {
            public string name, parent, type;          // type: group | image | text
            public float x, y, w, h;                   // design px, top-left of the frame
            public bool stretch, visible, empty, button;
            public string sprite;                      // Assets/... path
            public float[] tint, shadow;               // tint rgba 0-255; shadow [dx, dyDown, r, g, b, a(0-1)]
            public float[] slice;                      // sprite border [left, bottom, right, top] px -> Image Type Sliced
            public string text, font, align, place;    // align left|center|right, place baseline|rect
            public float size, leading, anchor_x, baseline_y, stroke_px;
            public float[] color, stroke_color;
            public string stroke_name;
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
            public bool visible;
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

        static List<TMP_FontAsset> FontAssets()
        {
            return AssetDatabase.FindAssets("t:TMP_FontAsset")
                .Select(g => AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(AssetDatabase.GUIDToAssetPath(g)))
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
            FW = s.frame[0]; FH = s.frame[1];
            string fontsDir = Or(s.fonts_dir, "Assets/_Project/Fonts");
            string uiRoot = Or(s.ui_root, "Assets/_Project/Images/UI");
            string prefabPath = Or(s.prefab_dir, "Assets/_Project/Prefabs/UI") + "/" + s.name + ".prefab";
            var nodes = s.nodes ?? new Node[0];

            // 1. validate everything BEFORE any change: fonts, prefab name, node tree, sprite sources
            var fontMap = new Dictionary<string, TMP_FontAsset>();
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
            foreach (var ns in s.new_sprites ?? new Move[0])
            {
                EnsureFolder(Path.GetDirectoryName(ns.to).Replace('\\', '/'));
                if (File.Exists(ns.to)) rep.warnings.Add("overwrote " + ns.to);
                File.Copy(ns.from, ns.to, true);
                AssetDatabase.ImportAsset(ns.to, ImportAssetOptions.ForceSynchronousImport);
                var ti = (TextureImporter)AssetImporter.GetAtPath(ns.to);
                ti.textureType = TextureImporterType.Sprite;
                ti.spriteImportMode = SpriteImportMode.Single;
                ti.mipmapEnabled = false;
                ti.alphaIsTransparency = true;
                ti.SaveAndReimport();
                if (AssetDatabase.LoadAssetAtPath<Sprite>(ns.to)) rep.sprites_imported.Add(ns.to);
                else { rep.errors.Add("import failed " + ns.to); return; }
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

            foreach (var f in fontMap.Values) MakeReadable(f);

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
                    if (n.stroke_px > 0)
                        mat = OutlineMat(font, fontsDir, Or(n.stroke_name, "Color"), C(n.stroke_color, Color.black), n.stroke_px, n.size, rep);
                    var t = go.AddComponent<TextMeshProUGUI>();
                    t.text = (n.text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
                    t.font = font;
                    if (mat) t.fontSharedMaterial = mat;
                    t.fontSize = n.size;
                    t.color = C(n.color, Color.black);
                    t.textWrappingMode = TextWrappingModes.NoWrap;
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
                        t.alignment = Align(n.align, false);
                    }
                    else
                    {
                        Place(rt, n.anchor_x - 400, n.baseline_y, 800, 0, p);
                        t.alignment = Align(n.align, true);
                    }
                    texts.Add(new BuiltText { path = path, node = n, t = t });
                    strokes[t] = n.stroke_px;
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
                var tr = new TextReport { path = bt.path, design = t.fontSizeMax, stroke_px = strokes[t], material = t.fontSharedMaterial.name, visible = t.gameObject.activeInHierarchy };
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

        static void MakeReadable(TMP_FontAsset f)
        {
            var tex = f.atlasTexture;
            if (tex == null || tex.isReadable) return;
            var so = new SerializedObject(tex);
            so.FindProperty("m_IsReadable").boolValue = true;
            so.ApplyModifiedProperties();
            AssetDatabase.SaveAssets();
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

        static Material OutlineMat(TMP_FontAsset font, string dir, string colorName, Color c, float strokePx, float fontSize, Report rep)
        {
            float texels = strokePx * font.faceInfo.pointSize / fontSize;
            if (texels > font.atlasPadding)
                rep.warnings.Add(font.name + ": stroke " + strokePx + "px at " + fontSize + " needs " + texels.ToString("F1") + " texels > atlas padding " + font.atlasPadding + " (ask the user before raising padding)");

            var probe = new Material(font.material);
            probe.EnableKeyword("OUTLINE_ON");
            probe.DisableKeyword("RATIOS_OFF");
            float gs = probe.GetFloat(ShaderUtilities.ID_GradientScale);
            float w = SolveWidth(probe, texels / gs / 2f);
            UnityEngine.Object.DestroyImmediate(probe);

            foreach (var g in AssetDatabase.FindAssets("t:Material", new[] { dir }))
            {
                var path = AssetDatabase.GUIDToAssetPath(g);
                var m = AssetDatabase.LoadAssetAtPath<Material>(path);
                if (m == null || !m.HasProperty(ShaderUtilities.ID_OutlineColor) || !m.IsKeywordEnabled("OUTLINE_ON")) continue;
                if (m.GetTexture(ShaderUtilities.ID_MainTex) != font.atlasTexture) continue;
                var oc = m.GetColor(ShaderUtilities.ID_OutlineColor);
                bool same = Mathf.Abs(oc.r - c.r) + Mathf.Abs(oc.g - c.g) + Mathf.Abs(oc.b - c.b) < 0.02f
                            && Mathf.Abs(m.GetFloat(ShaderUtilities.ID_OutlineWidth) - w) < 0.002f;
                if (same)
                {
                    if (!rep.materials_reused.Contains(path)) rep.materials_reused.Add(path);
                    return m;
                }
            }

            string baseName = dir + "/" + font.name + " Outline " + colorName;
            string file = baseName + ".mat";
            for (int i = 2; File.Exists(file); i++) file = baseName + " " + i + ".mat";
            var mat = new Material(font.material);
            AssetDatabase.CreateAsset(mat, file);
            mat.SetColor(ShaderUtilities.ID_OutlineColor, c);
            mat.EnableKeyword("OUTLINE_ON");
            mat.DisableKeyword("RATIOS_OFF");   // keep ratios ON; RATIOS_OFF caused square artifacts
            SolveWidth(mat, texels / gs / 2f);
            EditorUtility.SetDirty(mat);
            rep.materials_created.Add(file);
            return mat;
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
