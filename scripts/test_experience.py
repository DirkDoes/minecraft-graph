import json
import unittest
from pathlib import Path

from experience_relations import NO_DEATH_XP, ORB

ROOT = Path(__file__).resolve().parents[1]


class ExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))

    def test_entity_and_conditional_sources(self):
        graph = self.graph
        orb = next(node for node in graph["nodes"] if node["id"] == ORB)
        self.assertEqual(orb["kind"], "entity")
        self.assertTrue((ROOT / orb["icon"]).is_file())
        records = {r["id"]: r for r in graph["relationships"]}
        edges = [e for e in graph["edges"] if e["target"] == ORB]
        sources = {(e["source"], e["type"]) for e in edges}
        for source, kind in [("mob:minecraft:skeleton", "mob_experience"), ("minecraft:diamond_ore", "mining_experience"),
                             ("minecraft:sculk_sensor", "mining_experience"), ("minecraft:raw_iron", "smelting_experience"),
                             ("minecraft:furnace", "smelting_experience"), ("minecraft:fishing_rod", "fishing_experience"),
                             ("minecraft:experience_bottle", "bottle_experience"), ("mob:minecraft:sheep", "breeding_experience")]:
            self.assertIn((source, kind), sources)
        for slug in NO_DEATH_XP:
            self.assertNotIn(("mob:minecraft:" + slug, "mob_experience"), sources)
        self.assertFalse(any(e["source"] == "minecraft:campfire" for e in edges))
        for edge in edges:
            self.assertEqual(edge["minVersion"], graph["version"])
            self.assertTrue(records[edge["relationId"]]["note"])
        cooked = {r["cookingRecipeId"] for r in records.values() if r["type"] == "smelting_experience"}
        self.assertEqual(cooked, {r["id"] for r in graph["recipes"] if r["type"] in {"smelting", "smoking", "blasting"} and r.get("experience", 0) > 0})

    def test_every_coral_form_and_no_false_revival(self):
        edges = [e for e in self.graph["edges"] if e["type"] == "coral_dying"]
        for color in ("tube", "brain", "bubble", "fire", "horn"):
            for suffix in ("coral", "coral_fan", "coral_block"):
                living = "minecraft:" + color + "_" + suffix
                dead = "minecraft:dead_" + color + "_" + suffix
                self.assertTrue(any(e["source"] == living and e["target"] == dead for e in edges), living)
                self.assertFalse(any(e["source"] == dead and e["target"] == living for e in edges), living)
        self.assertEqual(len(edges), 20, "all five wall fan states are also retained")
        self.assertEqual(self.graph["coverage"]["experience"]["coralStateMappings"], 20)


if __name__ == "__main__":
    unittest.main()
