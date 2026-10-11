// Version bounds describe the supplied snapshot; they are inclusive.
export function compareVersions(a, b) {
  const parse = value => {
    const match = /^(\d+(?:\.\d+)*)(?:[- ](.+))?$/.exec(String(value));
    if (!match) throw new Error(`Invalid game version: ${value}`);
    return { numbers: match[1].split('.').map(Number), suffix: match[2] || '' };
  };
  const left = parse(a), right = parse(b);
  for (let i = 0; i < Math.max(left.numbers.length, right.numbers.length); i++) {
    const difference = (left.numbers[i] || 0) - (right.numbers[i] || 0);
    if (difference) return Math.sign(difference);
  }
  if (left.suffix === right.suffix) return 0;
  if (!left.suffix) return 1;
  if (!right.suffix) return -1;
  return left.suffix.localeCompare(right.suffix, undefined, { numeric: true });
}

export function availableAt(entity, version) {
  return (!entity.minVersion || compareVersions(entity.minVersion, version) <= 0)
    && (!entity.maxVersion || compareVersions(version, entity.maxVersion) <= 0);
}

export const nodeKind = node => node.kind || 'item';
export const edgeCategory = edge => edge.category || (edge.recipeId ? 'recipe' : 'relationship');
export const relationKey = edge => edge.recipeId || edge.relationId;
export const filterKey = edge => `${edgeCategory(edge)}:${edge.type}`;

export function validateGraph(graph) {
  if (graph?.schemaVersion !== 1 || !graph.version || !Array.isArray(graph.nodes)
      || !Array.isArray(graph.edges) || !Array.isArray(graph.recipes)
      || (graph.relationships !== undefined && !Array.isArray(graph.relationships))) throw new Error('Unsupported or incomplete graph data.');
  compareVersions(graph.version, graph.version);
  for (const name of ['nodes', 'recipes', 'relationships', 'edges']) {
    const ids = new Set();
    for (const item of graph[name] || []) {
      if (typeof item.id !== 'string' || !item.id || ids.has(item.id)) throw new Error(`Missing or duplicate ${name} identifier: ${item.id}`);
      ids.add(item.id);
      if (item.minVersion) compareVersions(item.minVersion, graph.version);
      if (item.maxVersion) compareVersions(item.maxVersion, graph.version);
      if (item.maxVersion && item.minVersion && compareVersions(item.minVersion, item.maxVersion) > 0) throw new Error(`Inverted version range: ${item.id}`);
    }
  }
  const nodes = new Set(graph.nodes.map(node => node.id));
  const recipes = new Set(graph.recipes.map(recipe => recipe.id));
  const relationships = new Set((graph.relationships || []).map(relation => relation.id));
  for (const id of relationships) if (recipes.has(id)) throw new Error(`Duplicate relationship identifier: ${id}`);
  for (const node of graph.nodes) if (typeof nodeKind(node) !== 'string' || !nodeKind(node)) throw new Error(`Unsupported node kind: ${node.kind}`);
  for (const edge of graph.edges) {
    if (!nodes.has(edge.source) || !nodes.has(edge.target) || typeof edge.type !== 'string'
        || Boolean(edge.recipeId) === Boolean(edge.relationId)
        || (edge.recipeId ? !recipes.has(edge.recipeId) : !relationships.has(edge.relationId))) throw new Error(`Broken connection: ${edge.id}`);
  }
  return graph;
}

export function filterGraph(graph, version, types, focusId = null, kinds = null, showSelfLoops = true) {
  let nodes = graph.nodes.filter(node => availableAt(node, version) && (!kinds || kinds.has(nodeKind(node))));
  const ids = new Set(nodes.map(node => node.id));
  const enabled = (record, category) => types.has(record.type) || types.has(`${record.category || category}:${record.type}`);
  const recipes = graph.recipes.filter(recipe => availableAt(recipe, version) && enabled(recipe, 'recipe'));
  const relationships = (graph.relationships || []).filter(relation => availableAt(relation, version) && enabled(relation, 'relationship'));
  const records = new Set([...recipes, ...relationships].map(record => record.id));
  let edges = graph.edges.filter(edge => availableAt(edge, version) && enabled(edge, edgeCategory(edge))
    && (showSelfLoops || edge.source !== edge.target)
    && records.has(relationKey(edge)) && ids.has(edge.source) && ids.has(edge.target));
  if (focusId) {
    const neighbors = new Set([focusId]);
    for (const edge of edges) if (edge.source === focusId || edge.target === focusId) {
      neighbors.add(edge.source); neighbors.add(edge.target);
    }
    nodes = nodes.filter(node => neighbors.has(node.id));
    edges = edges.filter(edge => neighbors.has(edge.source) && neighbors.has(edge.target));
  }
  const visibleRecords = new Set(edges.map(relationKey));
  return { nodes, edges, recipes: focusId ? recipes.filter(recipe => visibleRecords.has(recipe.id)) : recipes,
    relationships: focusId ? relationships.filter(relation => visibleRecords.has(relation.id)) : relationships };
}

// Curves keep all original records, including opposite directions and parallel recipes.
export function groupEdges(edges) {
  const groups = new Map();
  for (const edge of edges) {
    const category = edgeCategory(edge), key = JSON.stringify([edge.source, edge.target, category, edge.type]);
    if (!groups.has(key)) groups.set(key, { key, source: edge.source, target: edge.target, category, type: edge.type, edges: [], recipeIds: new Set(), relationIds: new Set() });
    const group = groups.get(key); group.edges.push(edge);
    if (edge.recipeId) group.recipeIds.add(edge.recipeId);
    if (edge.relationId) group.relationIds.add(edge.relationId);
  }
  return [...groups.values()];
}

export function indexGraph(graph) {
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const recipes = new Map(graph.recipes.map(recipe => [recipe.id, recipe]));
  const relationships = new Map((graph.relationships || []).map(relation => [relation.id, relation]));
  const incoming = new Map(graph.nodes.map(node => [node.id, new Set()]));
  const outgoing = new Map(graph.nodes.map(node => [node.id, new Set()]));
  const incomingEdges = new Map(graph.nodes.map(node => [node.id, []]));
  const outgoingEdges = new Map(graph.nodes.map(node => [node.id, []]));
  const degree = new Map(graph.nodes.map(node => [node.id, new Set()]));
  for (const edge of graph.edges) {
    incoming.get(edge.target)?.add(relationKey(edge)); outgoing.get(edge.source)?.add(relationKey(edge));
    incomingEdges.get(edge.target)?.push(edge); outgoingEdges.get(edge.source)?.push(edge);
    degree.get(edge.source)?.add(edge.target); degree.get(edge.target)?.add(edge.source);
  }
  return { nodes, recipes, relationships, incoming, outgoing, incomingEdges, outgoingEdges, degree };
}

const labels = {
  coral_dying: 'Coral dying', mining_experience: 'Mining', mob_experience: 'Mob kills', smelting_experience: 'Cooking', breeding_experience: 'Breeding', fishing_experience: 'Fishing', bottle_experience: "Bottles o’ Enchanting", disenchanting_experience: 'Disenchanting',
  crafting_shaped: 'Shaped', crafting_shapeless: 'Shapeless', crafting_decorated_pot: 'Decorated pots',
  crafting_dye: 'Dyeing', crafting_imbue: 'Imbuing', crafting_transmute: 'Transmuting',
  crafting_special_bannerduplicate: 'Banner copying', crafting_special_bookcloning: 'Book copying',
  crafting_special_mapextending: 'Map scaling', crafting_special_repairitem: 'Item repair',
  crafting_special_shielddecoration: 'Shield patterns', crafting_special_firework_rocket: 'Firework rockets',
  crafting_special_firework_star: 'Firework stars', crafting_special_firework_star_fade: 'Firework fade',
  smelting: 'Smelting', blasting: 'Blasting', smoking: 'Smoking', campfire_cooking: 'Campfire cooking',
  stonecutting: 'Stonecutting', smithing_transform: 'Transforming', smithing_trim: 'Armor trims', brewing: 'Brewing', loom: 'Banner patterns',
  anvil_repair: 'Material repair', anvil_combine: 'Combining', anvil_enchant: 'Enchanting',
  grindstone_repair: 'Combining & repair', grindstone_disenchant: 'Disenchanting',
  cartography_clone: 'Map cloning', cartography_extend: 'Map scaling', cartography_lock: 'Map locking',
  belongs_to: 'Belongs to', tag_contains: 'Included in category', composting: 'Composting', harvesting: 'Harvesting', mob_drop: 'Mob drops',
  ramming: 'Ramming', archaeology: 'Archaeology', gifting: 'Gifting', carving: 'Carving', tilling: 'Tilling', bucket_filling: 'Bucket filling', bottling: 'Bottling', mob_capture: 'Mob capture',
  block_drop: 'Block drops', fishing: 'Fishing', bartering: 'Bartering', passive_drop: 'Passive drops', shearing: 'Shearing', brushing: 'Brushing', milking: 'Milking', honey_harvesting: 'Honey harvesting',
  spawn_egg: 'Spawn eggs', bucket_release: 'Bucket release', mob_building: 'Mob building', egg_hatching: 'Egg hatching', ender_pearl_spawn: 'Ender pearls', creaking_heart_spawn: 'Creaking hearts',
  food_effect: 'Food', potion_effect: 'Potions', arrow_effect: 'Tipped arrows', beacon_effect: 'Beacons', mob_attack_effect: 'Mob attacks', mob_aura_effect: 'Mob auras', block_contact_effect: 'Block contact',
  remove_effect: 'Removing effects', death_protection: 'Death protection', ominous_effect: 'Ominous effects', effect_conversion: 'Effect conversion', effect_compatibility: 'Effect compatibility', effect_spawn: 'Spawning', effect_world_change: 'World changes', witch_potion: 'Witch potions', cure_zombie_villager: 'Curing zombie villagers', consume_remainder: 'Consumption remainders',
};
export function recipeType(type) {
  const color = type === 'belongs_to' || type === 'tag_contains' ? '#8b7ab5' : type === 'mob_drop' ? '#6589bd' : '#4c83c6';
  return { label: labels[type] || type.replace(/^crafting_special_/, '').replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase()), color };
}
export function relationshipPath(type, category = 'recipe') {
  if (category === 'effects' && type === 'effect_spawn') return ['Spawning', 'Status effects'];
  const family = ({ recipe: 'Recipes', membership: 'Membership', gathering: 'Gathering', loot: 'Loot', uses: 'Uses', spawning: 'Spawning', effects: 'Status effects', interactions: 'Interactions' })[category] || category.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase());
  if (category === 'effects') {
    const section = ['food_effect', 'potion_effect', 'arrow_effect', 'beacon_effect', 'mob_attack_effect', 'mob_aura_effect', 'block_contact_effect', 'ominous_effect'].includes(type) ? 'Sources'
      : ['effect_spawn', 'effect_world_change'].includes(type) ? 'Consequences' : 'Interactions';
    return [family, section, recipeType(type).label];
  }
  if (category !== 'recipe') return [family, recipeType(type).label];
  const station = type.startsWith('crafting_') ? 'Crafting' : type.startsWith('anvil_') ? 'Anvil'
    : type.startsWith('grindstone_') ? 'Grindstone' : type.startsWith('cartography_') ? 'Cartography'
    : type.startsWith('smithing_') ? 'Smithing' : type === 'loom' ? 'Loom' : null;
  return station ? [family, station, recipeType(type).label] : [family, recipeType(type).label];
}

export function viewLayers(graph, selected, mode = 'all') {
  const depth = new Map(graph.nodes.map(node => [node.id, 3]));
  if (!selected || !depth.has(selected)) return { ...graph, depth, edgeDepth: new Map(graph.edges.map(edge => [edge.id, 1])) };
  depth.set(selected, 0);
  for (let hop = 1; hop <= 2; hop++) {
    const additions = new Set();
    for (const edge of graph.edges) {
      if (depth.get(edge.source) === hop - 1 && depth.get(edge.target) > hop) additions.add(edge.target);
      if (depth.get(edge.target) === hop - 1 && depth.get(edge.source) > hop) additions.add(edge.source);
    }
    for (const id of additions) depth.set(id, hop);
  }
  const incident = edge => edge.source === selected || edge.target === selected;
  const edges = mode === 'direct' ? graph.edges.filter(incident)
    : mode === 'nearby' ? graph.edges.filter(edge => depth.get(edge.source) <= 2 && depth.get(edge.target) <= 2
      && (depth.get(edge.source) <= 1 || depth.get(edge.target) <= 1)) : graph.edges;
  const nodes = mode === 'direct' ? graph.nodes.filter(node => depth.get(node.id) <= 1)
    : mode === 'nearby' ? graph.nodes.filter(node => depth.get(node.id) <= 2) : graph.nodes;
  return { ...graph, nodes, edges, depth, edgeDepth: new Map(edges.map(edge => [edge.id, incident(edge) ? 1 : 2])) };
}

// Dense crossings are ambiguous; the user can select a node or zoom until a curve separates.
export function pickEdge(candidates, zoom, selected = null) {
  if (!selected) return null;
  const eligible = candidates.filter(candidate => candidate.incident && candidate.distance <= 5 && zoom >= .45);
  eligible.sort((a, b) => a.distance - b.distance);
  if (!eligible.length || (eligible[1] && eligible[1].distance - eligible[0].distance < 2.5)) return null;
  return eligible[0].group;
}

export function layoutGraph(nodes, edges, options = {}) {
  const count = nodes.length;
  if (!count) return { positions: [], regions: [] };
  if (options.mode === 'nearby' && nodes.some(node => node.id === options.selected)) {
    const { depth } = viewLayers({ nodes, edges }, options.selected, 'nearby');
    const order = (a, b) => (a.name || a.id).localeCompare(b.name || b.id) || a.id.localeCompare(b.id);
    const direct = nodes.filter(node => depth.get(node.id) === 1).sort(order);
    const outer = nodes.filter(node => depth.get(node.id) >= 2).sort(order);
    const positions = new Map([[options.selected, { id: options.selected, x: 0, y: 0 }]]);
    // Hub springs collapse first-hop neighbors. Separate depth bands keep the
    // focused items readable while the second hop stays in the outer context.
    const innerRadius = Math.max(240, direct.length * 220 / (2 * Math.PI), Math.sqrt(outer.length) * 30);
    const ring = (entries, radius, phase = 0) => entries.forEach((node, i) => {
      const angle = -Math.PI / 2 + phase + i * 2 * Math.PI / entries.length;
      positions.set(node.id, { id: node.id, x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
    });
    ring(direct, innerRadius);
    let radius = innerRadius + 220, placed = 0, band = 0;
    while (placed < outer.length) {
      const capacity = Math.max(1, Math.floor(2 * Math.PI * radius / 80));
      const entries = outer.slice(placed, placed + capacity);
      ring(entries, radius, band % 2 ? Math.PI / entries.length : 0);
      placed += entries.length; radius += 90; band++;
    }
    return { positions: nodes.map(node => positions.get(node.id)), regions: [] };
  }
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const neighbors = Array.from({ length: count }, () => new Set());
  const pairs = new Map();
  for (const edge of edges) {
    const a = index.get(edge.source), b = index.get(edge.target);
    if (a === undefined || b === undefined || a === b) continue;
    neighbors[a].add(b); neighbors[b].add(a);
    pairs.set(`${Math.min(a, b)}:${Math.max(a, b)}`, [a, b]);
  }
  const connected = [], loose = [];
  nodes.forEach((_, i) => (neighbors[i].size ? connected : loose).push(i));
  const x = new Float64Array(count), y = new Float64Array(count);
  const vx = new Float64Array(count), vy = new Float64Array(count);
  connected.sort((a, b) => neighbors[b].size - neighbors[a].size || nodes[a].id.localeCompare(nodes[b].id));
  connected.forEach((i, rank) => {
    const radius = 40 * Math.sqrt(rank), angle = rank * 2.399963;
    x[i] = Math.cos(angle) * radius; y[i] = Math.sin(angle) * radius;
  });
  const springs = [...pairs.values()];
  // A local repulsion grid bounds work; layout happens once in a Web Worker.
  for (let iteration = 0; iteration < 160; iteration++) {
    const cells = new Map(), cellSize = 115;
    for (const i of connected) {
      const key = `${Math.floor(x[i] / cellSize)},${Math.floor(y[i] / cellSize)}`;
      if (!cells.has(key)) cells.set(key, []);
      cells.get(key).push(i);
      vx[i] = -x[i] * .0008; vy[i] = -y[i] * .0008;
    }
    for (const i of connected) {
      const cx = Math.floor(x[i] / cellSize), cy = Math.floor(y[i] / cellSize);
      for (let gx = cx - 1; gx <= cx + 1; gx++) for (let gy = cy - 1; gy <= cy + 1; gy++) {
        for (const j of cells.get(`${gx},${gy}`) || []) {
          if (j <= i) continue;
          let dx = x[i] - x[j], dy = y[i] - y[j];
          if (dx === 0 && dy === 0) dx = .1;
          const squared = dx * dx + dy * dy;
          if (squared > 23000) continue;
          const force = 1500 / Math.max(squared, 20);
          vx[i] += dx * force; vy[i] += dy * force;
          vx[j] -= dx * force; vy[j] -= dy * force;
        }
      }
    }
    for (const [a, b] of springs) {
      const dx = x[b] - x[a], dy = y[b] - y[a], distance = Math.hypot(dx, dy) || 1;
      const force = (distance - 120) * .011 / Math.sqrt(Math.max(neighbors[a].size, neighbors[b].size, 1));
      vx[a] += dx / distance * force; vy[a] += dy / distance * force;
      vx[b] -= dx / distance * force; vy[b] -= dy / distance * force;
    }
    const cooling = 1 - iteration / 210;
    for (const i of connected) {
      x[i] += Math.max(-20, Math.min(20, vx[i])) * cooling;
      y[i] += Math.max(-20, Math.min(20, vy[i])) * cooling;
    }
  }
  let right = 0;
  for (const i of connected) right = Math.max(right, x[i]);
  const columns = Math.max(5, Math.ceil(Math.sqrt(loose.length * .65)));
  const rows = Math.ceil(loose.length / columns), left = right + 230;
  loose.sort((a, b) => nodes[a].name.localeCompare(nodes[b].name));
  loose.forEach((i, rank) => { x[i] = left + (rank % columns) * 72; y[i] = (Math.floor(rank / columns) - rows / 2) * 72; });
  const regions = [];
  return { positions: nodes.map((node, i) => ({ id: node.id, x: x[i], y: y[i] })), regions };
}
