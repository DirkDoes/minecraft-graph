"""Vanilla status effects and their conditional application/removal pathways.

Registry potion/effect values and default item components come from the verified
client; triggers in game code are explicitly audited for this release.
"""
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EFFECT_NOTES = {
    'absorption': 'Adds an absorption-health buffer. The registry attribute modifier grants 4 extra absorption health per level.',
    'bad_omen': 'Converts to Raid Omen on entering an eligible village, or Trial Omen when an eligible trial spawner detects the player.',
    'blindness': 'Restricts vision and interferes with player sprinting and critical-hit behavior.',
    'breath_of_the_nautilus': 'Prevents air from decreasing while riding a nautilus; a short refreshed duration allows a brief grace period after dismounting.',
    'conduit_power': 'Provides underwater breathing, visibility and mining benefits while the entity satisfies their water conditions.',
    'darkness': 'Pulses the player’s view into darkness; it does not directly deal damage.',
    'dolphins_grace': 'Reduces underwater movement drag, allowing the affected player to swim faster.',
    'fire_resistance': 'Protects against applicable fire/lava damage. It does not remove the burning timer or protect against every damage source.',
    'glowing': 'Makes the entity’s outline visible through blocks to observing players.',
    'haste': 'Speeds mining and attack animation. The registry attack-speed multiplier is 0.1 per level.',
    'health_boost': 'Raises the maximum-health attribute by 4 health points per level; increasing the maximum does not itself heal the entity.',
    'hero_of_the_village': 'Grants villager trade discounts and qualifies nearby players for profession-dependent villager gifts.',
    'hunger': 'Adds 0.005 times effect level to player food exhaustion each tick; it does not directly consume a food item.',
    'infested': 'On damage, a 10% random check can spawn 1–2 silverfish. Silverfish are ordinarily immune to this effect.',
    'instant_damage': 'Deals immediate magic damage, with intensity and level scaling. Undead-tag entities instead receive healing.',
    'instant_health': 'Heals immediately, with intensity and level scaling. Undead-tag entities instead take damage.',
    'invisibility': 'Makes the entity body invisible and reduces waypoint transmission; equipment and other visual elements can remain visible.',
    'jump_boost': 'Increases jump power and safe fall distance; the registry safe-fall-distance modifier adds 1 per level.',
    'levitation': 'Drives upward movement while active, except where the entity’s movement logic prevents it.',
    'luck': 'Raises the luck attribute, which changes selection in loot pools that use quality/luck, including eligible fishing loot.',
    'mining_fatigue': 'Slows mining and attack animation. The registry attack-speed multiplier decreases by 0.1 per level.',
    'nausea': 'Distorts the player’s view according to client accessibility settings; it does not directly deal damage.',
    'night_vision': 'Brightens the player’s view in darkness and alters underwater visibility.',
    'oozing': 'On removal with the KILLED reason, spawns up to two size-2 slimes, subject to nearby-slime/cramming checks. Slimes are ordinarily immune.',
    'poison': 'Periodically attempts 1 damage while health is above 1. Base interval is 25 ticks shifted right by the amplifier; high levels act every tick.',
    'raid_omen': 'After its 600-tick countdown, an eligible player’s saved omen position can start or extend a raid.',
    'regeneration': 'Periodically heals 1 health below maximum health. Base interval is 50 ticks shifted right by the amplifier; high levels act every tick.',
    'resistance': 'Reduces applicable incoming damage; bypass-resistance damage sources are unaffected.',
    'saturation': 'Instantly restores player food and saturation. Nonplayer living entities have no player food system.',
    'slow_falling': 'Reduces downward falling motion and prevents ordinary fall damage while active.',
    'slowness': 'The registry movement-speed multiplier decreases by 0.15 per level.',
    'speed': 'The registry movement-speed multiplier increases by 0.2 per level.',
    'strength': 'Adds 3 points to the attack-damage attribute per level.',
    'trial_omen': 'Lets an eligible detecting trial spawner become ominous. Its duration is 18000 ticks times the consumed Bad Omen level.',
    'unluck': 'Lowers the luck attribute, changing selection only in loot pools that use quality/luck.',
    'water_breathing': 'Prevents ordinary underwater air loss; it does not make the entity immune to all water-related damage.',
    'weakness': 'Subtracts 4 points from the attack-damage attribute per level and is required to initiate Zombie Villager curing.',
    'weaving': 'On a qualifying death, attempts to place 2–3 cobwebs on suitable nearby ground. Affected entities also bypass ordinary cobweb slowing.',
    'wind_charged': 'On removal with the KILLED reason, creates a wind burst with randomized power from 3 to below 5. It triggers wind-charge-style interactions; it does not create a collectible Wind Charge item.',
    'wither': 'Periodically attempts 1 Wither damage and can kill. Base interval is 40 ticks shifted right by the amplifier; high levels act every tick.',
}


def build_effects(game, version, mob_nodes):
    if version != '26.3':
        raise ValueError('Status interaction triggers must be audited for this game version')
    metadata = json.loads((ROOT / '.cache/effect-metadata.json').read_text(encoding='utf-8'))
    client_hash = hashlib.sha1(Path(game.jar.filename).read_bytes()).hexdigest()
    if metadata['version'] != version or metadata['clientSha1'] != client_hash:
        raise ValueError('Regenerate the effect metadata for this verified client')
    gathering = json.loads((ROOT / '.cache/gathering-metadata.json').read_text(encoding='utf-8'))
    language = json.loads(game.jar.read('assets/minecraft/lang/en_us.json'))
    bounds = {'minVersion': version, 'maxVersion': None}
    nodes, relationships, edges, capabilities = [], [], [], {}
    mob_ids = {node['id'] for node in mob_nodes}
    effect_ids = set(metadata['effects'])
    if {'minecraft:' + slug for slug in EFFECT_NOTES} != effect_ids:
        raise ValueError('Effect behavior audit does not cover the complete registry')
    icon_dir = ROOT / 'assets/effects'
    icon_dir.mkdir(exist_ok=True)

    def effect(identifier):
        identifier = identifier if ':' in identifier else 'minecraft:' + identifier
        if identifier not in effect_ids:
            raise ValueError(f'Unregistered status effect: {identifier}')
        return 'effect:' + identifier

    def mob(slug):
        identifier = 'mob:minecraft:' + slug
        if identifier not in mob_ids:
            raise ValueError(f'Unregistered mob: {slug}')
        return identifier

    def block(slug):
        identifier = 'minecraft:' + slug
        item = gathering['blockItems'][identifier]
        return item if item != 'minecraft:air' else 'block:' + identifier

    for identifier, value in metadata['effects'].items():
        slug = identifier.split(':', 1)[1]
        icon_path = 'assets/effects/' + slug + '.png'
        (ROOT / icon_path).write_bytes(game.jar.read('assets/minecraft/textures/mob_effect/' + slug + '.png'))
        nodes.append({'id': effect(identifier), 'name': language[value['descriptionId']], 'kind': 'effect',
                      'effectId': identifier, 'icon': icon_path, 'effectMetadata': value, 'note': EFFECT_NOTES[slug], **bounds})
    burning = 'effect:state:burning'
    with Image.open(BytesIO(game.jar.read('assets/minecraft/textures/block/fire_0.png'))) as source:
        source.convert('RGBA').crop((0, 0, source.width, source.width)).save(icon_dir / 'burning.png')
    nodes.append({'id': burning, 'name': 'Burning', 'kind': 'effect', 'effectId': None,
                  'icon': 'assets/effects/burning.png', 'state': 'on_fire',
                  'note': 'Entity state, not a registered Minecraft MobEffect. Fire Resistance prevents fire damage but does not clear the burning timer.', **bounds})
    known = set(game.items) | mob_ids | {node['id'] for node in nodes} | {'block:' + identifier for identifier, item in gathering['blockItems'].items() if item == 'minecraft:air'}

    def add(kind, sources, targets, identifier, note, *, source='vanilla_game_code', **fields):
        sources = list(dict.fromkeys(sources))
        targets = list(dict.fromkeys(targets))
        if not sources or not targets or set(sources + targets) - known:
            raise ValueError(f'Invalid effect relation endpoints: {identifier}: {sources} -> {targets}')
        relation_id = 'effects:' + identifier
        relationships.append({'id': relation_id, 'category': 'effects', 'type': kind,
            'name': fields.pop('name', kind.replace('_', ' ').title()),
            'inputs': [{'nodeId': item} for item in sources], 'outputs': [{'nodeId': item} for item in targets],
            'note': note, 'source': source, 'conditional': True, **bounds, **fields})
        for source_id in sources:
            for target_id in targets:
                edges.append({'id': relation_id + ':' + source_id + '>' + target_id, 'source': source_id,
                              'target': target_id, 'category': 'effects', 'type': kind, 'relationId': relation_id, **bounds})

    def actions(item, values, context, trigger, kind):
        for index, action in enumerate(values):
            identifier = f'{context}/{item}/{index}'
            action_type = action['type']
            fields = {'raw': action, 'trigger': trigger, 'probability': action.get('probability', 1), 'source': 'vanilla_item_component'}
            if action_type == 'minecraft:apply_effects':
                for subindex, instance in enumerate(action['effects']):
                    add(kind, [item], [effect(instance['id'])], identifier + '/' + str(subindex),
                        f'{trigger} applies this effect to the consumer if accepted by the entity. Probability is per use, not drop chance.',
                        effect=instance, **fields)
            elif action_type in ('minecraft:clear_all_effects', 'minecraft:remove_effects'):
                removed = sorted(effect_ids) if action_type == 'minecraft:clear_all_effects' else action['effects']
                if isinstance(removed, str):
                    removed = [removed]
                add('remove_effect', [item], [effect(value) for value in removed], identifier,
                    f'{trigger} removes active registered status effects. Burning is an entity state and is not cleared by milk or status-effect removal.', **fields)
            elif action_type not in ('minecraft:teleport_randomly', 'minecraft:play_sound'):
                raise ValueError(f'Unsupported default consume effect: {action_type}')

    for item, components in sorted(game.components.items()):
        consumable = components.get('minecraft:consumable')
        if 'minecraft:food' in components:
            capabilities[item] = {'food': components['minecraft:food'], 'playerConsumable': consumable is not None}
        if consumable is not None:
            capabilities.setdefault(item, {})['consumable'] = consumable
            actions(item, consumable.get('on_consume_effects', []), 'consume', 'Consuming this item', 'food_effect')
            remainder = components.get('minecraft:use_remainder')
            if remainder:
                add('consume_remainder', [item], [remainder['id']], 'remainder/' + item,
                    'After consuming a stack item, the empty container is returned according to the use_remainder component; creative inventory behavior can differ.',
                    source='vanilla_item_component', raw=remainder, results=[{'item': remainder['id'], 'count': remainder.get('count', 1)}])
        protection = components.get('minecraft:death_protection')
        if protection:
            actions(item, protection['death_effects'], 'death_protection', 'Activating held death protection against a qualifying lethal hit', 'death_protection')

    # Empty default potion contents have no effect. Every edge requires the named component value.
    for item in ('minecraft:potion', 'minecraft:splash_potion', 'minecraft:lingering_potion', 'minecraft:tipped_arrow'):
        scale = game.components[item].get('minecraft:potion_duration_scale', 1)
        for potion, instances in metadata['potions'].items():
            for index, instance in enumerate(instances):
                note = 'Requires potion_contents.potion=' + potion + '. Plain water, awkward, mundane and thick variants have no status effects. '
                if item == 'minecraft:splash_potion':
                    note += 'A splash applies effects to eligible nearby entities, scaled by impact distance; a direct hit has full strength. Short noninstant effects may be discarded.'
                elif item == 'minecraft:lingering_potion':
                    note += 'Entering its area cloud applies effects repeatedly while the cloud persists. Noninstant duration uses this item’s potion_duration_scale; instantaneous strength uses the cloud factor.'
                elif item == 'minecraft:tipped_arrow':
                    note += 'A successful arrow hit applies scaled effects to an eligible living target; instantaneous effects retain their special behavior.'
                else:
                    note += 'Drinking applies these effects to the consumer.'
                add('arrow_effect' if item.endswith('tipped_arrow') else 'potion_effect', [item], [effect(instance['id'])],
                    f'potion/{item}/{potion}/{index}', note, source='vanilla_potion_registry',
                    requiredComponents={'minecraft:potion_contents': {'potion': potion}}, effect=instance,
                    durationScale=scale, applicationDurationTicks=max(1, int(instance['duration'] * scale)),
                    instantaneous=metadata['effects'][instance['id']]['instantaneous'])

    for flower, instances in sorted(gathering['suspiciousStewIngredients'].items()):
        for index, instance in enumerate(instances):
            add('food_effect', ['minecraft:suspicious_stew'], [effect(instance['id'])], f'stew/{flower}/{index}',
                'This stew must carry the suspicious_stew_effects component produced using this flower. An empty default stew has no effects; loot/trade stew components can differ.',
                source='vanilla_suspicious_effect_holder', effect=instance, flower=flower,
                requiredComponents={'minecraft:suspicious_stew_effects': [instance]})
            add('stew_ingredient_effect', [flower], [effect(instance['id'])], f'stew_ingredient/{flower}/{index}',
                'Using this flower to craft Suspicious Stew or feeding it to a brown mooshroom selects this stew effect. The flower alone does not apply the effect.',
                source='vanilla_suspicious_effect_holder', effect=instance)

    add('ominous_effect', ['minecraft:ominous_bottle'], [effect('bad_omen')], 'ominous_bottle',
        'Drinking applies Bad Omen for 120000 ticks. Its level is ominous_bottle_amplifier + 1; default amplifier is zero.',
        effect={'id': 'minecraft:bad_omen', 'duration': 120000, 'amplifierFromComponent': 'minecraft:ominous_bottle_amplifier'},
        code='OminousBottleAmplifier.onConsume')
    add('effect_conversion', [effect('bad_omen')], [effect('raid_omen')], 'raid_omen',
        'A nonspectator player with Bad Omen entering a village outside Peaceful converts it to Raid Omen; an existing raid already at its omen cap prevents conversion. Village geometry remains a condition, not a node.',
        durationTicks=600, amplifier='preserved from Bad Omen', code='BadOmenMobEffect.applyEffectTick')
    add('effect_conversion', [effect('bad_omen'), 'minecraft:trial_spawner'], [effect('trial_omen')], 'trial_omen',
        'A detecting trial spawner consumes the player’s Bad Omen and grants Trial Omen when becoming ominous. This is an omen interaction, not a claim that this spawner produces arbitrary mobs.',
        durationTicks='18000 * (Bad Omen amplifier + 1)', code='TrialSpawnerStateData.transformBadOmenIntoTrialOmen')

    for tier, values in enumerate(metadata['beaconTiers'], 1):
        for value in values:
            add('beacon_effect', ['minecraft:beacon'], [effect(value)], 'beacon/' + value,
                'An active beacon with an unobstructed beam and valid mineral pyramid grants the selected effect to nearby players. Primary effects unlock at this pyramid tier; Regeneration is the tier-four secondary option. At tier four a selected primary may instead be upgraded to level II.',
                minimumPyramidLevels=tier, secondary=value == 'minecraft:regeneration', durationTicks='(9 + 2 * pyramid levels) * 20',
                radiusBlocks='10 + 10 * pyramid levels', code='BeaconBlockEntity.BEACON_EFFECTS/applyEffects')
    for source, status, ticks, note in [
        ('conduit', 'conduit_power', 260, 'Active conduit with at least 16 valid frame blocks grants wet players Conduit Power; radius is floor(frame blocks / 7) * 16, with range/height checks.'),
        ('bell', 'glowing', 60, 'A resonating bell reveals nearby raiders accepted by the raid entity tag and its distance checks; other mobs do not receive Glowing from it.'),
        ('sculk_shrieker', 'darkness', 260, 'A triggered naturally capable sculk shrieker applies Darkness to nearby eligible players via Warden.applyDarknessAround.'),
        ('potent_sulfur', 'nausea', 80, 'Noxious gas from this block affects nearby living nonspectators only if the gas path can reach their eye position.'),
        ('wither_rose', 'wither', 40, 'Contact with the planted flower applies Wither outside Peaceful to a susceptible living entity; wither-damage immunity prevents it.'),
    ]:
        add('block_contact_effect', [block(source)], [effect(status)], 'block/' + source, note,
            effect={'id': 'minecraft:' + status, 'duration': ticks, 'amplifier': 0})
    for flower in ('open_eyeblossom', 'closed_eyeblossom'):
        add('block_contact_effect', [flower if ':' in flower else 'minecraft:' + flower], [effect('poison')], 'eyeblossom/' + flower,
            'When the planted eyeblossom attracts bees, a touching bee without existing Poison receives this effect. Attraction depends on the open/closed flower state.',
            effect={'id': 'minecraft:poison', 'duration': 25}, targetEntity='minecraft:bee', code='EyeblossomBlock.entityInside')

    for slug, status, fields, note in [
        ('husk', 'hunger', {'durationTicks': '140 * floor(local effective difficulty)'}, 'A successful unarmed husk melee hit against a living target applies Hunger; a held weapon suppresses this special effect.'),
        ('bee', 'poison', {'durationByDifficulty': {'normal': 200, 'hard': 360}}, 'A successful sting applies Poison in Normal/Hard; Easy applies no poison.'),
        ('cave_spider', 'poison', {'durationByDifficulty': {'normal': 140, 'hard': 300}}, 'A successful cave spider melee hit applies Poison in Normal/Hard; Easy applies no poison.'),
        ('pufferfish', 'poison', {'durationTicks': '60 * puff state'}, 'Contact with a puffed pufferfish that successfully damages an eligible living target applies Poison; an unpuffed fish does not.'),
        ('wither_skeleton', 'wither', {'durationTicks': 200}, 'A successful wither skeleton melee hit applies Wither to a susceptible living target.'),
        ('wither', 'wither', {'durationByDifficulty': {'normal': 200, 'hard': 800}, 'amplifier': 1}, 'A successful Wither skull projectile hit applies Wither II in Normal/Hard; Easy applies no status effect.'),
        ('shulker', 'levitation', {'durationTicks': 200}, 'A successful shulker bullet hit applies Levitation to a susceptible living target.'),
        ('illusioner', 'blindness', {'durationTicks': 400}, 'An illusioner blindness spell applies Blindness to its target when its spell/local difficulty checks allow it.'),
    ]:
        add('mob_attack_effect', [mob(slug)], [effect(status)], 'attack/' + slug, note, **fields)
    for slug, status, ticks, note in [
        ('warden', 'darkness', 260, 'A nearby warden applies Darkness every 120 ticks to eligible players within 20 blocks.'),
        ('dolphin', 'dolphins_grace', 100, 'A dolphin swimming alongside a player grants and refreshes Dolphin’s Grace; swimming and distance AI checks apply.'),
        ('elder_guardian', 'mining_fatigue', 6000, 'An elder guardian checks players within 50 blocks every 1200 ticks and applies Mining Fatigue III when their current effect is weaker or nearly expired.'),
        ('nautilus', 'breath_of_the_nautilus', 60, 'Riding this nautilus grants Breath of the Nautilus, refreshing it every 40 ticks.'),
        ('zombie_nautilus', 'breath_of_the_nautilus', 60, 'Riding this zombie nautilus grants Breath of the Nautilus, refreshing it every 40 ticks.'),
        ('illusioner', 'invisibility', 1200, 'An illusioner’s mirror spell applies Invisibility to itself.'),
        ('axolotl', 'regeneration', 100, 'A player helping an axolotl kill its aquatic opponent gains Regeneration I; each support adds 100 ticks up to 2400 ticks.'),
    ]:
        add('mob_aura_effect', [mob(slug)], [effect(status)], 'aura/' + slug + '/' + status, note,
            durationTicks=ticks, amplifier=2 if slug == 'elder_guardian' else 0)
    add('mob_self_effect', [mob('axolotl')], [effect('regeneration')], 'axolotl_play_dead',
        'An axolotl that enters its playing-dead behavior applies Regeneration to itself.', durationTicks=200, code='PlayDead.start')
    for status, weight in [('speed', 2), ('strength', 1), ('regeneration', 1), ('invisibility', 1)]:
        add('mob_self_effect', [mob('spider')], [effect(status)], 'spider_spawn/' + status,
            'A Hard-difficulty spider spawn group can acquire one permanent effect. Group selection probability is 0.1 times local special difficulty multiplier; Speed has weight 2 and the other choices weight 1.',
            durationTicks=-1, conditionalSelectionWeight=weight, totalSelectionWeight=5,
            code='Spider.finalizeSpawn/SpiderEffectsGroupData.setRandomEffect')
    for slug in ('zoglin', 'zombified_piglin'):
        add('mob_self_effect', [mob(slug)], [effect('nausea')], 'zombification_nausea/' + slug,
            'The newly converted mob receives Nausea after Hoglin/Piglin zombification; an already existing mob does not receive it merely by being this type.',
            durationTicks=200, code='Hoglin.finishConversion / AbstractPiglin.finishConversion')
    for attack, amplifier in [('perched_breath', 0), ('fireball_cloud', 1)]:
        add('mob_attack_effect', [mob('ender_dragon')], [effect('instant_damage')], 'dragon/' + attack,
            'The dragon’s ' + attack.replace('_', ' ') + ' creates an area effect cloud applying Instant Damage. Cloud instantaneous-effect intensity is 0.5; its reapplication and radius checks apply.',
            amplifier=amplifier, instantaneousIntensity=.5, code='DragonSittingFlamingPhase / DragonFireball')
    add('remove_effect', [mob('axolotl')], [effect('mining_fatigue')], 'axolotl_support_remove',
        'When the player receives supporting effects after helping the axolotl kill its aquatic opponent, the axolotl removes the player’s Mining Fatigue.', code='Axolotl.applySupportingEffects')
    for slug, status, duration in [('stray', 'slowness', 600), ('bogged', 'poison', 100), ('parched', 'weakness', 600)]:
        instance = {'id': 'minecraft:' + status, 'duration': duration, 'amplifier': 0}
        add('mob_projectile_effect', [mob(slug)], ['minecraft:arrow'], 'mob_arrow/' + slug,
            'This mob shoots an arrow carrying this custom effect. Duration is supplied by the mob’s arrow construction, not the generic brewing potion duration.',
            producedComponents={'minecraft:potion_contents': {'custom_effects': [instance]}, 'minecraft:potion_duration_scale': 1}, code=slug + '.getArrow')
        add('arrow_effect', ['minecraft:arrow'], [effect(status)], 'mob_arrow_effect/' + slug,
            'A successful hit from the arrow carrying this mob-supplied custom effect applies it at this duration. This predicate is distinct from a brewed arrow’s potion field.',
            requiredComponents={'minecraft:potion_contents': {'custom_effects': [instance]}, 'minecraft:potion_duration_scale': 1}, effect=instance,
            applicationDurationTicks=duration, provenanceMob='minecraft:' + slug)
    add('arrow_effect', ['minecraft:spectral_arrow'], [effect('glowing')], 'spectral_arrow',
        'A successful spectral arrow hit applies Glowing for 200 ticks to a susceptible living target.', durationTicks=200, code='SpectralArrow.doPostHurtEffects')

    _add_witch(add, effect, mob)
    add('cure_zombie_villager', [mob('zombie_villager'), 'minecraft:golden_apple', effect('weakness')], [mob('villager')], 'zombie_villager_cure',
        'Use an ordinary Golden Apple on a Zombie Villager that currently has Weakness. It consumes one apple, removes Weakness, starts curing for 3600–6000 ticks, and eventually converts to a Villager. Nearby iron bars and beds can accelerate curing. Healing potion and enchanted golden apple do not initiate this cure.',
        conditions=['Zombie Villager has Weakness', 'use ordinary golden apple'],
        ingredients=[{'items': ['minecraft:golden_apple'], 'count': 1}], cureDurationTicks={'min': 3600, 'max': 6000},
        code='ZombieVillager.mobInteract/startConverting/finishConversion')
    add('mob_self_effect', [mob('zombie_villager')], [effect('strength')], 'curing_strength',
        'Starting the Golden Apple and Weakness cure removes Weakness and applies Strength to the converting Zombie Villager for the chosen conversion time.',
        durationTicks='selected cure duration', code='ZombieVillager.startConverting')
    add('mob_self_effect', [mob('villager')], [effect('nausea')], 'cured_villager_nausea',
        'The Villager created when Zombie Villager curing finishes receives Nausea for 200 ticks.', durationTicks=200, code='ZombieVillager.finishConversion')

    add('effect_spawn', [effect('oozing')], [mob('slime')], 'oozing_slime',
        'An entity carrying Oozing spawns up to two size-2 slimes when removed with the KILLED reason. Nearby-slime/maxEntityCramming checks can reduce the count. Slimes cannot normally acquire Oozing.',
        trigger='onMobRemoved: KILLED', count={'max': 2}, spawnedSize=2, code='OozingMobEffect.onMobRemoved')
    add('effect_spawn', [effect('infested')], [mob('silverfish')], 'infested_silverfish',
        'An Infested entity taking damage has a 10% chance to spawn 1–2 silverfish. Silverfish cannot normally acquire Infested.',
        trigger='onMobHurt', probability=.1, count={'min': 1, 'max': 2}, code='InfestedMobEffect.onMobHurt')
    add('effect_world_change', [effect('weaving')], ['minecraft:cobweb'], 'weaving_cobweb',
        'On removal with KILLED reason, attempts to place 2–3 cobwebs nearby on replaceable positions with sturdy ground. For nonplayers mobGriefing must be enabled; available positions can reduce the actual count.',
        count={'minAttempted': 2, 'maxAttempted': 3}, code='WeavingMobEffect.onMobRemoved/spawnCobwebsRandomlyAround')
    add('effect_interaction', [effect('weaving')], ['minecraft:cobweb'], 'weaving_bypass_web',
        'An entity with Weaving does not undergo the ordinary cobweb stuck-in-block slowing.', code='WebBlock.entityInside')
    add('effect_interaction', [effect('hero_of_the_village')], [mob('villager')], 'hero_villager',
        'This player effect qualifies the player for villager gifts and trade discounts; profession, cooldown and distance checks still apply.',
        code='Villager.updateSpecialPrices/GiveGiftToHero')
    for status in ('luck', 'unluck'):
        add('effect_interaction', [effect(status)], ['minecraft:fishing_rod'], 'fishing_luck/' + status,
            'This effect changes the fisher’s luck attribute. Only fishing loot pools that use entry quality/luck change selection; this does not alter every possible loot source.',
            code='FishingHook / LootPool / LivingEntity luck attribute')

    _add_immunities(game, metadata, add, effect, mob, mob_ids)
    _add_burning(game, metadata, add, effect, block, mob, mob_ids, burning)
    relation_ids = {record['id'] for record in relationships}
    if len(relation_ids) != len(relationships) or len({edge['id'] for edge in edges}) != len(edges):
        raise ValueError('Duplicate status relation identifiers')
    return {'nodes': nodes, 'relationships': relationships, 'edges': edges,
            'coverage': {'registeredEffects': len(effect_ids), 'entityStates': 1, 'potionTypes': len(metadata['potions']),
                         'foodItems': sum('minecraft:food' in value for value in game.components.values()),
                         'consumableItems': sum('consumable' in value for value in capabilities.values()), 'itemCapabilities': capabilities,
                         'sources': ['verified MobEffect and Potion registries', 'default item components', '26.3 game-code trigger audit'],
                         'limits': ['Registered item IDs remain nodes; potion and stew variants are explicit component predicates.',
                                    'Status effect application respects entity immunity, difficulty and other trigger conditions.',
                                    'Custom command/datapack item components and arbitrary equipped enchanted gear are not enumerated.',
                                    'Nutrition and attributes are node metadata; players, damage types and attributes are not additional nodes.']}}


def _add_witch(add, effect, mob):
    choices = [
        ('healing', 'Raider ally target has at most 4 health.'),
        ('regeneration', 'Raider ally target has more than 4 health.'),
        ('slowness', 'Enemy is at least 8 horizontal blocks away and has no Slowness; checked before Poison.'),
        ('poison', 'Enemy did not match Slowness branch, has at least 8 health and no Poison; checked before Weakness.'),
        ('weakness', 'Enemy did not match earlier branches, is within 3 horizontal blocks, has no Weakness, and the 25% random check succeeds.'),
        ('harming', 'Enemy did not match any earlier conditional branch; default offensive potion.'),
    ]
    for potion, condition in choices:
        add('witch_potion', [mob('witch')], ['minecraft:splash_potion'], 'witch/throw/' + potion,
            'A witch that is not drinking throws this splash potion according to its ordered target-selection branches. ' + condition,
            action='throws', producedComponents={'minecraft:potion_contents': {'potion': 'minecraft:' + potion}},
            conditions=[condition], code='Witch.performRangedAttack')
    for potion, condition in [
        ('water_breathing', '15% check while underwater and lacking Water Breathing.'),
        ('fire_resistance', 'Earlier branch failed; 15% check while on fire or recently damaged by fire, lacking Fire Resistance.'),
        ('healing', 'Earlier branches failed; 5% check while below maximum health.'),
        ('swiftness', 'Earlier branches failed; 50% check while a target is more than 11 blocks away and lacking Speed.'),
    ]:
        add('witch_potion', [mob('witch')], ['minecraft:potion'], 'witch/drink/' + potion,
            'A witch may equip and drink this potion while not already drinking. The potion then supplies its own effect through the potion-content relation. ' + condition,
            action='drinks', requiredComponents={'minecraft:potion_contents': {'potion': 'minecraft:' + potion}},
            conditions=[condition], code='Witch.aiStep')


def _add_immunities(game, metadata, add, effect, mob, mob_ids):
    reviewed = {'net.minecraft.world.entity.LivingEntity', 'net.minecraft.world.entity.animal.nautilus.AbstractNautilus',
                'net.minecraft.world.entity.boss.wither.WitherBoss', 'net.minecraft.world.entity.monster.skeleton.Parched',
                'net.minecraft.world.entity.monster.skeleton.WitherSkeleton', 'net.minecraft.world.entity.monster.spider.Spider'}
    if set(metadata['entityEffectMethods']) != {identifier.removeprefix('mob:') for identifier in mob_ids}:
        raise ValueError('Effect method export does not cover every mob')
    for identifier, methods in metadata['entityEffectMethods'].items():
        if methods['canBeAffected'] not in reviewed or methods['addEffect'] not in {
                'net.minecraft.world.entity.LivingEntity', 'net.minecraft.world.entity.boss.enderdragon.EnderDragon',
                'net.minecraft.world.entity.boss.wither.WitherBoss'}:
            raise ValueError('Unreviewed mob effect-application override: ' + identifier)
    for slug, code in [('ender_dragon', 'EnderDragon.addEffect'), ('wither', 'WitherBoss.addEffect')]:
        add('effect_immunity', [effect(identifier) for identifier, value in sorted(metadata['effects'].items()) if not value['instantaneous']],
            [mob(slug)], 'boss_status_immunity/' + slug,
            'This boss overrides ordinary addEffect to reject persistent status-effect application. Instantaneous magic damage/healing has separate entity/damage rules.', code=code)
    def entity_tag(tag, visiting=()):
        if tag in visiting:
            raise ValueError('Cyclic entity tag: ' + tag)
        namespace, slug = tag.split(':', 1)
        result = set()
        for value in json.loads(game.jar.read(f'data/{namespace}/tags/entity_type/{slug}.json'))['values']:
            value = value['id'] if isinstance(value, dict) else value
            result.update(entity_tag(value[1:], visiting + (tag,)) if value.startswith('#') else [value])
        return result
    immune = set()
    for tag, effects in [('immune_to_infested', ['infested']), ('immune_to_oozing', ['oozing']),
                         ('ignores_poison_and_regen', ['poison', 'regeneration'])]:
        for entity in entity_tag('minecraft:' + tag):
            for status in effects:
                immune.add((entity, status, tag))
    for slug, effects in [('spider', ['poison']), ('cave_spider', ['poison']), ('nautilus', ['poison']),
                         ('zombie_nautilus', ['poison']), ('wither', ['wither']), ('wither_skeleton', ['wither']), ('parched', ['weakness'])]:
        for status in effects:
            immune.add(('minecraft:' + slug, status, 'canBeAffected override'))
    rules = {}
    for entity, status, source in sorted(immune):
        rules.setdefault((entity, status), []).append(source)
    for (entity, status), sources in sorted(rules.items()):
        if 'mob:' + entity in mob_ids:
            add('effect_immunity', [effect(status)], ['mob:' + entity], f'immunity/{entity}/{status}',
                'This mob rejects ordinary application of this status effect; the edge means immunity rather than acquisition.',
                source='vanilla_entity_tag_and_game_code', rules=sources)
    for entity in sorted(entity_tag('minecraft:inverted_healing_and_harm')):
        if 'mob:' + entity in mob_ids:
            add('effect_inversion', [effect('instant_health'), effect('instant_damage')], ['mob:' + entity], 'inversion/' + entity,
                'This entity inverts instant healing/harming: Instant Health damages it, and Instant Damage heals it.',
                source='vanilla_entity_tag', rule='minecraft:inverted_healing_and_harm')
    for item in sorted(game.resolve_tag('minecraft:parrot_poisonous_food')):
        add('mob_food_effect', [item, mob('parrot')], [effect('poison')], 'parrot_poison/' + item,
            'Feeding a parrot this poisonous-food-tag item applies Poison for 900 ticks. A 3.4e38 player-attack damage hit is also attempted when the feeder is creative or the parrot is not invulnerable. This is not a taming food.',
            durationTicks=900, source='vanilla_item_tag_and_game_code', code='Parrot.mobInteract')


def _add_burning(game, metadata, add, effect, block, mob, mob_ids, burning):
    for slug, note in [('fire', 'Contact with ordinary fire accumulates ignition and sets a susceptible entity on fire.'),
                       ('soul_fire', 'Contact with soul fire accumulates ignition and sets a susceptible entity on fire.'),
                       ('lava', 'Contact with lava ignites a susceptible entity and also deals direct lava damage.')]:
        add('ignite', [block(slug)], [burning], 'ignite/' + slug, note,
            code='BaseFireBlock.entityInside / Entity.lavaHurt')
    add('ignite', ['minecraft:lava_bucket'], [burning], 'ignite/lava_bucket',
        'Placing the contained lava can ignite entities that touch it. Holding or drinking a lava bucket is not an ignition action.')
    add('ignite', [mob('blaze')], [burning], 'blaze_fireball',
        'A successful small-fireball hit from a Blaze ignites its susceptible victim for 5 seconds; if the damage attempt fails the original fire timer is restored.',
        durationTicks=100, code='SmallFireball.onHitEntity')
    add('ignite', ['minecraft:fire_charge'], [burning], 'fire_charge_projectile',
        'A fire charge dispensed as a small fireball can ignite a successfully damaged target. Hand use instead places fire, which has its own contact relation.',
        durationTicks=100, code='SmallFireball.onHitEntity / DispenseItemBehavior')
    add('ignite', ['minecraft:arrow'], [burning], 'burning_arrow',
        'An arrow projectile that is already on fire can ignite its successfully damaged hit target for 5 seconds; a failed hit restores the original fire timer. An ordinary unlit arrow does not do this.',
        conditions=['arrow projectile is on fire', 'damage attempt succeeds'], durationTicks=100, code='AbstractArrow.onHitEntity')
    for enchantment in ('fire_aspect', 'flame'):
        definition = json.loads(game.jar.read('data/minecraft/enchantment/' + enchantment + '.json'))
        supported = definition['supported_items']
        if not isinstance(supported, str) or not supported.startswith('#'):
            raise ValueError('Unexpected ignition enchantment item set: ' + enchantment)
        for item in sorted(game.resolve_tag(supported[1:])):
            add('ignite', [item], [burning], 'enchanted_ignite/' + enchantment + '/' + item,
                'Requires the ' + enchantment.replace('_', ' ').title() + ' enchantment. '
                + ('Direct attacks can ignite the victim for 4 seconds per enchantment level.' if enchantment == 'fire_aspect'
                   else 'The fired projectile is ignited for 100 seconds; its successful hit can ignite the victim under the arrow’s own rules.'),
                requiredComponents={'minecraft:enchantments': {'minecraft:' + enchantment: {'min': 1}}},
                source='vanilla_enchantment_json', raw=definition['effects'])
    for entity in metadata['fireImmuneEntities']:
        if 'mob:' + entity in mob_ids:
            add('effect_immunity', [burning], ['mob:' + entity], 'fire_immune/' + entity,
                'This entity type is fire-immune. Ordinary fire/lava damage and persistent burning are blocked by its entity fire immunity rules.',
                source='vanilla_entity_registry', code='EntityType.fireImmune / Entity.baseTick')
    for slug in ('zombie', 'husk', 'drowned', 'zombie_villager'):
        add('ignite', [mob(slug)], [burning], 'burning_zombie/' + slug,
            'A successful unarmed melee hit by an already-burning Zombie-family mob can ignite its victim. Chance is 0.3 times local effective difficulty, and duration is 2 times its floored value in seconds.',
            probability='0.3 * local effective difficulty', durationTicks='40 * floor(local effective difficulty)', code='Zombie.doHurtTarget')
    add('effect_protection', [effect('fire_resistance')], [burning], 'fire_resistance',
        'Fire Resistance prevents fire/lava/hot-floor damage accepted by its damage-type rule. It does not clear the entity’s burning timer.',
        code='LivingEntity.isInvulnerableTo / DamageTypeTags.IS_FIRE')
    for slug in ('water', 'powder_snow'):
        add('extinguish', [block(slug)], [burning], 'extinguish/' + slug,
            'Entity contact with this block/fluid can extinguish the active burning state; dimension-specific water placement and block-state restrictions apply.')
    for item in ('minecraft:water_bucket', 'minecraft:powder_snow_bucket'):
        add('extinguish', [item], [burning], 'extinguish/' + item,
            'Placing the bucket contents can extinguish a burning entity that contacts them.')
    for item in ('minecraft:splash_potion', 'minecraft:lingering_potion'):
        add('extinguish', [item], [burning], 'extinguish/water/' + item,
            'A thrown water variant extinguishes nearby burning eligible entities at impact; nonwater variants do not provide this water action.',
            requiredComponents={'minecraft:potion_contents': {'potion': 'minecraft:water'}},
            source='vanilla_potion_tag_and_game_code', potionTag='minecraft:extinguishes_entities', code='AbstractThrownPotion.applyEntityEffects')
    for content in ('water', 'powder_snow'):
        add('extinguish', ['minecraft:cauldron'], [burning], 'extinguish/cauldron/' + content,
            'Contact with a cauldron filled with ' + content.replace('_', ' ') + ' extinguishes a burning entity. The on-fire interaction consumes a level; powder snow becomes the corresponding water-cauldron state.',
            requiredBlock='minecraft:' + content + '_cauldron', code='LayeredCauldronBlock.entityInside/handleEntityOnFireInside')
    add('ignite', ['minecraft:cauldron'], [burning], 'ignite/lava_cauldron',
        'Contact with the contents of a lava-filled cauldron can ignite and deal lava damage to a susceptible entity. An empty cauldron does not.',
        requiredBlock='minecraft:lava_cauldron', code='LavaCauldronBlock.entityInside')
