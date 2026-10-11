import json
import unittest
import zipfile

from extract_data import CACHE, ROOT, GameData
from plant_relations import build_plants


class PlantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        cls.jar = zipfile.ZipFile(CACHE / "client.jar")
        cls.game = GameData(cls.jar, CACHE / "generated/reports")
        cls.part = build_plants(cls.game, cls.graph["version"], cls.graph["nodes"])

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_all_registered_fertilizing_types_and_conditional_crops(self):
        metadata = json.loads((CACHE / "plant-metadata.json").read_text(encoding="utf-8"))
        targets = {r["targetBlock"] for r in self.part["relationships"] if r["type"] == "fertilizing"}
        self.assertEqual(targets, set(metadata["bonemealable"]))
        directions = {(e["source"], e["target"], e["type"]) for e in self.part["edges"]}
        for source, target in [("wheat_seeds", "wheat"), ("melon_seeds", "melon"), ("pumpkin_seeds", "pumpkin"), ("torchflower_seeds", "torchflower"), ("pitcher_pod", "pitcher_plant"), ("potato", "poisonous_potato")]:
            self.assertIn(("minecraft:" + source, "minecraft:" + target, "crop_growing"), directions)
        crops = [r for r in self.part["relationships"] if r["type"] == "crop_growing" and "loot" in r]
        self.assertTrue(any(r["loot"]["conditions"] for r in crops))

    def test_graph_references_and_npc_conditions(self):
        ids = {node["id"] for node in self.graph["nodes"]}
        self.assertEqual(len({r["id"] for r in self.part["relationships"]}), len(self.part["relationships"]))
        self.assertEqual(len({e["id"] for e in self.part["edges"]}), len(self.part["edges"]))
        for edge in self.part["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)
        jobs = [r for r in self.part["relationships"] if r["type"] == "villager_workstation"]
        self.assertEqual(len(jobs), 13)
        doors = [r for r in self.part["relationships"] if r["type"] == "door_breaking"]
        self.assertTrue(doors)
        self.assertTrue(all("Hard difficulty" in r["conditions"] for r in doors))
        self.assertEqual({r["inputs"][0]["nodeId"] for r in doors}, {"mob:minecraft:" + slug for slug in ("zombie", "husk", "zombie_villager", "drowned", "zombified_piglin")})
        planting = [r for r in self.part["relationships"] if r["type"] == "villager_planting"]
        self.assertEqual({r["outputs"][0]["nodeId"] for r in planting}, set(self.game.resolve_tag("minecraft:villager_plantable_seeds")))
        with self.assertRaises(ValueError):
            build_plants(self.game, "future", self.graph["nodes"])


if __name__ == "__main__":
    unittest.main()
