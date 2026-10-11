"""Check workstation relationships against the extracted game defaults."""
import json
from pathlib import Path
from zipfile import ZipFile
from supplemental_recipes import build_supplemental

root = Path(__file__).resolve().parents[1]
components = {'minecraft:' + p.stem: json.loads(p.read_text())['components']
              for p in (root / '.cache/generated/reports/minecraft/components/item').glob('*.json')}
items = set(components)
with ZipFile(root / '.cache/client.jar') as archive:
    def tags(tag):
        namespace, slug = tag.lstrip('#').split(':', 1)
        values = json.loads(archive.read(f'data/{namespace}/tags/item/{slug}.json'))['values']
        result = set()
        for value in values:
            value = value['id'] if isinstance(value, dict) else value
            result.update(tags(value[1:]) if value.startswith('#') else [value])
        return sorted(result)

    recipes = build_supplemental(items, components, tags, '26.3')

by_id = {r['id']: r for r in recipes}
repair = by_id['minecraft-graph:anvil_repair/diamond_pickaxe']
assert repair['ingredients'][1]['items'] == ['minecraft:diamond']
assert repair['results'][0]['item'] == 'minecraft:diamond_pickaxe'
assert 'minecraft-graph:anvil_combine/carved_pumpkin' not in by_id
assert not any('minecraft:bedrock' in i['items'] for r in recipes for i in r['ingredients'])
assert not any('minecraft:bedrock' == o['item'] for r in recipes for o in r['results'])
assert all(r['ingredients'][0]['items'] == [r['results'][0]['item']]
           for r in recipes if r['type'] == 'grindstone_repair')
assert by_id['minecraft-graph:cartography_clone/filled_map']['results'][0]['count'] == 2
assert 'minecraft-graph:cartography_extend/filled_map' in by_id
assert 'minecraft-graph:cartography_extend/abandoned_camp_map' not in by_id
loom = by_id['minecraft-graph:loom/white_banner/creeper']
assert len(loom['ingredients'][1]['items']) == 16
assert loom['ingredients'][2]['consumed'] is False
assert len({r['bannerPattern'] for r in recipes if r['type'] == 'loom'}) == 42
assert by_id['minecraft-graph:grindstone_disenchant/book_1_no_curses']['results'][0]['item'] == 'minecraft:book'
print(f'Workstation self-check passed: {len(recipes)} operations; all loom patterns and same-item repairs accounted for.')
