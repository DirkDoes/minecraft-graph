import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import zipfile

from PIL import Image

from extract_data import GameData
from mob_relations import build_mobs, iter_loot_items, ROOT


class MobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jar = zipfile.ZipFile(ROOT / ".cache/client.jar")
        cls.game = GameData(cls.jar, ROOT / ".cache/generated/reports")
        cls.graph = build_mobs(cls.game, "26.3")

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_registry_classification_and_every_real_icon(self):
        registry = json.loads((ROOT / ".cache/generated/reports/registries.json").read_text())["minecraft:entity_type"]["entries"]
        models = json.loads((ROOT / ".cache/mob-models.json").read_text())
        self.assertEqual(set(registry), set(models["entities"]))
        self.assertEqual(len(registry), 161)
        mobs = {node["entityType"] for node in self.graph["nodes"]}
        self.assertEqual(mobs, {key for key, value in models["entities"].items() if value["mob"]})
        self.assertEqual(len(mobs), 90)
        self.assertTrue({"minecraft:creaking", "minecraft:giant", "minecraft:camel_husk", "minecraft:zombie_nautilus", "minecraft:sulfur_cube"} <= mobs)
        self.assertFalse({"minecraft:player", "minecraft:mannequin", "minecraft:armor_stand", "minecraft:arrow", "minecraft:oak_boat"} & mobs)
        icons = json.loads((ROOT / "assets/mobs/coverage.json").read_text())["icons"]
        self.assertEqual(set(icons), mobs)
        for node in self.graph["nodes"]:
            with Image.open(ROOT / node["icon"]) as image:
                self.assertEqual(image.size, (64, 64))
                self.assertIsNotNone(image.getbbox(), node["id"])
            self.assertEqual(icons[node["entityType"]]["method"], "official_mob_model")

    def test_examples_and_no_loot_entities(self):
        edges = {(edge["source"], edge["target"]) for edge in self.graph["edges"]}
        for mob, item in (("skeleton", "bone"), ("witch", "sugar"), ("witch", "potion"), ("zombie", "rotten_flesh"), ("zombie_villager", "rotten_flesh")):
            self.assertIn(("mob:minecraft:" + mob, "minecraft:" + item), edges)
        self.assertFalse(any(source == "mob:minecraft:creaking" for source, _ in edges))
        potions = [relation for relation in self.graph["relationships"] if relation["inputs"] == ["mob:minecraft:witch"] and relation["item"] == "minecraft:potion"]
        self.assertEqual(len(potions), 4)
        self.assertTrue(all(relation["conditional"] and len(relation["conditions"]) == 3 for relation in potions))
        self.assertIn(("mob:minecraft:skeleton", "minecraft:skeleton_skull"), edges)
        skull = next(relation for relation in self.graph["relationships"] if relation["id"] == "loot:charged_creeper/2")
        self.assertIn("alreadyDroppedSkull", json.dumps(skull["conditions"]))

    def test_nested_references_preserve_sheep_predicates(self):
        drops = list(iter_loot_items(self.game, "minecraft:entities/sheep"))
        wool = [drop for drop in drops if drop["item"].endswith("_wool")]
        self.assertEqual(len(wool), 16)
        self.assertTrue(all(drop["conditions"] for drop in wool))
        white = next(drop for drop in wool if drop["item"] == "minecraft:white_wool")
        self.assertEqual(white["resolvedLootTable"], "minecraft:entities/sheep/white")
        self.assertIn("sheared", json.dumps(white["conditions"]))
        self.assertTrue(white["selection"])
        discs = {drop["item"] for drop in iter_loot_items(self.game, "minecraft:entities/creeper") if drop["rawEntry"]["type"] == "minecraft:tag"}
        self.assertEqual(discs, set(self.game.resolve_tag("minecraft:creeper_drop_music_discs")))

    def test_reference_cycles_and_unknown_entries_fail_clearly(self):
        content = BytesIO()
        with zipfile.ZipFile(content, "w") as jar:
            for name, entry in (("a", {"type": "minecraft:loot_table", "value": "minecraft:b"}), ("b", {"type": "minecraft:loot_table", "value": "minecraft:a"}), ("unknown", {"type": "minecraft:future_entry"})):
                jar.writestr(f"data/minecraft/loot_table/{name}.json", json.dumps({"pools": [{"entries": [entry], "rolls": 1}]}))
        with zipfile.ZipFile(content) as jar:
            game = SimpleNamespace(jar=jar, _loot_smelting={}, items=set())
            with self.assertRaisesRegex(ValueError, "Cyclic loot reference"):
                list(iter_loot_items(game, "minecraft:a"))
            with self.assertRaisesRegex(ValueError, "Unsupported loot entry"):
                list(iter_loot_items(game, "minecraft:unknown"))

    def test_stale_geometry_cache_rejected(self):
        models = json.loads((ROOT / ".cache/mob-models.json").read_text())
        for field, value in (("version", "26.2"), ("clientSha1", "0" * 40)):
            stale = json.dumps(models | {field: value})
            with patch.object(Path, "read_text", return_value=stale):
                with self.assertRaisesRegex(ValueError, "version/client SHA1 mismatch"):
                    build_mobs(self.game, "26.3")

    def test_conditional_smelting_and_book_transformations(self):
        drops = list(iter_loot_items(self.game, "minecraft:entities/cow"))
        beef = next(drop for drop in drops if drop["item"] == "minecraft:beef")
        cooked = next(drop for drop in drops if drop["item"] == "minecraft:cooked_beef")
        self.assertIn("minecraft:inverted", json.dumps(beef["conditions"]))
        self.assertIn("is_on_fire", json.dumps(cooked["conditions"]))
        self.assertTrue(cooked["modifiers"])
        books = list(iter_loot_items(self.game, "minecraft:gameplay/fishing/treasure"))
        self.assertIn("minecraft:enchanted_book", {drop["item"] for drop in books})
        self.assertNotIn("minecraft:book", {drop["item"] for drop in books})

    def test_every_official_loot_table_resolves(self):
        paths = [path for path in self.jar.namelist() if path.startswith("data/minecraft/loot_table/") and path.endswith(".json")]
        self.assertEqual(len(paths), 1447)
        outputs = 0
        for path in paths:
            table_id = "minecraft:" + path.removeprefix("data/minecraft/loot_table/").removesuffix(".json")
            for drop in iter_loot_items(self.game, table_id):
                self.assertIn(drop["item"], self.game.items)
                self.assertTrue(drop["conditional"])
                self.assertTrue(drop["entryPath"])
                outputs += 1
        self.assertGreater(outputs, 2700)


if __name__ == "__main__":
    unittest.main()
