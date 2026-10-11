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
