"""Unit tests for the pure helpers of the create-ui scripts. Standard unittest: only the skill's venv is needed.

Usage: <venv python> -I -B tests/run_tests.py        (exit code 1 on failure)
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))   # -I drops the script dir

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import match_sprites  # noqa: E402
import spec_common as sc  # noqa: E402


def img(path, arr):
    Image.fromarray(np.asarray(arr, dtype=np.uint8)).save(path)
    return path


def button(w, h=40, edge=6):
    """A button-like sprite: dark 6 px edge, flat orange middle (stretchable both ways)."""
    a = np.zeros((h, w, 4), np.uint8)
    a[...] = (30, 30, 30, 255)
    a[edge:h - edge, edge:w - edge] = (250, 140, 20, 255)
    return a


class ParseArgs(unittest.TestCase):
    def test_flags(self):
        pos, name, replace, nest, names = sc.parse_args(["a.psd", ".", "out", "--name", "X", "--replace", "--no-nest"], 3)
        self.assertEqual((pos, name, replace, nest, names), (["a.psd", ".", "out"], "X", True, False, None))

    def test_missing_value(self):
        with self.assertRaises(SystemExit):
            sc.parse_args(["a.psd", ".", "out", "--name"], 3)
        with self.assertRaises(SystemExit):
            sc.parse_args(["a.psd", ".", "out", "--name", "--replace"], 3)

    def test_unknown_option(self):
        with self.assertRaises(SystemExit):
            sc.parse_args(["a.psd", ".", "out", "--replase"], 3)

    def test_too_few(self):
        with self.assertRaises(SystemExit):
            sc.parse_args(["a.psd"], 3)


class Names(unittest.TestCase):
    def test_safe_ui_name(self):
        w = []
        self.assertEqual(sc.safe_ui_name("Popup / Shop", w), "Popup_Shop")
        self.assertEqual(sc.safe_ui_name('a:b*c?"d<e>f|g\\h', w), "a_b_c_d_e_f_g_h")
        self.assertEqual(len(w), 2)
        w = []
        self.assertEqual(sc.safe_ui_name("BoosterUI", w), "BoosterUI")
        self.assertEqual(w, [])
        self.assertEqual(sc.safe_ui_name("///", []), "UI")

    def test_ps_align(self):
        w = []
        self.assertEqual([sc.ps_align(j, "t", w) for j in range(7)],
                         ["left", "right", "center", "left", "right", "center", "left"])
        self.assertEqual(len(w), 4)   # only the justified ones warn

    def test_unique_name(self):
        used, w = set(), []
        self.assertEqual(sc.unique_name("", "Icon", used, w), "Icon")
        self.assertEqual(sc.unique_name("", "Icon", used, w), "Icon 2")
        self.assertEqual(sc.unique_name("", "a/b", used, w), "a_b")
        self.assertEqual(len(w), 2)


def image(name, x, y, w, h, parent="", visible=True, **kw):
    return {"name": name, "parent": parent, "type": "image", "visible": visible, "x": x, "y": y, "w": w, "h": h, **kw}


class Nesting(unittest.TestCase):
    FRAME = (1080, 1920)

    def test_smallest_container_wins(self):
        nodes = [image("Panel", 100, 100, 800, 800), image("Card", 200, 200, 300, 300), image("Icon", 250, 250, 50, 50)]
        sc.nest_contained(nodes, self.FRAME)
        self.assertEqual([sc.path_of(n) for n in nodes], ["Panel", "Panel/Card", "Panel/Card/Icon"])

    def test_blocked_by_overlap_in_between(self):
        nodes = [image("Panel", 100, 100, 800, 800), image("Wide", 0, 240, 1080, 40), image("Icon", 250, 250, 50, 50)]
        nested, blocked = sc.nest_contained(nodes, self.FRAME)
        self.assertEqual(sc.path_of(nodes[2]), "Icon")
        self.assertTrue(any("Wide" in b for b in blocked))

    def test_label_on_button_even_without_nest(self):
        txt = {"name": "Label", "parent": "", "type": "text", "visible": True, "x": 420, "y": 1310, "w": 240, "h": 80}
        nodes = [image("PlayButton", 400, 1300, 280, 100, button=True), txt]
        sc.nest_contained(nodes, self.FRAME, nest=False)
        self.assertEqual(sc.path_of(txt), "PlayButton/Label")

    def test_full_frame_background_is_not_a_container(self):
        nodes = [image("Bg", 0, 0, 1080, 1920), image("Icon", 10, 10, 50, 50)]
        sc.nest_contained(nodes, self.FRAME)
        self.assertEqual(sc.path_of(nodes[1]), "Icon")


class Variants(unittest.TestCase):
    def test_icon_and_title_swap(self):
        nodes = [image("HintIcon", 100, 100, 80, 80), image("UndoIcon", 100, 100, 80, 80, visible=False),
                 {"name": "HintText", "parent": "", "type": "text", "visible": True, "text": "Hint", "x": 100, "y": 300, "w": 120, "h": 50},
                 {"name": "UndoText", "parent": "", "type": "text", "visible": False, "text": "Undo", "x": 100, "y": 300, "w": 130, "h": 50}]
        v = sc.find_variants(nodes)
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["name"], "undo")
        self.assertEqual(sorted(v[0]["show"]), ["UndoIcon", "UndoText"])
        self.assertEqual(sorted(v[0]["hide"]), ["HintIcon", "HintText"])


class Slice(unittest.TestCase):
    def test_wider_button_is_the_same_sprite_sliced(self):
        src, dst = button(60).astype(np.float32), button(200).astype(np.float32)
        r = match_sprites.slice_fit(src, dst)
        self.assertIsNotNone(r)
        l, b, rr, t = r["slice"]
        self.assertTrue(l >= 6 and rr >= 6 and b == 0 and t == 0, r["slice"])
        self.assertEqual(r["size"], [200, 40])
        self.assertLessEqual(r["diff"], match_sprites.SLICE_ART)

    def test_different_art_does_not_match(self):
        other = button(200)
        other[..., :3] = (20, 120, 250)
        self.assertIsNone(match_sprites.slice_fit(button(60).astype(np.float32), other.astype(np.float32)))

    def test_padding_is_trimmed(self):
        padded = np.zeros((60, 240, 4), np.uint8)
        padded[10:50, 20:220] = button(200)
        r = match_sprites.slice_fit(button(60).astype(np.float32), padded.astype(np.float32))
        self.assertIsNotNone(r)
        self.assertEqual(r["offset"], [20, 10])


class Gradient(unittest.TestCase):
    def test_vertical_overlay_corners(self):
        fx = {"gradient": {"noise": False, "colors": [[0, 255, 0, 0, "UsrS"], [1, 0, 0, 255, "UsrS"]],
                           "alphas": [[0, 1], [1, 1]]}, "angle": 90, "scale": 100, "opacity": 100}
        w = []
        corners, color = sc.ps_gradient_overlay(fx, 100, 50, [255, 255, 255, 200], "t", w)
        tl, bl = corners[0:4], corners[8:12]
        self.assertEqual(tl, [0, 0, 255, 255])    # angle 90: the end color is at the top
        self.assertEqual(bl, [255, 0, 0, 255])
        self.assertEqual(color, [255, 255, 255, 200])

    def test_noise_gradient_is_skipped(self):
        w = []
        self.assertIsNone(sc.ps_gradient_overlay({"gradient": {"noise": True, "colors": [1]}}, 10, 10, [0, 0, 0, 255], "t", w))
        self.assertTrue(w)


class Planner(unittest.TestCase):
    def test_same_art_twice_and_sliced_reuse_in_one_build(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Assets", "_Project", "Images", "UI", "Common"))
            a = img(os.path.join(d, "a.png"), button(60))
            a2 = img(os.path.join(d, "a2.png"), button(60))
            wide = img(os.path.join(d, "wide.png"), button(200))
            p = sc.SpritePlanner(d, "TestUI", [a, a2, wide])
            pa, _, _ = p.sprite_for(a, "OkButton")
            pa2, _, _ = p.sprite_for(a2, "OkButton copy")
            pw, off, size = p.sprite_for(wide, "WideButton")
            self.assertEqual(pa, "Assets/_Project/Images/UI/TestUI/OkButton.png")
            self.assertEqual(pa2, pa)
            self.assertEqual(pw, pa)
            self.assertEqual(tuple(size), (200, 40))
            self.assertIn(pa, p.borders)
            self.assertEqual(len(p.new_sprites), 1)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
