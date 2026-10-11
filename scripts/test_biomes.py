import json
import unittest
import zipfile

from extract_data import CACHE, ROOT, GameData
from biome_relations import FeatureOutputs, biome_feature_structures, build_biomes, material_outputs, registry


class BiomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        cls.jar = zipfile.ZipFile(CACHE / "client.jar")
        cls.game = GameData(cls.jar, CACHE / "generated/reports")
        cls.part = build_biomes(cls.game, "26.3", cls.graph["nodes"])
        cls.links = {(e["source"], e["target"], e["type"]) for e in cls.part["edges"]}

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_complete_registry_and_dimension_memberships(self):
        metadata = json.loads((CACHE / "biome-metadata.json").read_text(encoding="utf-8"))
        biome_nodes = {n["biomeId"] for n in self.part["nodes"] if n["kind"] == "biome"}
        self.assertEqual(biome_nodes, set(metadata["biomes"]))
        self.assertEqual(len(biome_nodes), 67)
        self.assertEqual(len([n for n in self.part["nodes"] if n["kind"] == "dimension"]), 3)
        for biome in metadata["presets"]["minecraft:nether"]:
            self.assertIn(("biome:" + biome, "dimension:minecraft:the_nether", "biome_dimension"), self.links)
        for biome in metadata["endBiomes"]:
            self.assertIn(("biome:" + biome, "dimension:minecraft:the_end", "biome_dimension"), self.links)
        self.assertIn(("biome:minecraft:the_void", "dimension:minecraft:overworld", "biome_dimension"), self.links)
        self.assertFalse(any(e["type"] == "biome_block" and e["source"] == "biome:minecraft:the_void" for e in self.part["edges"]))

    def test_structure_contents_remain_secondary(self):
        for biome, block in [("desert", "cut_sandstone"), ("desert", "chiseled_sandstone"), ("desert", "sandstone_slab"), ("desert", "suspicious_sand"),
                             ("plains", "calcite"), ("plains", "budding_amethyst"), ("plains", "chest"), ("plains", "spawner"),
                             ("end_highlands", "purpur_block"), ("end_highlands", "end_stone_bricks"), ("the_end", "iron_bars")]:
            self.assertNotIn(("biome:minecraft:" + biome, "minecraft:" + block, "biome_block"), self.links)
        self.assertIn(("biome:minecraft:stony_peaks", "minecraft:calcite", "biome_block"), self.links)
        self.assertIn(("biome:minecraft:desert", "minecraft:sandstone", "biome_block"), self.links)
        mapping = biome_feature_structures(self.game)
        self.assertEqual(mapping["minecraft:desert_well"], {"minecraft:desert"})
        self.assertEqual(mapping["minecraft:amethyst_geode"], set(self.part["coverage"]["dimensionBiomes"]["minecraft:overworld"]))

    def test_predicates_do_not_become_outputs_and_procedural_debug_blocks_do_not_leak(self):
        features = FeatureOutputs(self.game)
        self.assertEqual(features.placed("minecraft:ore_coal_upper"), {"minecraft:coal_ore", "minecraft:deepslate_coal_ore"})
        self.assertEqual(features.placed("minecraft:glow_lichen"), {"minecraft:glow_lichen"})
        self.assertEqual(features.placed("minecraft:large_dripstone"), {"minecraft:dripstone_block"})
        self.assertNotIn(("biome:minecraft:dripstone_caves", "minecraft:diamond_block", "biome_block"), self.links)
        self.assertNotIn(("biome:minecraft:dripstone_caves", "minecraft:creeper_head", "biome_block"), self.links)
        self.assertEqual(features.placed("minecraft:blue_ice"), {"minecraft:blue_ice"})
        self.assertNotIn("minecraft:mycelium", material_outputs(self.game, "minecraft:overworld", "minecraft:plains"))
        self.assertIn("minecraft:mycelium", material_outputs(self.game, "minecraft:overworld", "minecraft:mushroom_fields"))
        for biome in ("badlands", "eroded_badlands", "frozen_peaks", "grove", "ice_spikes", "jagged_peaks", "snowy_slopes"):
            self.assertNotIn(("biome:minecraft:" + biome, "minecraft:grass_block", "biome_block"), self.links)
        for biome in ("plains", "forest", "wooded_badlands"):
            self.assertIn(("biome:minecraft:" + biome, "minecraft:grass_block", "biome_block"), self.links)
        self.assertIn("minecraft:water", features.placed("minecraft:clay_pool_with_dripleaves"))
        self.assertIn("minecraft:end_stone", features.feature("minecraft:end_podium_active"))
        self.assertIn("minecraft:wall_torch", features.feature("minecraft:end_podium_active"))
        with self.assertRaises(ValueError):
            features.provider({"type": "minecraft:unknown_provider"})

    def test_natural_spawn_entries_preserve_the_entire_registry(self):
        records = {r["id"]: r for r in self.part["relationships"] if r["type"] == "biome_spawn"}
        expected = 0
        for biome, definition in registry(self.game, "biome").items():
            attribute = definition["attributes"]["minecraft:gameplay/natural_mob_spawns"]["argument"]
            for category, entries in attribute["spawns_by_category"].items():
                for index, entry in enumerate(entries):
                    expected += 1
                    record = records["worldgen:spawn/" + biome.split(":")[1] + "/" + category + "/" + entry["type"].split(":")[1] + "/" + str(index)]
                    self.assertEqual(record["spawnWeight"], entry["weight"])
                    self.assertEqual(record["spawnCount"], entry["count"])
                    self.assertEqual(record["spawnCost"], attribute["spawn_costs"].get(entry["type"]))
        self.assertEqual(len(records), expected)
        self.assertFalse(any(e["source"] == "biome:minecraft:deep_dark" and e["type"] == "biome_spawn" for e in self.part["edges"]))
        self.assertIn(("biome:minecraft:desert", "mob:minecraft:husk", "biome_spawn"), self.links)

    def test_references_icons_and_version_guards(self):
        ids = {n["id"] for n in self.graph["nodes"]} | {n["id"] for n in self.part["nodes"]}
        self.assertEqual(len({r["id"] for r in self.part["relationships"]}), len(self.part["relationships"]))
        self.assertEqual(len({e["id"] for e in self.part["edges"]}), len(self.part["edges"]))
        for edge in self.part["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)
            self.assertEqual(edge["minVersion"], "26.3")
            self.assertIsNone(edge["maxVersion"])
        for node in self.part["nodes"]:
            self.assertTrue((ROOT / node["icon"]).is_file())
        with self.assertRaises(ValueError):
            build_biomes(self.game, "future", self.graph["nodes"])


if __name__ == "__main__":
    unittest.main()
