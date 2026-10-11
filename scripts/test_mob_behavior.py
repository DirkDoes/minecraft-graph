import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from extract_data import CACHE, ROOT, GameData
from mob_behavior_relations import build_mob_behaviors


class MobBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        cls.jar = zipfile.ZipFile(CACHE / "client.jar")
        cls.game = GameData(cls.jar, CACHE / "generated/reports")
        cls.part = build_mob_behaviors(cls.game, cls.graph["version"], cls.graph["nodes"])
        cls.records = {record["id"]: record for record in cls.part["relationships"]}
        cls.directions = {(edge["source"], edge["target"], edge["type"]) for edge in cls.part["edges"]}

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def record(self, key):
        return self.records["interaction:behavior/" + key]

    def test_existing_endpoints_bounds_and_unique_references(self):
        ids = {node["id"] for node in self.graph["nodes"]}
        self.assertEqual(self.part["nodes"], [])
        self.assertEqual(len(self.records), len(self.part["relationships"]))
        self.assertEqual(len({edge["id"] for edge in self.part["edges"]}), len(self.part["edges"]))
        for edge in self.part["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)
            self.assertIn(edge["relationId"], self.records)
        for record in self.part["relationships"]:
            self.assertEqual(record["minVersion"], "26.3")
            self.assertIsNone(record["maxVersion"])
            self.assertTrue(record["conditions"])
            self.assertTrue(record["sourceClass"])
        self.assertEqual(self.part["coverage"]["omittedUnrepresentedBlocks"], [])

    def test_real_conversion_chains_require_their_triggers(self):
        for source, target in (("husk", "zombie"), ("zombie", "drowned"), ("piglin", "zombified_piglin"),
                               ("piglin_brute", "zombified_piglin"), ("hoglin", "zoglin"), ("tadpole", "frog")):
            self.assertIn(("mob:minecraft:" + source, "mob:minecraft:" + target, "mob_conversion"), self.directions)
        self.assertNotIn(("mob:minecraft:husk", "mob:minecraft:drowned", "mob_conversion"), self.directions)
        self.assertNotIn(("mob:minecraft:drowned", "mob:minecraft:zombie", "mob_conversion"), self.directions)
        self.assertIn(("block:minecraft:water", "mob:minecraft:drowned", "mob_conversion"), self.directions)
        freezing = self.record("freezing/skeleton")
        self.assertEqual((freezing["exposureTicks"], freezing["conversionTicks"]), (140, 300))
        self.assertIn(("minecraft:powder_snow_bucket", "mob:minecraft:stray", "mob_conversion"), self.directions)
        self.assertNotIn(("mob:minecraft:bogged", "mob:minecraft:stray", "mob_conversion"), self.directions)
        lightning = self.record("lightning/villager")
        self.assertEqual(lightning["trigger"], "lightning")
        self.assertIn("Difficulty is not Peaceful", lightning["conditions"])

    def test_infection_requires_killing_blow_and_difficulty(self):
        records = [record for record in self.records.values() if record["type"] == "infection"]
        self.assertEqual({record["inputs"][0]["nodeId"] for record in records},
                         {"mob:minecraft:" + name for name in ("zombie", "husk", "zombie_villager", "drowned", "zombified_piglin")})
        for record in records:
            self.assertEqual(record["probabilityByDifficulty"], {"easy": 0, "normal": .5, "hard": 1, "peaceful": 0})
            self.assertIn("Killing blow on a Villager", record["conditions"])
            self.assertEqual(record["outputs"], [{"nodeId": "mob:minecraft:zombie_villager"}])
        shearing = self.record("shearing/mooshroom")
        self.assertEqual({part["nodeId"] for part in shearing["inputs"]}, {"mob:minecraft:mooshroom", "minecraft:shears"})
        self.assertEqual(shearing["outputs"], [{"nodeId": "mob:minecraft:cow"}])

    def test_frog_loot_retains_variants_and_actor(self):
        records = [record for record in self.records.values() if record["type"] == "predation_drop"]
        self.assertEqual(len(records), 4)
        variants = {record["frogVariant"]: record["outputs"][0]["nodeId"] for record in records if "frogVariant" in record}
        self.assertEqual(variants, {"minecraft:warm": "minecraft:pearlescent_froglight", "minecraft:cold": "minecraft:verdant_froglight", "minecraft:temperate": "minecraft:ochre_froglight"})
        for record in records:
            self.assertEqual(record["quantity"], 1)
            self.assertEqual(record["preySize"], 1)
            self.assertIn("mob:minecraft:frog", {part["nodeId"] for part in record["inputs"]})
            self.assertTrue(record["loot"]["conditions"])
            self.assertEqual(record["loot"]["rawEntry"]["condition"]["type"], "minecraft:damage_source_properties")
        self.assertIn(("mob:minecraft:frog", "minecraft:slime_ball", "predation_drop"), self.directions)
        self.assertNotIn(("mob:minecraft:frog", "minecraft:magma_cream", "predation_drop"), self.directions)

    def test_tag_target_inventory_and_specific_hunting_exceptions(self):
        for tag_name in ("axolotl_hunt_targets", "axolotl_always_hostiles"):
            raw = json.loads(self.jar.read("data/minecraft/tags/entity_type/" + tag_name + ".json"))
            records = [record for record in self.records.values() if record.get("entityTypeTag") == "minecraft:" + tag_name]
            self.assertEqual({record["outputs"][0]["nodeId"] for record in records}, {"mob:" + value for value in raw["values"]})
            self.assertTrue(all(record["maximumRange"] == 8 for record in records))
        self.assertIn(("mob:minecraft:cat", "mob:minecraft:rabbit", "hunting"), self.directions)
        self.assertNotIn(("mob:minecraft:cat", "mob:minecraft:chicken", "hunting"), self.directions)
        self.assertNotIn(("mob:minecraft:fox", "mob:minecraft:pufferfish", "hunting"), self.directions)
        turtle = self.record("hunting/wolf/baby_turtle")
        self.assertIn("Baby Turtle", turtle["conditions"])
        self.assertIn("Turtle on land", turtle["conditions"])

    def test_repelling_and_pollination_require_correct_block_states(self):
        self.assertIn(("mob:minecraft:cat", "mob:minecraft:phantom", "repelling"), self.directions)
        self.assertNotIn(("mob:minecraft:ocelot", "mob:minecraft:phantom", "repelling"), self.directions)
        campfire = self.record("repellent_block/piglin/minecraft:soul_campfire")
        self.assertIn("Soul Campfire must be lit", campfire["conditions"])
        for tag_name in ("hoglin_repellents", "piglin_repellents", "bee_attractive"):
            raw = json.loads(self.jar.read("data/minecraft/tags/block/" + tag_name + ".json"))
            records = [record for record in self.records.values() if record.get("blockTag") == "minecraft:" + tag_name]
            self.assertEqual({record["targetBlock"] for record in records}, set(raw["values"]))
        sunflower = self.record("pollination/minecraft:sunflower")
        self.assertIn("Upper Sunflower half", sunflower["conditions"])
        grown = {record["targetBlock"] for record in self.records.values() if record["type"] == "crop_pollination"}
        self.assertIn("minecraft:torchflower_crop", grown)
        self.assertNotIn("minecraft:pitcher_crop", grown)

    def test_temptation_does_not_inherit_overridden_horse_goals(self):
        self.assertIn(("minecraft:golden_carrot", "mob:minecraft:horse", "attraction"), self.directions)
        self.assertNotIn(("minecraft:golden_carrot", "mob:minecraft:skeleton_horse", "attraction"), self.directions)
        self.assertNotIn(("minecraft:golden_carrot", "mob:minecraft:zombie_horse", "attraction"), self.directions)
        for item in self.game.resolve_tag("minecraft:zombie_horse_food"):
            self.assertIn((item, "mob:minecraft:zombie_horse", "attraction"), self.directions)
        harness = self.record("tempt/happy_ghast_tempt_items/minecraft:white_harness/happy_ghast")
        self.assertIn("Adult Happy Ghast without body armor for harness temptation", harness["conditions"])

    def test_copper_golem_waxing_scraping_and_statue_activation(self):
        statue = self.record("copper_golem/statue")
        self.assertEqual(statue["outputs"], [{"nodeId": "minecraft:oxidized_copper_golem_statue"}])
        self.assertEqual(statue["chancePerCheck"], .0058)
        self.assertIn(("minecraft:honeycomb", "mob:minecraft:copper_golem", "mob_waxing"), self.directions)
        for axe in self.game.resolve_tag("minecraft:axes"):
            for kind in ("mob_scraping", "mob_unwaxing", "statue_activation"):
                self.assertIn((axe, "mob:minecraft:copper_golem", kind), self.directions)
        activation = [record for record in self.records.values() if record["type"] == "statue_activation"]
        self.assertTrue(all("Unaffected oxidation stage" in record["conditions"] for record in activation))
        self.assertTrue(all("minecraft:copper_golem_statue" in {part["nodeId"] for part in record["inputs"]} for record in activation))
        self.assertFalse(any("minecraft:waxed_copper_golem_statue" in {part["nodeId"] for part in record["inputs"]} for record in activation))

    def test_new_version_or_changed_client_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "version audit"):
            build_mob_behaviors(self.game, "26.4", self.graph["nodes"])
        with tempfile.TemporaryDirectory(dir=CACHE) as directory:
            path = Path(directory) / "client.jar"
            path.write_bytes(b"Different client")
            game = SimpleNamespace(jar=SimpleNamespace(filename=str(path)))
            with self.assertRaisesRegex(ValueError, "exact audited"):
                build_mob_behaviors(game, "26.3", self.graph["nodes"])


if __name__ == "__main__":
    unittest.main()
