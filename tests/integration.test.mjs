import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { validateGraph, filterGraph, groupEdges } from '../core.mjs';

test('the shipped dataset keeps every item, recipe and edge and has complete artwork', () => {
  const graph = validateGraph(JSON.parse(readFileSync(new URL('../data/graph.json', import.meta.url))));
  const provenance = JSON.parse(readFileSync(new URL('../data/provenance.json', import.meta.url)));
  const artwork = JSON.parse(readFileSync(new URL('../assets/icon-coverage.json', import.meta.url)));
  const types = new Set(graph.edges.map(edge => edge.type));
  const visible = filterGraph(graph, graph.version, types);
  assert.equal(visible.nodes.length, provenance.counts.nodes);
  assert.equal(visible.recipes.length, provenance.counts.recipes);
  assert.equal(visible.edges.length, provenance.counts.edges);
  assert.equal(groupEdges(visible.edges).reduce((sum, group) => sum + group.edges.length, 0), graph.edges.length);
  assert.deepEqual(new Set(Object.keys(artwork.items)), new Set(graph.nodes.filter(node => node.kind === 'item').map(node => node.id)));
  for (const node of graph.nodes) assert.ok(existsSync(new URL('../' + node.icon, import.meta.url)), node.id);
  for (const id of ['minecraft:bedrock', 'minecraft:command_block', 'minecraft:light']) {
    assert.ok(visible.nodes.some(node => node.id === id));
    assert.ok(!visible.edges.some(edge => edge.category === 'recipe' && (edge.source === id || edge.target === id)));
  }
  assert.equal(graph.counts.itemRecipeEdges, 25594, 'all original item recipe connections survive');
  const connected = (source, target, type) => graph.edges.some(edge => edge.source === source && edge.target === target && edge.type === type);
  assert.ok(connected('minecraft:oak_planks', 'tag:minecraft:planks', 'belongs_to'));
  assert.ok(connected('tag:minecraft:planks', 'minecraft:crafting_table', 'crafting_shaped'));
  assert.ok(connected('minecraft:wheat_seeds', 'minecraft:bone_meal', 'composting'));
  assert.ok(connected('mob:minecraft:skeleton', 'minecraft:bone', 'mob_drop'));
  assert.ok(connected('mob:minecraft:witch', 'minecraft:sugar', 'mob_drop'));
  assert.ok(connected('minecraft:beehive', 'minecraft:honey_bottle', 'honey_harvesting'));
  for (const [source, target, type] of [
    ['minecraft:skeleton_spawn_egg', 'mob:minecraft:skeleton', 'spawn_egg'],
    ['minecraft:cod_bucket', 'mob:minecraft:cod', 'bucket_release'],
    ['minecraft:ender_pearl', 'mob:minecraft:endermite', 'ender_pearl_spawn'],
    ['minecraft:iron_block', 'mob:minecraft:iron_golem', 'mob_building'],
    ['minecraft:shears', 'mob:minecraft:sheep', 'shearing_tool'],
    ['minecraft:shears', 'minecraft:beehive', 'harvesting_tool'],
    ['minecraft:glass_bottle', 'minecraft:beehive', 'harvesting_tool'],
    ['minecraft:campfire', 'minecraft:beehive', 'smoking_bees'],
    ['minecraft:hay_block', 'minecraft:campfire', 'campfire_smoke'],
    ['minecraft:wooden_shovel', 'minecraft:campfire', 'extinguishing'],
    ['minecraft:blue_dye', 'mob:minecraft:sheep', 'dyeing'],
    ['minecraft:wheat', 'mob:minecraft:sheep', 'feeding'],
    ['minecraft:wheat_seeds', 'mob:minecraft:chicken', 'feeding'],
    ['minecraft:rotten_flesh', 'effect:minecraft:hunger', 'food_effect'],
    ['mob:minecraft:husk', 'effect:minecraft:hunger', 'mob_attack_effect'],
    ['minecraft:potion', 'effect:minecraft:jump_boost', 'potion_effect'],
    ['minecraft:beacon', 'effect:minecraft:jump_boost', 'beacon_effect'],
    ['effect:minecraft:oozing', 'mob:minecraft:slime', 'effect_spawn'],
    ['effect:minecraft:infested', 'mob:minecraft:silverfish', 'effect_spawn'],
    ['effect:minecraft:weakness', 'mob:minecraft:villager', 'cure_zombie_villager'],
  ]) assert.ok(connected(source, target, type), `${source} → ${target} (${type})`);
  assert.equal(graph.nodes.filter(node => node.kind === 'effect' && node.effectId).length, 40);
  assert.ok(graph.nodes.some(node => node.id === 'effect:state:burning'));
  assert.ok(!graph.edges.some(edge => ['minecraft:spawner', 'minecraft:trial_spawner'].includes(edge.source) && edge.target.startsWith('mob:')));
  assert.ok(!graph.edges.some(edge => edge.source === 'minecraft:potion' && edge.target === 'mob:minecraft:slime'));
  assert.ok(!graph.edges.some(edge => edge.source === 'mob:minecraft:witch' && edge.target.startsWith('effect:')));
  for (const id of ['minecraft:bread', 'minecraft:diamond_chestplate', 'minecraft:stone']) {
    assert.ok(graph.nodes.find(node => node.id === id).capabilities, id);
  }
  assert.equal(graph.nodes.find(node => node.id === 'minecraft:cod_bucket').capabilities.playerConsumable, false);
  assert.equal(graph.nodes.find(node => node.id === 'minecraft:bread').capabilities.playerConsumable, true);
  const noRelationships = filterGraph(graph, graph.version, new Set());
  assert.equal(noRelationships.nodes.length, graph.nodes.length);
  assert.equal(noRelationships.edges.length, 0);
});

test('world generation keeps structure contents and dimension membership on separate hops', () => {
  const graph = validateGraph(JSON.parse(readFileSync(new URL('../data/graph.json', import.meta.url))));
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const connected = (source, target, type) => graph.edges.some(edge => edge.source === source && edge.target === target && edge.type === type);
  assert.equal(graph.coverage.structures.registeredStructures, 52);
  assert.equal(graph.counts.structures, graph.coverage.structures.registeredStructures + graph.coverage.structures.featureStructures + graph.coverage.structures.runtimeSites.length);
  assert.ok(graph.counts.biomes >= 67);
  assert.equal(graph.counts.dimensions, 3);
  for (const relation of graph.relationships.filter(record => record.contextRef)) {
    const { nodeId, lootTable } = relation.contextRef;
    assert.ok(nodes.get(nodeId)?.lootContexts?.[lootTable]?.length, relation.id);
    assert.equal(lootTable, relation.sourceLootTable);
  }
  for (const edge of graph.edges) {
    assert.ok(!(nodes.get(edge.source).kind === 'structure' && nodes.get(edge.target).kind === 'dimension'), edge.id);
    if (edge.type === 'biome_dimension') {
      assert.equal(nodes.get(edge.source).kind, 'biome');
      assert.equal(nodes.get(edge.target).kind, 'dimension');
    }
  }
  assert.ok(connected('structure:minecraft:fortress', 'biome:minecraft:nether_wastes', 'structure_biome'));
  assert.ok(connected('biome:minecraft:nether_wastes', 'dimension:minecraft:the_nether', 'biome_dimension'));
  assert.ok(connected('structure:minecraft:end_city', 'minecraft:purpur_block', 'structure_block'));
  assert.ok(!graph.edges.some(edge => edge.type === 'biome_block' && edge.target === 'minecraft:purpur_block'));
  assert.ok(connected('structure:minecraft:desert_pyramid', 'minecraft:cut_sandstone', 'structure_block'));
  assert.ok(!connected('biome:minecraft:desert', 'minecraft:cut_sandstone', 'biome_block'));
  assert.ok(connected('structure:minecraft:fortress', 'mob:minecraft:blaze', 'structure_spawner_mob'));
  assert.ok(connected('structure:minecraft:fortress', 'mob:minecraft:blaze', 'structure_spawn_mob'));
  assert.ok(connected('structure:minecraft:swamp_hut', 'mob:minecraft:witch', 'structure_generated_mob'));
  assert.ok(connected('structure:minecraft:buried_treasure', 'minecraft:heart_of_the_sea', 'structure_loot'));
  assert.ok(connected('structure:minecraft:ancient_city', 'minecraft:sculk_shrieker', 'structure_block'));
  assert.ok(connected('minecraft:sculk_shrieker', 'mob:minecraft:warden', 'mob_summoning'));
  assert.ok(!connected('structure:minecraft:ancient_city', 'mob:minecraft:warden', 'structure_generated_mob'));
});
