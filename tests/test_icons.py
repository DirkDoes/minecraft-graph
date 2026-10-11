import json
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from render_icons import SIZE, apply_transform, definition_transform, raster_triangle, rotation
from render_blocks import matches, select_models


class IconTests(unittest.TestCase):
    def test_blockstate_selection_and_correct_block_artwork(self):
        state = {"north": "false", "age": "0"}
        self.assertTrue(matches({"OR": [{"north": "true"}, {"age": "0|1"}]}, state))
        self.assertFalse(matches({"AND": [{"north": "true"}, {"age": "0"}]}, state))
        self.assertEqual(select_models({"variants": {"age=0": [{"model": "fresh"}, {"model": "alternative"}], "age=1": {"model": "old"}}}, state), [{"model": "fresh"}])
        report = json.loads((ROOT / "assets/blocks/coverage.json").read_text(encoding="utf-8"))
        graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        self.assertEqual(set(report["blocks"]), {n["blockId"] for n in graph["nodes"] if n["kind"] == "block"})
        for slug in ("fire", "soul_fire", "nether_portal", "frosted_ice", "end_portal", "end_gateway", "piston_head"):
            node = next(n for n in graph["nodes"] if n["id"] == "block:minecraft:" + slug)
            self.assertEqual(node["icon"], f"assets/blocks/{slug}.png")
            image = Image.open(ROOT / node["icon"])
            self.assertEqual(image.size, (SIZE, SIZE))
            self.assertIsNotNone(image.getbbox())
        textures = set(report["sourceTextures"])
        for texture in ("fire_0", "soul_fire_0", "nether_portal", "frosted_ice_0"):
            self.assertIn(f"assets/minecraft/textures/block/{texture}.png", textures)
        self.assertIn("assets/minecraft/textures/entity/end_portal/end_portal.png", textures)

    def test_mob_camera_faces_front(self):
        camera = rotation([8, 152, 0]) @ np.diag([1, -1, 1])
        self.assertGreater((camera @ np.array([0, 0, -1]))[2], 0)
        coverage = json.loads((ROOT / "assets/mobs/coverage.json").read_text(encoding="utf-8"))
        self.assertTrue(all(icon["viewRotation"] == [8, 152, 0] for icon in coverage["icons"].values()))

    def test_game_gui_rotation_exposes_top_face(self):
        normal = rotation([30, 225, 0]) @ np.array([0, 1, 0])
        self.assertGreater(normal[2], 0)
        matrix = definition_transform({"scale": [1, -1, -1], "translation": [0.5, 1.5, 0.5]})
        np.testing.assert_allclose(apply_transform(np.array([[0, 16, 0]]), matrix), [[8, 8, 8]])

    def test_nearest_sampling_and_straight_alpha(self):
        output = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
        depth = np.full((SIZE, SIZE), -np.inf)
        texture = np.array([[[255, 0, 0, 128], [0, 255, 0, 255]]], dtype=np.uint8)
        points = np.array([[0, 0, 1], [64, 0, 1], [0, 64, 1]])
        uv = np.array([[0, 0], [1, 0], [0, 1]])
        raster_triangle(output, depth, points, uv, texture, np.ones(3))
        self.assertEqual(output[1, 1].tolist(), [255, 0, 0, 128])
        self.assertEqual(output[1, 40].tolist(), [0, 255, 0, 255])
        self.assertEqual(output[63, 63].tolist(), [0, 0, 0, 0])
        raster_triangle(output, depth, points- [0, 0, 2], uv, texture, np.zeros(3))
        self.assertEqual(output[1, 1].tolist(), [255, 0, 0, 128])

    def test_every_registered_item_has_a_valid_icon(self):
        report = json.loads((ROOT / "assets/icon-coverage.json").read_text(encoding="utf-8"))
        self.assertEqual(report["registeredItems"], report["iconsWritten"])
        self.assertEqual(report["missingIcons"], [])
        for item in report["items"]:
            with self.subTest(item=item):
                image = Image.open(ROOT / "assets/icons" / (item.split(":")[1] + ".png"))
                self.assertEqual(image.size, (SIZE, SIZE))
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.getbbox() is None, item == "minecraft:air")


if __name__ == "__main__":
    unittest.main()
