"""Check category completeness and preservation of the underlying recipe graph."""
import copy
import json
import unittest
import zipfile

from category_relations import build_categories
from extract_data import CACHE, ROOT, GameData, build_edges


class CategoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jar = zipfile.ZipFile(CACHE / "client.jar")
        cls.game = GameData(cls.jar, CACHE / "generated" / "reports")
        graph = json.loads((ROOT / "data" / "graph.json").read_text(encoding="utf-8"))
        cls.recipes = graph["recipes"]
        cls.version = graph["version"]
        cls.categories = build_categories(cls.game, cls.recipes, cls.version)
        cls.nodes = {node["id"]: node for node in cls.categories["nodes"]}

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_all_tags_members_and_icons(self):
        self.assertEqual(set(self.nodes), {f"tag:{tag}" for tag in self.game.tags if self.game.resolve_tag(tag)})
        memberships = {(edge["source"], edge["target"]) for edge in self.categories["edges"] if edge["type"] == "belongs_to"}
        for tag in self.game.tags:
            self.assertEqual({source for source, target in memberships if target == f"tag:{tag}"}, set(self.game.resolve_tag(tag)))
        for node in self.nodes.values():
            self.assertTrue((ROOT / node["icon"]).is_file(), node["id"])
            self.assertEqual(node["kind"], "category")
        for name in ("planks", "leaves", "logs", "wool"):
            self.assertIn(f"tag:minecraft:{name}", self.nodes)

    def test_planks_recipe_preserves_every_item_edge(self):
        recipes_before = copy.deepcopy(self.recipes)
        original_edges = build_edges(self.recipes, self.game.items)
        categories = build_categories(self.game, self.recipes, self.version)
        self.assertEqual(self.recipes, recipes_before)
        self.assertEqual(build_edges(self.recipes, self.game.items), original_edges)
        recipe_edges = [edge for edge in categories["edges"] if edge.get("recipeId") == "minecraft:crafting_table"]
        self.assertEqual([(edge["source"], edge["target"]) for edge in recipe_edges], [("tag:minecraft:planks", "minecraft:crafting_table")])
        original_planks = {edge["source"] for edge in original_edges if edge["recipeId"] == "minecraft:crafting_table"}
        self.assertEqual(original_planks, set(self.game.resolve_tag("minecraft:planks")))

    def test_recipe_identity_optional_and_no_untagged_invention(self):
        tagged = {(recipe["id"], index) for recipe in self.recipes for index, group in enumerate(recipe["ingredients"]) if group.get("tag")}
        edges = [edge for edge in self.categories["edges"] if edge["category"] == "recipe"]
        self.assertEqual({(edge["recipeId"], edge["ingredientIndex"]) for edge in edges}, tagged)
        recipes = {recipe["id"]: recipe for recipe in self.recipes}
        for edge in edges:
            recipe = recipes[edge["recipeId"]]
            group = recipe["ingredients"][edge["ingredientIndex"]]
            self.assertEqual(edge["source"], f"tag:{group['tag']}")
            self.assertEqual(edge["optional"], group.get("optional", False))
            self.assertEqual(edge["type"], recipe["type"])
            if recipe.get("resultFromIngredient") == edge["ingredientIndex"]:
                self.assertIn(edge["target"], group["items"])
                self.assertEqual(edge["requiredInputItem"], edge["target"])
        sample = {"id": "test:optional_identity", "type": "test", "category": "recipe", "minVersion": self.version, "maxVersion": None,
                  "ingredients": [{"items": ["minecraft:oak_planks"], "tag": "minecraft:planks", "optional": True}],
                  "results": [{"item": "minecraft:oak_planks"}, {"item": "minecraft:birch_planks"}], "resultFromIngredient": 0}
        sample_edges = [edge for edge in build_categories(self.game, [sample], self.version)["edges"] if edge["category"] == "recipe"]
        self.assertEqual([edge["target"] for edge in sample_edges], ["minecraft:oak_planks"])
        self.assertTrue(sample_edges[0]["optional"])

    def test_nested_tags_are_direct_and_resolved(self):
        edges = [edge for edge in self.categories["edges"] if edge["type"] == "tag_contains"]
        expected = set()
        for tag, raw in self.game.tags.items():
            for value in raw["values"]:
                value = value if isinstance(value, str) else value["id"]
                if value.startswith("#") and f"tag:{value[1:]}" in self.nodes:
                    expected.add((f"tag:{value[1:]}", f"tag:{tag}"))
        self.assertEqual({(edge["source"], edge["target"]) for edge in edges}, expected)
        for edge in edges:
            child, parent = self.nodes[edge["source"]]["tag"], self.nodes[edge["target"]]["tag"]
            self.assertLessEqual(set(self.game.resolve_tag(child)), set(self.game.resolve_tag(parent)))

    def test_record_references_ids_and_version_bounds(self):
        relation_ids = {relation["id"] for relation in self.categories["relationships"]}
        all_nodes = set(self.nodes) | self.game.items
        self.assertEqual(len({edge["id"] for edge in self.categories["edges"]}), len(self.categories["edges"]))
        for edge in self.categories["edges"]:
            self.assertIn(edge["source"], all_nodes)
            self.assertIn(edge["target"], all_nodes)
            if edge["category"] == "membership":
                self.assertIn(edge["relationId"], relation_ids)
        for record in self.categories["nodes"] + self.categories["relationships"] + self.categories["edges"]:
            self.assertEqual(record["minVersion"], self.version)
            self.assertIsNone(record["maxVersion"])


if __name__ == "__main__":
    unittest.main()
