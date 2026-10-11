import assert from 'node:assert/strict';
import { compareVersions, availableAt, validateGraph, filterGraph, groupEdges, indexGraph, layoutGraph, viewLayers, pickEdge, relationshipPath, nodeKind, nodeBoundaryDistance, nodeContainsPoint, STRUCTURE_CORNER_RATIO, filterKey } from '../core.mjs';

assert.equal(compareVersions('1.21.10', '1.21.9'), 1);
assert.equal(compareVersions('26.3', '1.21.11'), 1);
assert.equal(compareVersions('26.3', '26.3.0'), 0);
assert.equal(compareVersions('26.3-pre-1', '26.3'), -1);
assert.throws(() => compareVersions('broken', '26.3'));
const bounds = { minVersion: '1.21.9', maxVersion: '26.3' };
assert.equal(availableAt(bounds, '1.21.9'), true);
assert.equal(availableAt(bounds, '26.3'), true);
assert.equal(availableAt(bounds, '26.4'), false);

const node = (id, minVersion = '26.3') => ({ id, name: id, minVersion, maxVersion: null });
const recipe = (id, type = 'crafting_shapeless') => ({ id, type, minVersion: '26.3', maxVersion: null });
const edge = (id, source, target, recipeId, type = 'crafting_shapeless') => ({ id, source, target, recipeId, type, minVersion: '26.3', maxVersion: null });
const graph = { schemaVersion: 1, version: '26.3', nodes: [node('diamond'), node('block'), node('bedrock'), node('future', '26.4')], recipes: [recipe('compress'), recipe('expand'), recipe('alternative'), recipe('smelt', 'smelting')], edges: [edge('a', 'diamond', 'block', 'compress'), edge('b', 'block', 'diamond', 'expand'), edge('c', 'diamond', 'block', 'alternative'), edge('d', 'future', 'block', 'smelt', 'smelting')] };
assert.equal(validateGraph(graph), graph);
assert.throws(() => validateGraph({ ...graph, nodes: [...graph.nodes, node('diamond')] }));
assert.throws(() => validateGraph({ ...graph, edges: [edge('bad', 'missing', 'block', 'compress')] }));
const filtered = filterGraph(graph, '26.3', new Set(['crafting_shapeless', 'smelting']));
assert.equal(filtered.nodes.length, 3);
assert.equal(filtered.edges.length, 3);
assert.ok(filtered.nodes.some(n => n.id === 'bedrock'));
assert.equal(filterGraph(graph, '26.3', new Set()).edges.length, 0);
assert.equal(filterGraph(graph, '26.2', new Set(['crafting_shapeless'])).nodes.length, 0);
assert.equal(filterGraph(graph, '26.3', new Set(['crafting_shapeless']), 'diamond').nodes.length, 2);
const grouped = groupEdges(filtered.edges);
assert.equal(grouped.length, 2);
assert.equal(grouped.find(g => g.source === 'diamond').edges.length, 2);
assert.equal(grouped.find(g => g.source === 'diamond').recipeIds.size, 2);
assert.equal(indexGraph(graph).outgoing.get('diamond').size, 2);
const layout = layoutGraph(filtered.nodes, filtered.edges);
assert.equal(layout.positions.length, 3);
assert.ok(layout.positions.every(p => Number.isFinite(p.x) && Number.isFinite(p.y)));
assert.equal(layout.regions.length, 0);
assert.deepEqual(layoutGraph([], []), { positions: [], regions: [] });
assert.deepEqual(layout, layoutGraph(filtered.nodes, filtered.edges));
console.log('Core checks passed: version bounds, data validation, filters, isolated nodes, opposing/parallel edges, and deterministic layout.');

const mixed = { ...graph, nodes: [...graph.nodes, { ...node('planks'), kind: 'category' }, { ...node('skeleton'), kind: 'mob' }, node('far')], relationships: [
  { id: 'member', type: 'belongs_to', category: 'membership', minVersion: '26.3' },
  { id: 'drop', type: 'mob_drop', category: 'loot', minVersion: '26.3', maxVersion: '26.3' },
  { id: 'next', type: 'belongs_to', category: 'membership', minVersion: '26.3' },
], edges: [...graph.edges,
  { id: 'm', source: 'diamond', target: 'planks', type: 'belongs_to', category: 'membership', relationId: 'member' },
  { id: 'l', source: 'skeleton', target: 'diamond', type: 'mob_drop', category: 'loot', relationId: 'drop' },
  { id: 'n', source: 'planks', target: 'far', type: 'belongs_to', category: 'membership', relationId: 'next' },
] };
assert.equal(validateGraph(mixed), mixed);
assert.throws(() => validateGraph({ ...mixed, edges: [...mixed.edges, { id: 'broken', source: 'diamond', target: 'planks', type: 'belongs_to', relationId: 'absent' }] }));
assert.throws(() => validateGraph({ ...mixed, edges: [{ ...mixed.edges[0], relationId: 'member' }] }));
const allTypes = new Set(mixed.edges.map(edge => edge.type));
const all = filterGraph(mixed, '26.3', allTypes);
assert.equal(all.edges.length, 6);
assert.equal(all.relationships.length, 3);
assert.equal(filterGraph(mixed, '26.4', allTypes).edges.some(edge => edge.id === 'l'), false);
const itemsOnly = filterGraph(mixed, '26.3', allTypes, null, new Set(['item']));
assert.ok(itemsOnly.nodes.every(node => nodeKind(node) === 'item'));
assert.equal(itemsOnly.edges.length, 3);
const mixedIndex = indexGraph(all);
assert.equal(mixedIndex.incoming.get('diamond').has('drop'), true);
assert.equal(mixedIndex.relationships.get('drop').type, 'mob_drop');
assert.equal(groupEdges(all.edges).flatMap(group => group.edges).length, all.edges.length);
assert.equal(groupEdges(all.edges).find(group => group.type === 'mob_drop').relationIds.size, 1);
assert.deepEqual(relationshipPath('crafting_special_bookcloning'), ['Recipes', 'Crafting', 'Book copying']);
assert.deepEqual(relationshipPath('mob_drop', 'loot'), ['Loot', 'Mob drops']);
assert.deepEqual(relationshipPath('spawn_egg', 'spawning'), ['Spawning', 'Spawn eggs']);
assert.deepEqual(relationshipPath('bucket_release', 'spawning'), ['Spawning', 'Bucket release']);
assert.deepEqual(relationshipPath('effect_spawn', 'effects'), ['Spawning', 'Status effects']);
assert.deepEqual(relationshipPath('potion_effect', 'effects'), ['Status effects', 'Sources', 'Potions']);
const direct = viewLayers(all, 'diamond', 'direct');
assert.deepEqual(direct.nodes.map(node => node.id).sort(), ['block', 'diamond', 'planks', 'skeleton']);
assert.ok(direct.edges.every(edge => edge.source === 'diamond' || edge.target === 'diamond'));
assert.equal(direct.depth.get('far'), 2);
assert.equal(direct.depth.get('bedrock'), 3);
const nearby = viewLayers(all, 'diamond', 'nearby');
assert.equal(nearby.nodes.some(node => node.id === 'bedrock'), false);
assert.equal(nearby.nodes.some(node => node.id === 'far'), true);
assert.equal(nearby.edgeDepth.get('n'), 2);
assert.equal(nearby.edgeDepth.get('a'), 1);
assert.equal(viewLayers(all, null, 'nearby').nodes.length, all.nodes.length);
const candidate = (group, distance, incident = false) => ({ group, distance, incident });
assert.equal(pickEdge([candidate('a', 1)], .2), null);
assert.equal(pickEdge([candidate('a', 1)], 1.2), null);
assert.equal(pickEdge([candidate('a', 1)], 1.2, 'diamond'), null);
assert.equal(pickEdge([candidate('a', 1, true), candidate('b', 2, true)], 1.2, 'diamond'), null);
assert.equal(pickEdge([candidate('a', 1, true), candidate('b', 4, true)], 1.2, 'diamond'), 'a');
assert.equal(pickEdge([candidate('a', 1), candidate('selected', 3, true)], .6, 'diamond'), 'selected');
assert.equal(pickEdge([candidate('a', 1, true), candidate('b', 2, true)], .6, 'diamond'), null);
const loops = { ...mixed, relationships: [...mixed.relationships, { id: 'self', type: 'belongs_to', category: 'membership', minVersion: '26.3' }], edges: [...mixed.edges,
  { id: 'self-edge', source: 'diamond', target: 'diamond', type: 'belongs_to', category: 'membership', relationId: 'self' },
] };
const noLoops = filterGraph(loops, '26.3', allTypes, null, null, false);
assert.equal(noLoops.edges.some(edge => edge.source === edge.target), false);
assert.equal(noLoops.nodes.length, all.nodes.length);
assert.equal(noLoops.edges.length, all.edges.length);
assert.equal(filterGraph(loops, '26.3', allTypes).edges.length, all.edges.length + 1);
const collidingTypes = { ...mixed, relationships: [...mixed.relationships, { id: 'other-family', type: 'belongs_to', category: 'uses' }], edges: [...mixed.edges,
  { id: 'other-edge', source: 'skeleton', target: 'block', type: 'belongs_to', category: 'uses', relationId: 'other-family' },
] };
const qualified = filterGraph(collidingTypes, '26.3', new Set(['membership:belongs_to']));
assert.equal(qualified.relationships.some(relation => relation.id === 'other-family'), false);
assert.ok(qualified.edges.every(edge => edge.category === 'membership'));
assert.equal(filterKey(collidingTypes.edges.at(-1)), 'uses:belongs_to');
const extendedNearby = { ...all, nodes: [...all.nodes, node('far-two')], edges: [...all.edges,
  { id: 'second-hop', source: 'block', target: 'far-two', type: 'belongs_to', category: 'membership', relationId: 'next' },
  { id: 'second-only', source: 'far', target: 'far-two', type: 'belongs_to', category: 'membership', relationId: 'next' },
] };
assert.equal(viewLayers(extendedNearby, 'diamond', 'nearby').edges.some(edge => edge.id === 'second-only'), false);
assert.equal(viewLayers(extendedNearby, 'diamond', 'nearby').edges.some(edge => edge.id === 'second-hop'), true);
// A dense second-hop hub must not pull the selected node's direct neighbors
// into overlapping central positions during Nearby layout.
const hubNodes = [node('focus'), ...Array.from({ length: 9 }, (_, i) => node(`direct-${i}`)), ...Array.from({ length: 135 }, (_, i) => node(`outer-${i}`))];
const hubEdges = [
  ...hubNodes.slice(1, 10).map(neighbor => ({ source: 'focus', target: neighbor.id })),
  ...hubNodes.slice(10).flatMap(neighbor => hubNodes.slice(1, 10).map(direct => ({ source: direct.id, target: neighbor.id }))),
];
const layered = layoutGraph(hubNodes, hubEdges, { mode: 'nearby', selected: 'focus' });
const layeredPositions = new Map(layered.positions.map(position => [position.id, position]));
assert.deepEqual(layeredPositions.get('focus'), { id: 'focus', x: 0, y: 0 });
const firstHop = hubNodes.slice(1, 10).map(node => layeredPositions.get(node.id));
for (let i = 0; i < firstHop.length; i++) for (let j = i + 1; j < firstHop.length; j++) {
  assert.ok(Math.hypot(firstHop[i].x - firstHop[j].x, firstHop[i].y - firstHop[j].y) > 220);
}
const innerRadius = Math.max(...firstHop.map(position => Math.hypot(position.x, position.y)));
assert.ok(hubNodes.slice(10).every(node => {
  const position = layeredPositions.get(node.id);
  return Number.isFinite(position.x) && Math.hypot(position.x, position.y) >= innerRadius + 219;
}));
assert.deepEqual(layered, layoutGraph(hubNodes, hubEdges, { mode: 'nearby', selected: 'focus' }));
assert.deepEqual(layoutGraph(filtered.nodes, filtered.edges, { mode: 'direct', selected: 'diamond' }), layout);
console.log('Mixed graph checks passed: kind filters, relationship records, hierarchy, two-hop layers, and ambiguous curve picking.');

const world = {
  schemaVersion: 1, version: '26.3', recipes: [],
  nodes: ['structure', 'biome', 'dimension'].map(kind => ({ ...node(`${kind}:minecraft:example`), kind })),
  relationships: ['structure_biome', 'biome_dimension'].map(type => ({ id: type, type, category: 'worldgen', minVersion: '26.3' })),
  edges: [
    { id: 'structure-biome', source: 'structure:minecraft:example', target: 'biome:minecraft:example', type: 'structure_biome', category: 'worldgen', relationId: 'structure_biome' },
    { id: 'biome-dimension', source: 'biome:minecraft:example', target: 'dimension:minecraft:example', type: 'biome_dimension', category: 'worldgen', relationId: 'biome_dimension' },
  ],
};
validateGraph(world);
const worldTypes = new Set(world.edges.map(filterKey));
assert.equal(filterGraph(world, '26.3', worldTypes).edges.length, 2);
const noStructures = filterGraph(world, '26.3', worldTypes, null, new Set(['biome', 'dimension']));
assert.equal(noStructures.nodes.length, 2);
assert.deepEqual(noStructures.edges.map(edge => edge.id), ['biome-dimension']);
assert.equal(filterGraph(world, '26.3', new Set(['worldgen:structure_biome'])).edges.length, 1);
assert.deepEqual(relationshipPath('structure_generated_mob', 'worldgen'), ['World generation', 'Structures', 'Generated residents']);
assert.deepEqual(relationshipPath('structure_spawner_mob', 'worldgen'), ['World generation', 'Structures', 'Spawner mobs']);
assert.deepEqual(relationshipPath('structure_spawn_mob', 'worldgen'), ['World generation', 'Structures', 'Natural spawning overrides']);
assert.deepEqual(relationshipPath('biome_block', 'worldgen'), ['World generation', 'Biomes', 'Natural blocks']);
assert.deepEqual(relationshipPath('structure_loot', 'loot'), ['Loot', 'Structure loot']);
assert.equal(viewLayers(world, world.nodes[0].id, 'direct').nodes.some(node => node.kind === 'dimension'), false);
assert.equal(viewLayers(world, world.nodes[0].id, 'nearby').depth.get(world.nodes[2].id), 2);

const structureNode = world.nodes[0], circleNode = world.nodes[1], radius = 18;
assert.equal(nodeContainsPoint(structureNode, radius, 17, 10), true);
assert.equal(nodeContainsPoint(circleNode, radius, 17, 10), false);
assert.equal(nodeContainsPoint(structureNode, radius, 18, 18), false);
assert.equal(nodeContainsPoint(structureNode, radius, 19, 0), false);
assert.equal(nodeBoundaryDistance(structureNode, radius, 1, 0), radius);
assert.equal(nodeBoundaryDistance(circleNode, radius, 1, 1), radius);
const diagonal = nodeBoundaryDistance(structureNode, radius, 1, 1);
assert.ok(Math.abs(diagonal - (radius * (1 - STRUCTURE_CORNER_RATIO) * Math.SQRT2 + radius * STRUCTURE_CORNER_RATIO)) < 1e-10);
// Curve endpoints and the hit area agree at straight edges and rounded corners.
for (let angle = 0; angle < 2 * Math.PI; angle += Math.PI / 24) {
  const x = Math.cos(angle), y = Math.sin(angle), boundary = nodeBoundaryDistance(structureNode, radius, x, y);
  assert.equal(nodeContainsPoint(structureNode, radius, x * (boundary - .001), y * (boundary - .001)), true);
  assert.equal(nodeContainsPoint(structureNode, radius, x * (boundary + .001), y * (boundary + .001)), false);
}
console.log('World generation checks passed: new node filters, two-hop dimensions, spawn semantics, rounded-square clipping and hit areas.');
