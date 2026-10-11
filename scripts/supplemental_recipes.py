"""Item relationships for vanilla workstation operations outside recipe JSON.

Inputs come from the 26.3 game registry/component reports and bundled tags.
The formulas/conditions were checked against the corresponding menu bytecode.
"""
import json
from pathlib import Path
from zipfile import ZipFile


def build_supplemental(items, components, tags, version):
    if version != '26.3':
        raise ValueError('Workstation menu logic is audited for 26.3. Audit the new version before exporting it.')
    recipes = []
    jar = Path(__file__).resolve().parents[1] / '.cache' / 'client.jar'

    def ingredient(ids, **extra):
        ids = [ids] if isinstance(ids, str) else sorted(ids)
        assert ids and set(ids) <= items, f'Unknown workstation ingredient: {ids}'
        return {'items': ids, 'count': 1, **extra}

    def add(kind, key, inputs, output, notes, count=1, **extra):
        assert output in items
        recipes.append({
            'id': f'minecraft-graph:{kind}/{key}', 'type': kind, 'category': 'recipe',
            'minVersion': version, 'maxVersion': None, 'ingredients': inputs,
            'results': [{'item': output, 'count': count}], 'dynamic': True,
            'note': notes, 'source': 'game_code_and_components', **extra,
        })

    def holder_items(value):
        if isinstance(value, list):
            result = set()
            for entry in value:
                result.update(holder_items(entry))
            return result
        if value.startswith('#'):
            return set(tags(value[1:]))
        return {value}

    damageable = sorted(item for item, comp in components.items() if comp.get('minecraft:max_damage', 0) > 0)
    for item in damageable:
        slug = item.split(':')[1]
        repair = components[item].get('minecraft:repairable')
        if repair:
            add('anvil_repair', slug, [ingredient(item), ingredient(holder_items(repair['items']))], item,
                'Requires a damaged base item. Each consumed repair material restores up to 25% of maximum durability; use as many materials as needed. Enchantments remain. Experience/prior-work costs apply; survival cost must be below 40 levels.',
                variableMaterialCount=True)
        add('anvil_combine', slug, [ingredient(item, count=2)], item,
            'Two copies of the SAME item in separate slots. Combines remaining durability plus a 12% maximum-durability bonus, capped at maximum; merges compatible enchantments. Requires an improvement. Experience/prior-work costs apply; survival cost must be below 40 levels.')
        add('grindstone_repair', slug, [ingredient(item, count=2)], item,
            'Two copies of the SAME item in separate slots. Combines remaining durability plus a 5% maximum-durability bonus, capped at maximum. Removes non-curse enchantments and prior-work cost; curses remain.')

    with ZipFile(jar) as archive:
        enchantable = set()
        for name in archive.namelist():
            if name.startswith('data/minecraft/enchantment/') and name.endswith('.json'):
                enchantable.update(holder_items(json.loads(archive.read(name))['supported_items']))
        enchantable.add('minecraft:enchanted_book')
        for item in sorted(enchantable):
            slug = item.split(':')[1]
            add('anvil_enchant', slug, [ingredient(item), ingredient('minecraft:enchanted_book')], item,
                'The book must contain an enchantment supported by the base item. Only compatible enchantments merge; equal levels may upgrade up to the enchantment maximum. Output retains the base item ID. Experience/prior-work costs apply; survival cost must be below 40 levels.')
            if item == 'minecraft:enchanted_book':
                add('anvil_combine', slug, [ingredient(item, count=2)], item,
                    'Two enchanted books in separate slots; the right book must contribute compatible enchantments. Only one output book. Experience/prior-work costs apply; survival cost must be below 40 levels.')
            if item != 'minecraft:enchanted_book':
                add('grindstone_disenchant', slug, [ingredient(item)], item,
                    'Requires an enchanted item. Removes all non-curse enchantments and resets prior-work cost; curses remain. The output keeps the same item ID.')
        for count in [1, 2]:
            add('grindstone_disenchant', f'book_{count}_no_curses', [ingredient('minecraft:enchanted_book', count=count)], 'minecraft:book',
                'Requires enchanted book(s) with no curse remaining after removal. Non-curse enchantments are removed and the output becomes one ordinary book.')
            add('grindstone_disenchant', f'book_{count}_curses', [ingredient('minecraft:enchanted_book', count=count)], 'minecraft:enchanted_book',
                'Requires enchanted book(s) with at least one curse. Non-curse enchantments are removed; curses remain, so the output stays one enchanted book.')

        def pattern_tag(tag, visiting=()):
            assert tag not in visiting, f'Banner pattern tag cycle: {tag}'
            namespace, slug = tag.split(':', 1)
            values = json.loads(archive.read(f'data/{namespace}/tags/banner_pattern/{slug}.json'))['values']
            result = set()
            for value in values:
                value = value['id'] if isinstance(value, dict) else value
                result.update(pattern_tag(value[1:], (*visiting, tag)) if value.startswith('#') else [value])
            return result

        banners = sorted(item for item in tags('minecraft:banners') if 'minecraft:banner_patterns' in components[item])
        dyes = sorted(item for item in tags('minecraft:loom_dyes') if 'minecraft:dye' in components[item])
        patterns = {pattern: None for pattern in pattern_tag('minecraft:no_item_required')}
        for item in tags('minecraft:loom_patterns'):
            provider = components[item].get('minecraft:provides_banner_patterns')
            if provider:
                for pattern in pattern_tag(provider[1:]) if provider.startswith('#') else [provider]:
                    patterns[pattern] = item
        for banner in banners:
            for pattern, provider in sorted(patterns.items()):
                inputs = [ingredient(banner), ingredient(dyes, tag='minecraft:loom_dyes')]
                if provider:
                    inputs.append(ingredient(provider, consumed=False))
                add('loom', f'{banner.split(":")[1]}/{pattern.split(":")[1]}', inputs, banner,
                    'Consumes one banner and one chosen dye, appending the chosen colored pattern. The banner must have fewer than six existing patterns. The optional banner-pattern item is retained. Output keeps the base banner color/item ID.',
                    bannerPattern=pattern)

    maps = tags('minecraft:clonable_maps')
    for item in maps:
        slug = item.split(':')[1]
        add('cartography_clone', slug, [ingredient(item), ingredient('minecraft:map')], item,
            'Requires an initialized map with saved map data. Copies it using one empty map, producing two maps with the same map data.', count=2)
        add('cartography_lock', slug, [ingredient(item), ingredient('minecraft:glass_pane')], item,
            'Requires an initialized, unlocked map. Consumes one glass pane to lock its saved map data; the item ID stays the same.')
    for item in tags('minecraft:extendable_maps'):
        add('cartography_extend', item.split(':')[1], [ingredient(item), ingredient('minecraft:paper')], item,
            'Requires an initialized, unlocked map with scale below 4. Consumes one paper and increases map scale by one. Explorer maps and buried-treasure maps are excluded by the game tag.')
    assert len({r['id'] for r in recipes}) == len(recipes)
    return recipes
