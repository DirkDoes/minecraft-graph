"""Assert actual registry coverage, conditional potion chains and trigger semantics."""
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image
from extract_data import CACHE, ROOT, GameData
from effect_relations import build_effects


class EffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jar = zipfile.ZipFile(CACHE / 'client.jar')
        cls.game = GameData(cls.jar, CACHE / 'generated/reports')
        cls.registry = json.loads((CACHE / 'effect-metadata.json').read_text())
        models = json.loads((CACHE / 'mob-models.json').read_text())
        cls.mob_nodes = [{'id': 'mob:' + entity} for entity, value in models['entities'].items() if value['mob']]
        cls.part = build_effects(cls.game, '26.3', cls.mob_nodes)
        cls.by_id = {r['id']: r for r in cls.part['relationships']}

    @classmethod
    def tearDownClass(cls):
        cls.jar.close()

    def test_full_registry_and_static_icons(self):
        effects = {n['effectId'] for n in self.part['nodes'] if n['effectId']}
        reported = json.loads((CACHE / 'generated/reports/registries.json').read_text())['minecraft:mob_effect']['entries']
        self.assertEqual(effects, set(reported))
        self.assertEqual(len(effects), 40)
        self.assertEqual(len(self.registry['potions']), 46)
        for node in self.part['nodes']:
            self.assertTrue(node['note'])
            with Image.open(ROOT / node['icon']) as image:
                self.assertEqual(image.width, image.height)
                self.assertIsNotNone(image.getbbox())
            if node['effectId']:
                slug = node['effectId'].split(':')[1]
                self.assertEqual((ROOT / node['icon']).read_bytes(), self.jar.read('assets/minecraft/textures/mob_effect/' + slug + '.png'))
        burning = next(n for n in self.part['nodes'] if n.get('state') == 'on_fire')
        self.assertIsNone(burning['effectId'])

    def test_potions_require_contents_and_preserve_durations(self):
        variants = [r for r in self.part['relationships'] if r['source'] == 'vanilla_potion_registry']
        expected = sum(len(effects) for effects in self.registry['potions'].values()) * 4
        self.assertEqual(len(variants), expected)
        self.assertTrue(all(r['requiredComponents']['minecraft:potion_contents']['potion'] not in
                            ('minecraft:water', 'minecraft:awkward', 'minecraft:mundane', 'minecraft:thick') for r in variants))
        arrow = self.by_id['effects:potion/minecraft:tipped_arrow/minecraft:poison/0']
        self.assertEqual(arrow['effect']['duration'], 900)
        self.assertEqual(arrow['applicationDurationTicks'], 112)
        self.assertEqual(arrow['durationScale'], .125)
        self.assertEqual(self.by_id['effects:potion/minecraft:potion/minecraft:strong_leaping/0']['effect']['amplifier'], 1)
        self.assertEqual(self.by_id['effects:mob_arrow_effect/stray']['applicationDurationTicks'], 600)
        self.assertEqual(self.by_id['effects:mob_arrow_effect/stray']['requiredComponents']['minecraft:potion_duration_scale'], 1)

    def test_food_removal_and_death_protection(self):
        flesh = self.by_id['effects:consume/minecraft:rotten_flesh/0/0']
        self.assertEqual(flesh['probability'], .8)
        self.assertEqual(flesh['effect']['duration'], 600)
        caps = self.part['coverage']['itemCapabilities']
        food_items = {item for item, c in self.game.components.items() if 'minecraft:food' in c}
        self.assertEqual(food_items, {item for item, c in caps.items() if 'food' in c})
        self.assertEqual(caps['minecraft:bread']['food']['nutrition'], 5)
        milk = self.by_id['effects:consume/minecraft:milk_bucket/0']
        self.assertEqual(len(milk['outputs']), 40)
        self.assertNotIn('effect:state:burning', {n['nodeId'] for n in milk['outputs']})
        honey = self.by_id['effects:consume/minecraft:honey_bottle/0']
        self.assertEqual(honey['outputs'], [{'nodeId': 'effect:minecraft:poison'}])
        totem = self.by_id['effects:death_protection/minecraft:totem_of_undying/1/0']
        self.assertEqual(totem['effect']['duration'], 900)
        self.assertEqual(totem['effect']['amplifier'], 1)
        self.assertEqual(len([r for r in self.part['relationships'] if r['id'].startswith('effects:stew/')]), 17)

    def test_real_spawn_loop_witch_and_curing(self):
        edges = {(e['source'], e['target'], e['type']) for e in self.part['edges']}
        self.assertIn(('effect:minecraft:oozing', 'mob:minecraft:slime', 'effect_spawn'), edges)
        self.assertIn(('effect:minecraft:infested', 'mob:minecraft:silverfish', 'effect_spawn'), edges)
        self.assertNotIn(('minecraft:potion', 'mob:minecraft:slime', 'effect_spawn'), edges)
        self.assertEqual(self.by_id['effects:infested_silverfish']['probability'], .1)
        brewing = json.loads(self.jar.read('data/minecraft/recipe/brewing/potion_awkward_slime_block.json'))
        self.assertEqual(brewing['reagent']['item'], 'minecraft:slime_block')
        self.assertEqual(brewing['output']['components']['minecraft:potion_contents']['potion'], 'minecraft:oozing')
        self.assertEqual(self.by_id['effects:witch/throw/poison']['producedComponents']['minecraft:potion_contents']['potion'], 'minecraft:poison')
        self.assertFalse(any(e['source'] == 'mob:minecraft:witch' and e['target'].startswith('effect:') for e in self.part['edges']))
        cure = self.by_id['effects:zombie_villager_cure']
        self.assertEqual({v['nodeId'] for v in cure['inputs']}, {'mob:minecraft:zombie_villager', 'minecraft:golden_apple', 'effect:minecraft:weakness'})
        self.assertEqual(cure['outputs'], [{'nodeId': 'mob:minecraft:villager'}])
        self.assertIn(('effect:minecraft:poison', 'mob:minecraft:cave_spider', 'effect_immunity'), edges)
        self.assertIn(('effect:minecraft:weakness', 'mob:minecraft:parched', 'effect_immunity'), edges)
        self.assertIn(('effect:minecraft:speed', 'mob:minecraft:wither', 'effect_immunity'), edges)
        self.assertIn(('effect:minecraft:speed', 'mob:minecraft:ender_dragon', 'effect_immunity'), edges)
        self.assertEqual(len(self.registry['entityEffectMethods']), 90)

    def test_references_bounds_and_fail_closed(self):
        node_ids = set(self.game.items) | {n['id'] for n in self.mob_nodes} | {n['id'] for n in self.part['nodes']}
        gathering = json.loads((CACHE / 'gathering-metadata.json').read_text())
        node_ids |= {'block:' + b for b, item in gathering['blockItems'].items() if item == 'minecraft:air'}
        self.assertEqual(len(self.by_id), len(self.part['relationships']))
        self.assertEqual(len({e['id'] for e in self.part['edges']}), len(self.part['edges']))
        for obj in self.part['nodes'] + self.part['relationships'] + self.part['edges']:
            self.assertEqual(obj['minVersion'], '26.3')
            self.assertIsNone(obj['maxVersion'])
        for edge in self.part['edges']:
            self.assertIn(edge['source'], node_ids)
            self.assertIn(edge['target'], node_ids)
            self.assertIn(edge['relationId'], self.by_id)
        with self.assertRaises(ValueError):
            build_effects(self.game, '26.4', self.mob_nodes)
        with patch.dict(self.game.components['minecraft:bread'], {'minecraft:consumable': {'on_consume_effects': [{'type': 'minecraft:unknown'}]}}):
            with self.assertRaisesRegex(ValueError, 'Unsupported default consume'):
                build_effects(self.game, '26.3', self.mob_nodes)


if __name__ == '__main__':
    unittest.main()
