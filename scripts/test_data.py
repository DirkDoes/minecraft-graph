"""Focused parser checks plus exhaustive coverage checks against the original game."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import unittest
import zipfile

from extract_data import CACHE, ROOT, GameData, build_edges, normalize_recipe


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads((ROOT / "data" / "graph.json").read_text(encoding="utf-8"))
        cls.provenance = json.loads((ROOT / "data" / "provenance.json").read_text(encoding="utf-8"))
        cls.nodes = {node["id"]: node for node in cls.graph["nodes"]}
        cls.recipes = {recipe["id"]: recipe for recipe in cls.graph["recipes"]}
        cls.jar = zipfile.ZipFile(CACHE / "client.jar")
        cls.game = GameData(cls.jar, CACHE / "generated" / "reports")

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_official_jar_and_entire_registry(self):
        self.assertEqual(hashlib.sha1((CACHE / "client.jar").read_bytes()).hexdigest(), self.provenance["clientSha1"])
        self.assertEqual({node["id"] for node in self.nodes.values() if node["kind"] == "item"}, self.game.items)
        self.assertEqual(len(self.nodes), len(self.graph["nodes"]))
        self.assertEqual(self.graph["version"], self.provenance["version"])
        for item in ("minecraft:bedrock", "minecraft:command_block", "minecraft:light", "minecraft:air"):
            self.assertIn(item, self.nodes)

    def test_every_vanilla_recipe_preserved_and_mapped(self):
        paths = [path for path in self.jar.namelist() if path.startswith("data/minecraft/recipe/") and path.endswith(".json")]
        official = {recipe["id"]: recipe for recipe in self.graph["recipes"] if recipe["source"] == "vanilla_recipe_json"}
        self.assertEqual(len(paths), len(official))
        self.assertEqual(len(paths), self.graph["counts"]["vanillaRecipeFiles"])
        for path in paths:
            recipe_id = "minecraft:" + path.removeprefix("data/minecraft/recipe/").removesuffix(".json")
            recipe = official[recipe_id]
            self.assertEqual(recipe["raw"], json.loads(self.jar.read(path)), recipe_id)
            self.assertTrue(recipe["ingredients"], recipe_id)
            self.assertTrue(recipe["results"], recipe_id)
        self.assertEqual(Counter(recipe["type"] for recipe in self.graph["recipes"]), self.provenance["recipeTypes"])

    def test_edges_refer_to_whole_recipes_and_correlate_identity(self):
        edge_ids = set()
        recipe_edges = Counter()
        for edge in self.graph["edges"]:
            self.assertNotIn(edge["id"], edge_ids)
            edge_ids.add(edge["id"])
            self.assertIn(edge["source"], self.nodes)
            self.assertIn(edge["target"], self.nodes)
            if edge["category"] != "recipe":
                continue
            recipe = self.recipes[edge["recipeId"]]
            group = recipe["ingredients"][edge["ingredientIndex"]]
            if self.nodes[edge["source"]]["kind"] == "category":
                self.assertEqual(self.nodes[edge["source"]]["tag"], group["tag"])
                if recipe.get("resultFromIngredient") == edge["ingredientIndex"]:
                    self.assertEqual(edge["requiredInputItem"], edge["target"])
                continue
            self.assertIn(edge["source"], group["items"])
            self.assertIn(edge["target"], {output["item"] for output in recipe["results"]})
            self.assertIn(edge["source"], self.nodes)
            self.assertIn(edge["target"], self.nodes)
            self.assertEqual(edge["type"], recipe["type"])
            self.assertEqual(edge["category"], "recipe")
            if recipe.get("resultFromIngredient") == edge["ingredientIndex"]:
                self.assertEqual(edge["source"], edge["target"])
            recipe_edges[recipe["id"]] += 1
        self.assertEqual(set(recipe_edges), set(self.recipes))
        for recipe in self.graph["recipes"]:
            expected = sum(len(group["items"]) if recipe.get("resultFromIngredient") == index else len(group["items"]) * len(recipe["results"]) for index, group in enumerate(recipe["ingredients"]))
            self.assertEqual(recipe_edges[recipe["id"]], expected, recipe["id"])
        for element in self.graph["nodes"] + self.graph["recipes"] + self.graph["edges"] + self.graph["relationships"]:
            self.assertEqual(element["minVersion"], self.graph["version"])
            self.assertIsNone(element["maxVersion"])

    def test_counts_alternatives_and_direction(self):
        block = self.recipes["minecraft:diamond_block"]
        self.assertEqual(block["ingredients"][0]["count"], 9)
        self.assertEqual(block["results"], [{"item": "minecraft:diamond_block", "count": 1}])
        reverse = self.recipes["minecraft:diamond"]
        self.assertEqual(reverse["results"], [{"item": "minecraft:diamond", "count": 9}])
        directions = {(edge["source"], edge["target"]) for edge in self.graph["edges"] if edge["category"] == "recipe"}
        self.assertIn(("minecraft:diamond", "minecraft:diamond_block"), directions)
        self.assertIn(("minecraft:diamond_block", "minecraft:diamond"), directions)
        self.assertFalse(any("minecraft:bedrock" in pair for pair in directions))
        self.assertFalse(any("minecraft:command_block" in pair for pair in directions))
        tag = self.game.resolve_tag("minecraft:trimmable_armor")
        self.assertIn("minecraft:diamond_chestplate", tag)
        self.assertIn("minecraft:netherite_boots", tag)
        arrow = self.recipes["minecraft:tipped_arrow"]
        self.assertEqual(arrow["ingredients"][1]["count"], 8)
        self.assertEqual(arrow["results"][0]["count"], 8)
        clone = self.recipes["minecraft:map_cloning"]
        self.assertEqual(clone["results"][0]["count"], 2)
        self.assertEqual(clone["results"][0]["maxCount"], 9)

    def test_component_conditions_and_optional_modifiers(self):
        brewing = next(r for r in self.graph["recipes"] if r["type"] == "brewing")
        self.assertIn("potion_contents", brewing["ingredients"][0]["predicates"])
        self.assertIn("minecraft:potion_contents", brewing["results"][0]["components"])
        rocket = self.recipes["minecraft:firework_rocket"]
        self.assertEqual(rocket["ingredients"][1]["maxCount"], 3)
        self.assertEqual(rocket["ingredients"][2]["count"], 0)
        self.assertTrue(rocket["ingredients"][2]["optional"])
        repair = self.recipes["minecraft:repair_item"]
        self.assertEqual(repair["ingredients"][0]["count"], 2)
        self.assertIn("minecraft:diamond_sword", repair["ingredients"][0]["items"])
        self.assertNotIn("minecraft:diamond", repair["ingredients"][0]["items"])

    def test_fail_closed_on_unknown_ingredient_or_serializer(self):
        with self.assertRaises(ValueError):
            self.game.ingredient("minecraft:not_a_real_item")
        with self.assertRaises(ValueError):
            normalize_recipe("test:future", {"type": "minecraft:unknown_future_recipe"}, self.game, "26.3")
        self.game.tags["test:cycle"] = {"values": ["#test:cycle"]}
        with self.assertRaises(ValueError):
            self.game.resolve_tag("test:cycle")
        self.game.tags["test:optional"] = {"values": [{"id": "#test:absent", "required": False}, "minecraft:diamond"]}
        self.assertEqual(self.game.resolve_tag("test:optional"), ["minecraft:diamond"])


if __name__ == "__main__":
    unittest.main()
