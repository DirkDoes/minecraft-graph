"""Check registry coverage, meaningful directions and conditional interaction rules."""
import json
import unittest
import zipfile

from extract_data import CACHE, ROOT, GameData
from interaction_relations import build_interactions


class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        cls.jar = zipfile.ZipFile(CACHE / "client.jar")
        cls.game = GameData(cls.jar, CACHE / "generated/reports")
        cls.part = build_interactions(cls.game, "26.3", cls.graph["nodes"])
        cls.records = {record["id"]: record for record in cls.part["relationships"]}
        cls.directions = {(edge["source"], edge["target"], edge["type"]) for edge in cls.part["edges"]}
        cls.metadata = json.loads((CACHE / "interaction-metadata.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_references_and_no_universal_spawner_claim(self):
        ids = {node["id"] for node in self.graph["nodes"]}
        self.assertEqual(self.part["nodes"], [])
        self.assertEqual(len(self.records), len(self.part["relationships"]))
        self.assertEqual(len({edge["id"] for edge in self.part["edges"]}), len(self.part["edges"]))
        for edge in self.part["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)
            self.assertEqual(edge["minVersion"], "26.3")
            self.assertIsNone(edge["maxVersion"])
            record = self.records[edge["relationId"]]
            self.assertIn(edge["source"], {node["nodeId"] for node in record["inputs"]})
            self.assertIn(edge["target"], {node["nodeId"] for node in record["outputs"]})
        self.assertFalse(any(edge["source"] in ["minecraft:spawner", "minecraft:trial_spawner"] and edge["target"].startswith("mob:") for edge in self.part["edges"]))
        with self.assertRaises(ValueError):
            build_interactions(self.game, "26.4", self.graph["nodes"])
        with self.assertRaisesRegex(ValueError, "Unknown interaction endpoint"):
            build_interactions(self.game, "26.3", [])

    def test_all_default_spawn_eggs_and_buckets(self):
        egg_edges = {(source, target.removeprefix("mob:")) for source, target, kind in self.directions if kind == "spawn_egg"}
        self.assertEqual(egg_edges, set(self.metadata["spawnEggs"].items()))
        for source, target in egg_edges:
            self.assertEqual(target, self.game.components[source]["minecraft:entity_data"]["id"])
        bucket_edges = {(source, target.removeprefix("mob:")) for source, target, kind in self.directions if kind == "bucket_release"}
        self.assertEqual(bucket_edges, set(self.metadata["mobBuckets"].items()))
        self.assertIn(("minecraft:sulfur_cube_bucket", "minecraft:sulfur_cube"), bucket_edges)
        self.assertIn(("minecraft:ender_pearl", "mob:minecraft:endermite", "ender_pearl_spawn"), self.directions)
        self.assertNotIn(("minecraft:ender_pearl", "mob:minecraft:enderman", "ender_pearl_spawn"), self.directions)
        pearl = self.records["interaction:ender_pearl_spawn"]
        self.assertEqual(pearl["chance"], .05)
        self.assertTrue(any("Peaceful" in condition for condition in pearl["conditions"]))
        eggs = [record for record in self.records.values() if record["type"] == "egg_hatching"]
        self.assertEqual(len(eggs), 3)
        self.assertTrue(all(record["hatchChance"] == .125 and record["fourChicksConditionalChance"] == 1/32 for record in eggs))

    def test_building_and_egg_stages(self):
        wither = self.records["interaction:mob_building:wither"]
        self.assertEqual(wither["ingredients"][0], {"items": ["minecraft:soul_sand", "minecraft:soul_soil"], "count": 4})
        self.assertEqual(wither["ingredients"][1]["count"], 3)
        iron = self.records["interaction:mob_building:iron_golem"]
        self.assertEqual(iron["ingredients"][0]["count"], 4)
        self.assertEqual(set(iron["ingredients"][1]["items"]), {"minecraft:carved_pumpkin", "minecraft:jack_o_lantern"})
        self.assertNotIn("minecraft:pumpkin", {node["nodeId"] for node in iron["inputs"]})
        copper = self.records["interaction:mob_building:copper_golem"]
        self.assertEqual(set(copper["ingredients"][0]["items"]), set(self.game.resolve_tag("minecraft:copper")))
        for source, target in [("turtle_egg", "turtle"), ("sniffer_egg", "sniffer"), ("frogspawn", "tadpole")]:
            self.assertIn(("minecraft:" + source, "mob:minecraft:" + target, "block_hatching"), self.directions)
        self.assertEqual(self.records["interaction:mob_splitting:sulfur_cube"]["count"], 2)
        self.assertIn("unprimed", self.records["interaction:mob_splitting:sulfur_cube"]["note"])
        dried_ghast = self.records["interaction:dried_ghast_hydrating"]
        self.assertEqual(dried_ghast["hydrationTickDelay"], 5000)
        self.assertEqual(dried_ghast["requiredBlockState"], {"block": "minecraft:dried_ghast", "waterlogged": True})
        self.assertIn(("minecraft:dried_ghast", "mob:minecraft:happy_ghast", "hydration_spawning"), self.directions)
        chest_records = [record for record in self.records.values() if record["type"] == "construction_side_product"]
        self.assertEqual(len(chest_records), 8)
        for copper_id, chest_id in self.metadata["copperConstructionChests"].items():
            self.assertIn((copper_id, chest_id, "construction_side_product"), self.directions)
        self.assertFalse(any(record["type"] in {"mob_waxing", "mob_scraping", "statue_conversion", "statue_awakening"} for record in self.records.values()))

    def test_sculk_shrieker_warden_requires_natural_summoning_state_and_warning(self):
        self.assertIn(("minecraft:sculk_shrieker", "mob:minecraft:warden", "mob_summoning"), self.directions)
        record = self.records["interaction:sculk_shrieker_warden"]
        self.assertEqual(record["category"], "spawning")
        self.assertEqual(record["requiredBlockState"], {"block": "minecraft:sculk_shrieker", "can_summon": True})
        self.assertEqual(record["warningLevelRequired"], 4)
        self.assertEqual(record["warningIncreaseCooldownTicks"], 200)
        self.assertEqual(record["nearbyWardenCheckCube"], [48, 48, 48])
        self.assertEqual((record["spawnAttempts"], record["spawnRangeXZ"], record["spawnRangeY"]), (20, 5, 6))
        self.assertTrue(any("spawn_wardens=true" in condition for condition in record["conditions"]))
        self.assertTrue(any("Peaceful" in condition for condition in record["conditions"]))
        self.assertTrue(any("no liquid" in condition for condition in record["conditions"]))
        self.assertIn("player-placed shriekers have can_summon=false", record["note"])
        self.assertEqual({edge["source"] for edge in self.part["edges"] if edge["relationId"] == record["id"]}, {"minecraft:sculk_shrieker"})

    def test_tools_food_and_state_changes(self):
        for source, target, kind in [("minecraft:shears", "mob:minecraft:sheep", "shearing_tool"), ("minecraft:shears", "minecraft:beehive", "harvesting_tool"),
                                     ("minecraft:glass_bottle", "minecraft:beehive", "harvesting_tool"), ("minecraft:campfire", "minecraft:beehive", "smoking_bees"),
                                     ("minecraft:iron_shovel", "minecraft:campfire", "extinguishing"), ("minecraft:hay_block", "minecraft:campfire", "campfire_smoke"),
                                     ("minecraft:red_dye", "mob:minecraft:sheep", "dyeing"), ("minecraft:wheat", "mob:minecraft:sheep", "breeding"),
                                     ("minecraft:wheat_seeds", "mob:minecraft:chicken", "breeding"), ("tag:minecraft:chicken_food", "mob:minecraft:chicken", "feeding"),
                                     ("minecraft:saddle", "mob:minecraft:pig", "equipping"), ("minecraft:red_harness", "mob:minecraft:happy_ghast", "equipping"),
                                     ("minecraft:water_bucket", "block:minecraft:water", "placing"), ("minecraft:flint_and_steel", "block:minecraft:fire", "igniting"),
                                     ("minecraft:soul_soil", "block:minecraft:soul_fire", "igniting"), ("minecraft:obsidian", "block:minecraft:nether_portal", "portal_igniting")]:
            self.assertIn((source, target, kind), self.directions)
        self.assertNotIn(("minecraft:iron_helmet", "mob:minecraft:skeleton", "equipping"), self.directions)
        self.assertNotIn(("minecraft:wheat", "mob:minecraft:llama", "breeding"), self.directions)
        self.assertNotIn(("minecraft:red_mushroom", "mob:minecraft:zombie_horse", "breeding"), self.directions)
        self.assertEqual(self.records["interaction:healing:wolf:rotten_flesh"]["healing"], 8)
        self.assertEqual(self.records["interaction:healing:cat:cod"]["healing"], 2)
        self.assertEqual(self.records["interaction:healing:nautilus:cod_bucket"]["healing"], 4)
        self.assertIn(("minecraft:leather_helmet", "minecraft:leather_helmet", "washing"), self.directions)
        self.assertEqual(self.records["interaction:washing_dye:minecraft:leather_helmet"]["requiredBlockState"]["block"], "minecraft:water_cauldron")

    def test_complete_component_and_transformer_inventories_without_repetition(self):
        fuels = {item for item, components in self.game.components.items() if "minecraft:cooking_fuel" in components}
        fuel_records = [record for record in self.records.values() if record["type"] == "cooking_fuel"]
        self.assertEqual({record["inputs"][0]["nodeId"] for record in fuel_records}, fuels)
        self.assertEqual(len(fuel_records), len(fuels))
        self.assertTrue(all(len(record["outputs"]) == 3 for record in fuel_records))
        expected_transformers = {components["minecraft:block_transformer"] for components in self.game.components.values() if "minecraft:block_transformer" in components}
        self.assertEqual(set(self.part["coverage"]["blockTransformers"]), expected_transformers)
        expected_rules = sum(len(section["block_state_provider"]["rules"]) for identifier in expected_transformers for section in json.loads(self.jar.read("data/" + identifier.replace(":", "/block_transformer/") + ".json")))
        self.assertEqual(self.part["coverage"]["transformRules"], expected_rules)
        mining = [record for record in self.records.values() if record["type"] == "mining_tool"]
        self.assertLess(len(mining), 100)
        for tool, expected in [("wooden_pickaxe", False), ("golden_pickaxe", False), ("iron_pickaxe", True)]:
            matching = [record for record in mining if record["inputs"][0]["nodeId"] == "minecraft:" + tool and "minecraft:diamond_ore" in record["blockIds"]]
            self.assertEqual(len(matching), 1)
            self.assertIs(matching[0]["correctForDrops"], expected)
        self.assertEqual(self.part["coverage"]["itemCapabilities"]["minecraft:iron_helmet"]["equippable"]["slot"], "head")
        self.assertEqual(self.part["coverage"]["itemCapabilities"]["minecraft:wheat_seeds"]["placeable"]["blockId"], "minecraft:wheat")

    def test_water_potion_and_frost_walker_predicates(self):
        for item in ["minecraft:splash_potion", "minecraft:lingering_potion"]:
            water = self.records["interaction:water_harming:" + item]
            self.assertEqual({node["nodeId"] for node in water["outputs"]}, {"mob:minecraft:" + entity for entity in ["blaze", "enderman", "snow_golem", "strider"]})
            self.assertEqual(water["requiredComponents"], {"minecraft:potion_contents": {"potion": "minecraft:water"}})
        walker = self.records["interaction:frost_walking"]
        self.assertEqual(walker["requiredEnchantments"], {"minecraft:frost_walker": {"min": 1}})
        self.assertEqual(walker["raw"], json.loads(self.jar.read("data/minecraft/enchantment/frost_walker.json")))
        self.assertIn(("block:minecraft:frosted_ice", "block:minecraft:water", "melting"), self.directions)
        self.assertNotIn(("minecraft:packed_ice", "block:minecraft:water", "melting"), self.directions)


if __name__ == "__main__":
    unittest.main()
