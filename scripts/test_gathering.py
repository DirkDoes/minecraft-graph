"""Check complete gathering sources and that conditional outcomes stay conditional."""
import json
from pathlib import Path
import unittest
import zipfile

from extract_data import CACHE, ROOT, GameData
from gathering_relations import build_gathering


class GatheringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads((ROOT / 'data/graph.json').read_text(encoding='utf-8'))
        cls.jar = zipfile.ZipFile(CACHE / 'client.jar')
        cls.game = GameData(cls.jar, CACHE / 'generated/reports')
        cls.part = build_gathering(cls.game, cls.graph['version'], [n for n in cls.graph['nodes'] if n['kind'] == 'mob'])

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_every_compostable_and_block_table(self):
        items = {item for item, c in self.game.components.items() if 'minecraft:compostable' in c}
        records = [r for r in self.part['relationships'] if r['type'] == 'composting']
        self.assertEqual({r['ingredients'][0]['items'][0] for r in records}, items)
        by_item = {r['ingredients'][0]['items'][0]: r for r in records}
        self.assertEqual(by_item['minecraft:wheat_seeds']['layerChance'], .3)
        self.assertEqual(by_item['minecraft:cake']['layerChance'], 1)
        self.assertTrue(all(r['layersRequired'] == 7 for r in records))
        self.assertTrue(all(r['ingredients'][1]['consumed'] is False for r in records))
        tables = {'minecraft:' + p.removeprefix('data/minecraft/loot_table/').removesuffix('.json') for p in self.jar.namelist() if p.startswith('data/minecraft/loot_table/blocks/') and p.endswith('.json')}
        self.assertEqual(tables, {t for t in self.part['coverage']['lootTables'] if t.startswith('minecraft:blocks/')})

    def test_references_versions_and_conditional_loot(self):
        node_ids = {n['id'] for n in self.graph['nodes']} | {n['id'] for n in self.part['nodes']}
        relation_ids = {r['id'] for r in self.part['relationships']}
        self.assertEqual(len(relation_ids), len(self.part['relationships']))
        self.assertEqual(len({e['id'] for e in self.part['edges']}), len(self.part['edges']))
        for edge in self.part['edges']:
            self.assertIn(edge['source'], node_ids)
            self.assertIn(edge['target'], node_ids)
            self.assertIn(edge['relationId'], relation_ids)
            self.assertEqual(edge['minVersion'], '26.3')
            self.assertIsNone(edge['maxVersion'])
        fishing = [r for r in self.part['relationships'] if r['type'] == 'fishing']
        self.assertTrue(any(r['loot']['conditions'] for r in fishing))
        self.assertTrue(all(r['loot']['selection'] for r in fishing))
        self.assertTrue(any(r['loot']['modifiers'] for r in fishing))
        self.assertTrue(any(r['outputs'][0]['nodeId'] == 'minecraft:enchanted_book' for r in fishing))

    def test_manual_gathering_and_fail_closed_version(self):
        directions = {(e['source'], e['target'], e['type']) for e in self.part['edges']}
        for source, target, kind in [('minecraft:beehive','minecraft:honey_bottle','honey_harvesting'), ('mob:minecraft:cow','minecraft:milk_bucket','milking'), ('mob:minecraft:sheep','minecraft:white_wool','shearing'), ('mob:minecraft:armadillo','minecraft:armadillo_scute','brushing'), ('mob:minecraft:piglin','minecraft:ender_pearl','bartering'), ('block:minecraft:water','minecraft:water_bucket','bucket_filling')]:
            self.assertIn((source, target, kind), directions)
        with self.assertRaises(ValueError):
            build_gathering(self.game, '26.4', [])


if __name__ == '__main__':
    unittest.main()
