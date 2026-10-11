"""Completeness, provenance and generator-boundary checks against the actual client."""
import gzip
import json
import unittest
import zipfile

from extract_data import CACHE, ROOT, GameData
from structure_relations import StructureSources, build_structures, names, read_nbt


class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jar = zipfile.ZipFile(CACHE / "client.jar")
        cls.game = GameData(cls.jar, CACHE / "generated/reports")
        graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        cls.existing = graph["nodes"]
        node_ids = {node["id"] for node in cls.existing}
        for biome in names(cls.game, "worldgen/biome"):
            if "biome:" + biome not in node_ids:
                cls.existing.append({"id": "biome:" + biome})
        cls.part = build_structures(cls.game, "26.3", cls.existing)
        cls.records = {record["id"]: record for record in cls.part["relationships"]}
        cls.nodes = {node["id"]: node for node in cls.part["nodes"]}
        cls.directions = {(edge["source"], edge["target"], edge["type"]) for edge in cls.part["edges"]}

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_every_registered_structure_and_known_missing_template(self):
        registered = names(self.game, "worldgen/structure")
        self.assertEqual(len(registered), 52)
        self.assertEqual({"structure:" + name for name in registered},
                         {node["id"] for node in self.part["nodes"] if node["kind"] == "structure" and "generationKind" not in node})
        self.assertEqual(self.part["coverage"]["missingVanillaTemplateReferences"],
                         ["minecraft:ancient_city/walls/intact_horizontal_wall_stairs_5"])
        self.assertFalse(self.part["coverage"]["templateEntitiesNotRepresented"])
        for node in self.part["nodes"]:
            if node["kind"] == "structure":
                self.assertTrue((ROOT / node["icon"]).is_file(), node["id"])
                self.assertTrue(self.part["coverage"]["structures"][node["id"]]["blocks"], node["id"])

    def test_references_versions_and_secondary_paths(self):
        ids = {node["id"] for node in self.existing} | set(self.nodes)
        self.assertEqual(len(self.records), len(self.part["relationships"]))
        self.assertEqual(len({edge["id"] for edge in self.part["edges"]}), len(self.part["edges"]))
        for edge in self.part["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)
            self.assertIn(edge["relationId"], self.records)
            self.assertFalse(edge["target"].startswith("dimension:"))
            self.assertEqual(edge["minVersion"], "26.3")
            self.assertIsNone(edge["maxVersion"])
        self.assertIn(("structure:minecraft:fortress", "biome:minecraft:nether_wastes", "structure_biome"), self.directions)
        with self.assertRaises(ValueError):
            build_structures(self.game, "26.4", self.existing)

    def test_blocks_are_outputs_not_terrain_tests(self):
        expected = (("end_city", "minecraft:purpur_block"), ("desert_pyramid", "minecraft:cut_sandstone"),
                    ("desert_pyramid", "minecraft:blue_terracotta"), ("jungle_pyramid", "minecraft:dispenser"),
                    ("nether_fossil", "minecraft:dried_ghast"), ("fossil_diamonds", "minecraft:deepslate_diamond_ore"))
        for structure, target in expected:
            self.assertIn(("structure:minecraft:" + structure, target, "structure_block"), self.directions)
        for structure, block in (("buried_treasure", "minecraft:andesite"), ("mineshaft", "minecraft:lava"),
                                 ("monument", "minecraft:ice"), ("monument", "minecraft:blue_ice"),
                                 ("nether_fossil", "minecraft:soul_sand"), ("fossil_diamonds", "minecraft:coal_ore"),
                                 ("ruined_portal_desert", "minecraft:jungle_leaves"), ("ruined_portal_desert", "minecraft:vine")):
            self.assertNotIn(("structure:minecraft:" + structure, block, "structure_block"), self.directions)

    def test_residents_spawners_overrides_and_decorations_are_separate(self):
        for structure, mob, kind in (("swamp_hut", "witch", "structure_generated_mob"),
                                     ("swamp_hut", "witch", "structure_spawn_mob"),
                                     ("fortress", "blaze", "structure_spawner_mob"),
                                     ("fortress", "blaze", "structure_spawn_mob"),
                                     ("monument", "elder_guardian", "structure_generated_mob"),
                                     ("monument", "guardian", "structure_spawn_mob"),
                                     ("end_city", "shulker", "structure_generated_mob"),
                                     ("trial_chambers", "breeze", "structure_spawner_mob"),
                                     ("monster_room", "zombie", "structure_spawner_mob")):
            self.assertIn(("structure:minecraft:" + structure, "mob:minecraft:" + mob, kind), self.directions)
        self.assertIn(("structure:minecraft:end_city", "minecraft:elytra", "structure_item"), self.directions)
        self.assertIn(("structure:minecraft:end_spike", "minecraft:end_crystal", "structure_item"), self.directions)
        self.assertIn(("structure:minecraft:village_taiga", "minecraft:iron_helmet", "structure_item"), self.directions)
        self.assertIn(("structure:minecraft:village_taiga", "minecraft:iron_chestplate", "structure_item"), self.directions)
        self.assertIn(("structure:minecraft:end_podium_active", "minecraft:dragon_egg", "structure_block"), self.directions)
        self.assertIn(("structure:minecraft:abandoned_camp_bamboo_jungle", "minecraft:orange_cushion", "structure_item"), self.directions)

    def test_loot_retains_predicates_modifiers_and_shared_context(self):
        loot = [record for record in self.records.values() if record["type"] == "structure_loot"]
        self.assertTrue(loot)
        for record in loot:
            self.assertTrue(record["loot"]["selection"])
            reference = record["contextRef"]
            self.assertTrue(self.nodes[reference["nodeId"]]["lootContexts"][reference["lootTable"]])
            self.assertEqual(record["loot"]["sourceLootTable"], reference["lootTable"])
        self.assertTrue(any(record["loot"]["conditions"] for record in loot))
        self.assertTrue(any(record["loot"]["modifiers"] for record in loot))
        self.assertIn(("structure:minecraft:buried_treasure", "minecraft:heart_of_the_sea", "structure_loot"), self.directions)
        self.assertIn("minecraft:archaeology/desert_well", self.part["coverage"]["structures"]["structure:minecraft:desert_well"]["lootTables"])
        self.assertIn("minecraft:chests/trial_chambers/reward_ominous", self.part["coverage"]["structures"]["structure:minecraft:trial_chambers"]["lootTables"])

    def test_nbt_all_template_variants_and_invalid_input(self):
        files = [path for path in self.jar.namelist() if path.startswith("data/minecraft/structure/") and path.endswith(".nbt")]
        self.assertEqual(len(files), self.part["coverage"]["allVanillaTemplates"])
        for path in files:
            value = read_nbt(self.jar.read(path))
            for palette in value.get("palettes", [value.get("palette", [])]):
                self.assertTrue(all(0 <= block["state"] < len(palette) for block in value["blocks"]), path)
        minimal = b"\x0a\x00\x00\x08\x00\x04name\x00\x04test\x00"
        self.assertEqual(read_nbt(minimal), {"name": "test"})
        self.assertEqual(read_nbt(gzip.compress(minimal)), {"name": "test"})
        with self.assertRaises(ValueError):
            read_nbt(minimal[:-1])

    def test_jigsaw_terminal_fallback_and_connector_names(self):
        sources = StructureSources(self.game)
        def template(next_pool=None, name="minecraft:bottom"):
            nbt = {"id": "minecraft:jigsaw", "name": name}
            if next_pool:
                nbt.update(pool=next_pool, target="minecraft:bottom")
            return {"blocks": [{"nbt": nbt}]}
        sources.templates = {"minecraft:start": template("minecraft:child_pool"), "minecraft:child": template("minecraft:terminal_pool"),
                             "minecraft:end": template(), "minecraft:wrong": template(name="minecraft:wrong"),
                             "minecraft:forbidden": template()}
        def entry(name):
            return {"weight": 1, "element": {"element_type": "minecraft:single_pool_element", "location": name, "processors": {"processors": []}}}
        sources.pools = {"minecraft:start_pool": {"elements": [entry("minecraft:start")], "fallback": "minecraft:forbidden_pool"},
                         "minecraft:child_pool": {"elements": [entry("minecraft:child"), entry("minecraft:wrong")], "fallback": "minecraft:empty"},
                         "minecraft:terminal_pool": {"elements": [entry("minecraft:forbidden")], "fallback": "minecraft:end_pool"},
                         "minecraft:end_pool": {"elements": [entry("minecraft:end")], "fallback": "minecraft:forbidden_pool"},
                         "minecraft:forbidden_pool": {"elements": [entry("minecraft:forbidden")], "fallback": "minecraft:empty"}}
        templates, _, _ = sources.jigsaw({"start_pool": "minecraft:start_pool", "size": 1})
        found = {entry["template"]: entry for entry in templates}
        self.assertEqual(set(found), {"minecraft:start", "minecraft:child", "minecraft:end"})
        self.assertEqual(found["minecraft:end"]["depth"], 2)
        self.assertTrue(found["minecraft:end"]["fallback"])

    def test_processors_do_not_add_unmatched_outputs(self):
        sources = StructureSources(self.game)
        processor = {"processors": [{"processor_type": "minecraft:rule", "rules": [
            {"input_predicate": {"predicate_type": "minecraft:block_match", "block": "minecraft:torch"},
             "location_predicate": {"predicate_type": "minecraft:always_true"}, "output_state": "minecraft:air"},
            {"input_predicate": {"predicate_type": "minecraft:block_match", "block": "minecraft:gravel"},
             "location_predicate": {"predicate_type": "minecraft:always_true"}, "output_state": "minecraft:suspicious_gravel"}]}]}
        self.assertEqual(sources.processed("minecraft:torch", processor)[0], {"minecraft:air"})
        self.assertEqual(sources.processed("minecraft:stone", processor)[0], {"minecraft:stone"})


if __name__ == "__main__":
    unittest.main()
