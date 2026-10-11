import { availableAt, validateGraph, filterGraph, groupEdges, indexGraph, recipeType, relationshipPath, nodeKind, edgeCategory, relationKey, filterKey, viewLayers, pickEdge } from './core.mjs';

const $ = id => document.getElementById(id);
const canvas = $('graph'), ctx = canvas.getContext('2d');
const number = value => value.toLocaleString();
const state = { graph: null, index: null, version: null, types: new Set(), positions: new Map(), selected: null, selectedEdge: null, mode: 'all', showSelfLoops: false, kinds: new Set(), query: '', limit: 60, view: null, base: null, groups: [], neighbors: new Set(), images: new Map(), camera: { x: 0, y: 0, zoom: 1 }, width: 1, height: 1, frame: null, hover: null, pointers: new Map(), gesture: null, ready: false };
const mobile = matchMedia('(max-width: 620px), (max-width: 950px) and (max-height: 500px) and (pointer: coarse)');
const mobilePanel = $('mobile-panel');
let panelOrigin = null;

function restoreMobilePanel() {
  if (!panelOrigin) return;
  const { node, parent, next } = panelOrigin;
  parent.insertBefore(node, next); panelOrigin = null;
}

function closeMobilePanel() {
  restoreMobilePanel();
  if (mobilePanel.open) mobilePanel.close();
}

function openMobilePanel(kind) {
  if (!mobile.matches || mobilePanel.open || !state.ready) return;
  const node = kind === 'details' ? $('details') : document.querySelector('.sidebar');
  panelOrigin = { node, parent: node.parentNode, next: node.nextSibling };
  mobilePanel.dataset.panel = kind;
  $('mobile-panel-title').textContent = { search: 'Search nodes', filters: 'Filters', details: 'Details' }[kind];
  $('mobile-panel-content').append(node);
  mobilePanel.showModal();
  if (kind === 'search') { $('search').focus(); renderSearch(); }
  $('mobile-panel-content').scrollTop = 0;
}

function syncMobileSelection() {
  const selected = Boolean(state.selected || state.selectedEdge);
  $('mobile-selection').hidden = !mobile.matches || !selected;
  document.body.classList.toggle('mobile-has-selection', mobile.matches && selected);
  if (!mobile.matches) return;
  if (!selected) {
    if (mobilePanel.dataset.panel === 'details') closeMobilePanel();
    return;
  }
  const node = state.index.nodes.get(state.selected);
  const button = $('mobile-details');
  button.replaceChildren();
  if (node && !state.selectedEdge) button.append(icon(node));
  button.append(element('span', 'mobile-selection-name', state.selectedEdge ? 'Selected connection' : node.name), element('span', 'mobile-details-label', 'Details ›'));
}

$('mobile-search').addEventListener('click', () => openMobilePanel('search'));
$('mobile-filters').addEventListener('click', () => openMobilePanel('filters'));
$('mobile-details').addEventListener('click', () => openMobilePanel('details'));
$('mobile-clear').addEventListener('click', clearSelection);
$('mobile-panel-close').addEventListener('click', closeMobilePanel);
mobilePanel.addEventListener('close', () => { if (!mobilePanel.open) restoreMobilePanel(); });
mobilePanel.addEventListener('click', event => {
  const r = mobilePanel.getBoundingClientRect();
  if (event.target === mobilePanel && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) closeMobilePanel();
});
mobile.addEventListener('change', () => { closeMobilePanel(); if (state.graph) syncMobileSelection(); });

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const iconSource = node => node?.icon?.startsWith('assets/') ? `${node.icon}?v=${encodeURIComponent(state.graph?.assetRevision || state.graph?.version || '')}` : '';

function icon(node, className = '') {
  const img = element('img', className);
  img.alt = '';
  img.loading = 'lazy';
  if (iconSource(node)) img.src = iconSource(node);
  img.addEventListener('error', () => { img.style.visibility = 'hidden'; }, { once: true });
  if (nodeKind(node || {}) === 'category') {
    const hexagon = element('span', `category-icon ${className}`); hexagon.setAttribute('aria-hidden', 'true'); hexagon.append(img); return hexagon;
  }
  return img;
}

function itemButton(id, className = 'ingredient-chip', label, mode = null) {
  const node = state.index.nodes.get(id);
  const button = element('button', className);
  button.append(icon(node), element('span', '', label || node?.name || id));
  button.title = id;
  button.addEventListener('click', () => selectNode(id, true, mode));
  return button;
}

function updateView(shouldFit = false) {
  if (!state.graph) return;
  state.hover = null; $('tooltip').hidden = true;
  state.focusWorker?.terminate(); state.focusWorker = null;
  state.positions = state.fullPositions || state.positions;
  $('loading').hidden = state.ready;
  state.base = filterGraph(state.graph, state.version, state.types, null, state.kinds, state.showSelfLoops);
  if (state.selected && !state.base.nodes.some(node => node.id === state.selected)) {
    state.selected = null; state.selectedEdge = null;
    history.replaceState(null, '', location.pathname + location.search);
  }
  state.view = viewLayers(state.base, state.selected, state.mode);
  state.activeIndex = indexGraph(state.base); state.baseDegree = state.activeIndex.degree;
  state.neighbors = new Set([...state.view.depth].filter(([, depth]) => depth <= 1).map(([id]) => id));
  state.groups = groupEdges(state.view.edges);
  const typesForPair = new Map();
  for (const group of state.groups) {
    const pair = [group.source, group.target].sort().join('|');
    if (!typesForPair.has(pair)) typesForPair.set(pair, []);
    const key = `${group.category}:${group.type}`;
    if (!typesForPair.get(pair).includes(key)) typesForPair.get(pair).push(key);
  }
  for (const group of state.groups) {
    const pair = [group.source, group.target].sort().join('|');
    group.offset = 18 + typesForPair.get(pair).indexOf(`${group.category}:${group.type}`) * 12;
    group.color = recipeType(group.type).color; updateCurve(group);
  }
  $('node-count').textContent = number(state.view.nodes.length);
  $('edge-count').textContent = number(state.view.edges.length);
  document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mode === state.mode)));
  syncFilters(); renderSearch();
  if (state.selectedEdge) {
    const group = state.groups.find(group => group.key === state.selectedEdge);
    if (group) selectEdge(group); else state.selectedEdge = null;
  }
  if (!state.selectedEdge) {
    if (state.selected) renderItemDetails();
    else { $('details').classList.remove('has-selection'); $('details').replaceChildren(state.emptyDetails.cloneNode(true)); populateStarters(); }
  }
  syncMobileSelection();
  if (state.mode !== 'all' && state.selected && state.ready) relayout();
  else if (shouldFit && state.ready) fit();
  requestDraw();
}

function relayout() {
  if (!state.ready || !state.view?.nodes.length) return;
  state.focusWorker?.terminate();
  const worker = new Worker('graph-worker.js', { type: 'module' });
  const local = state.mode !== 'all' && state.selected;
  state.focusWorker = worker; $('loading').hidden = false;
  $('loading').querySelector('h2').textContent = `Arranging ${local ? state.mode + ' nodes' : 'graph'}`;
  $('loading-text').textContent = `${number(state.view.nodes.length)} nodes · ${number(state.view.edges.length)} connections`;
  worker.onmessage = ({ data }) => {
    if (state.focusWorker !== worker) return;
    worker.terminate(); state.focusWorker = null;
    if (data.error) { console.error(data.error); state.mode = 'all'; updateView(true); return; }
    state.positions = new Map(data.positions.map(position => [position.id, position]));
    if (!local) { state.fullPositions = new Map([...state.fullPositions, ...state.positions]); state.positions = state.fullPositions; }
    state.groups.forEach(updateCurve); $('loading').hidden = true; fit();
  };
  worker.onerror = () => { if (state.focusWorker !== worker) return; worker.terminate(); state.focusWorker = null; state.mode = 'all'; updateView(true); };
  worker.postMessage({ nodes: state.view.nodes.map(({ id, name }) => ({ id, name })), edges: state.view.edges.map(({ source, target }) => ({ source, target })), mode: state.mode, selected: state.selected });
}

function availableCanvasWidth() {
  const details = $('details');
  if (details.classList.contains('has-selection') && getComputedStyle(details).position === 'absolute') {
    return Math.max(100, Math.min(state.width, details.getBoundingClientRect().left - canvas.getBoundingClientRect().left));
  }
  return state.width;
}

function updateCurve(group) {
  const a = state.positions.get(group.source), b = state.positions.get(group.target);
  if (!a || !b) return;
  if (group.source === group.target) {
    group.curve = { ax: a.x + 12, ay: a.y - 12, bx: a.x - 12, by: a.y - 12, cx: a.x + 72, cy: a.y - 86, dx: a.x - 72, dy: a.y - 86, loop: true };
  } else {
    const dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy) || 1;
    const offset = Math.min(group.offset, distance * .32);
    const cx = (a.x + b.x) / 2 - dy / distance * offset, cy = (a.y + b.y) / 2 + dx / distance * offset;
    const ad = Math.hypot(cx - a.x, cy - a.y) || 1, bd = Math.hypot(cx - b.x, cy - b.y) || 1;
    group.curve = { ax: a.x + (cx - a.x) / ad * 18, ay: a.y + (cy - a.y) / ad * 18, bx: b.x + (cx - b.x) / bd * 18, by: b.y + (cy - b.y) / bd * 18, cx, cy, loop: false };
  }
  const c = group.curve;
  group.bounds = { left: Math.min(c.ax, c.bx, c.cx, c.dx ?? c.cx), right: Math.max(c.ax, c.bx, c.cx, c.dx ?? c.cx), top: Math.min(c.ay, c.by, c.cy), bottom: Math.max(c.ay, c.by, c.cy) };
}

function renderSearch() {
  const list = $('item-list'); list.replaceChildren();
  if (!state.base) { $('search-results').hidden = true; return; }
  const query = state.query.toLocaleLowerCase().trim();
  $('search-results').hidden = !query || document.activeElement !== $('search');
  if (!query) return;
  const matches = state.base.nodes.filter(node => node.name.toLocaleLowerCase().includes(query) || node.id.toLocaleLowerCase().includes(query))
    .sort((a, b) => a.name.localeCompare(b.name));
  $('result-count').textContent = number(matches.length);
  for (const node of matches.slice(0, state.limit)) {
    const button = itemButton(node.id, `item-row${state.selected === node.id ? ' selected' : ''}`, null, 'direct');
    button.children[1].className = 'item-name';
    button.append(element('span', 'node-kind', nodeKind(node))); list.append(button);
  }
  if (!matches.length) list.append(element('p', 'no-results', 'No matching nodes in this version and node filters.'));
  if (matches.length > state.limit) {
    const button = element('button', 'show-more', `Show more · ${number(matches.length - state.limit)} remaining`);
    button.addEventListener('click', () => { state.limit += 60; $('search').focus(); renderSearch(); }); list.append(button);
  }
}

function buildTypeFilters() {
  const root = { children: new Map(), types: new Set(), count: 0 };
  const counts = new Map();
  for (const record of [...state.graph.recipes, ...(state.graph.relationships || [])]) {
    const category = record.category || (state.index.recipes.has(record.id) ? 'recipe' : 'relationship');
    const key = `${category}:${record.type}`;
    if (!counts.has(key)) counts.set(key, { type: record.type, category, key, count: 0 });
    counts.get(key).count++;
  }
  for (const { type, category, key, count } of counts.values()) {
    let branch = root; branch.types.add(key); branch.count += count;
    for (const name of relationshipPath(type, category)) {
      if (!branch.children.has(name)) branch.children.set(name, { name, children: new Map(), types: new Set(), count: 0 });
      branch = branch.children.get(name); branch.types.add(key); branch.count += count;
    }
  }
  const container = $('type-filters'); container.replaceChildren(); state.filterInputs = [];
  function renderBranch(branch) {
    const label = element('label', 'filter-label'), checkbox = element('input'); checkbox.type = 'checkbox';
    const types = [...branch.types]; state.filterInputs.push({ checkbox, types });
    checkbox.setAttribute('aria-label', `Show ${branch.name} relationships`);
    checkbox.addEventListener('click', event => event.stopPropagation());
    checkbox.addEventListener('change', () => {
      for (const type of types) if (checkbox.checked) state.types.add(type); else state.types.delete(type);
      updateView();
    });
    label.append(checkbox, element('span', 'filter-name', branch.name), element('span', 'filter-count', number(branch.count)));
    if (!branch.children.size) return label;
    const details = element('details');
    const summary = element('summary'); summary.append(label); details.append(summary);
    const children = element('div');
    for (const child of branch.children.values()) children.append(renderBranch(child));
    details.append(children); return details;
  }
  for (const branch of root.children.values()) container.append(renderBranch(branch));
  const nodeContainer = $('node-filters'); nodeContainer.replaceChildren(); state.nodeInputs = [];
  const kinds = new Map();
  for (const node of state.graph.nodes) kinds.set(nodeKind(node), (kinds.get(nodeKind(node)) || 0) + 1);
  const kindLabels = { item: 'Items', category: 'Categories', mob: 'Mobs', block: 'Blocks', effect: 'Status effects', entity: 'Other entities' };
  for (const [kind, count] of kinds) {
    const label = element('label', 'filter-label'), checkbox = element('input'); checkbox.type = 'checkbox'; checkbox.value = kind;
    checkbox.setAttribute('aria-label', `Show ${kindLabels[kind] || kind} nodes`);
    state.nodeInputs.push(checkbox);
    checkbox.addEventListener('change', () => { if (checkbox.checked) state.kinds.add(kind); else state.kinds.delete(kind); updateView(true); });
    label.append(checkbox, element('span', 'filter-name', kindLabels[kind] || kind), element('span', 'filter-count', number(count))); nodeContainer.append(label);
  }
  syncFilters();
}

function syncFilters() {
  for (const { checkbox, types } of state.filterInputs || []) {
    const shown = types.filter(type => state.types.has(type)).length;
    checkbox.checked = shown === types.length; checkbox.indeterminate = shown > 0 && shown < types.length;
  }
  for (const checkbox of state.nodeInputs || []) checkbox.checked = state.kinds.has(checkbox.value);
  $('toggle-types').textContent = state.types.size ? 'Hide all' : 'Show all';
  $('toggle-nodes').textContent = state.kinds.size ? 'Hide all' : 'Show all';
}

function selectNode(id, moveCamera = false, mode = null) {
  const node = state.index?.nodes.get(id);
  if (!node || !availableAt(node, state.version) || !state.kinds.has(nodeKind(node))) return;
  state.selected = id; state.selectedEdge = null;
  if (mobilePanel.open && mobilePanel.dataset.panel === 'search') closeMobilePanel();
  if (mode) state.mode = mode;
  $('search-results').hidden = true;
  history.replaceState(null, '', `#${encodeURIComponent(id)}`);
  updateView(state.mode !== 'all');
  if (moveCamera && state.mode === 'all') {
    const position = state.positions.get(id);
    if (!position) return;
    state.camera.zoom = Math.max(state.camera.zoom, .95);
    state.camera.x = availableCanvasWidth() / 2 - position.x * state.camera.zoom;
    state.camera.y = state.height / 2 - position.y * state.camera.zoom;
  }
  requestDraw();
}

function clearSelection() {
  if (!state.graph) return;
  state.selected = null; state.selectedEdge = null;
  history.replaceState(null, '', location.pathname + location.search);
  $('details').classList.remove('has-selection');
  $('details').replaceChildren(state.emptyDetails.cloneNode(true));
  populateStarters(); updateView(true);
}

function populateStarters() {
  const container = $('starter-items');
  if (!container) return;
  container.replaceChildren();
  for (const id of ['minecraft:crafting_table', 'minecraft:diamond', 'minecraft:oak_log']) {
    if (!state.index.nodes.has(id)) continue;
    const button = itemButton(id, 'starter-item');
    button.append(element('span', '', '↗')); container.append(button);
  }
}

function detailsTop(label) {
  const header = element('div', 'detail-topline');
  const close = element('button', 'close-button', '×'); close.setAttribute('aria-label', 'Clear selection');
  close.addEventListener('click', clearSelection);
  header.append(element('span', 'eyebrow', label), close);
  return header;
}

function renderItemDetails() {
  if (!state.selected) return;
  const node = state.index.nodes.get(state.selected), container = $('details');
  container.classList.add('has-selection'); container.replaceChildren(detailsTop(`${nodeKind(node).toUpperCase()} DETAILS`));
  const hero = element('div', 'selected-item-hero'), title = element('div');
  title.append(element('h2', '', node.name), element('div', 'item-id', node.id));
  hero.append(icon(node), title); container.append(hero);
  if (node.note) container.append(element('p', 'node-note', node.note));
  if (node.effectMetadata) {
    const metadata = element('details', 'ingredient-alternatives'); metadata.append(element('summary', 'alternative-label', 'Game effect data'));
    metadata.append(element('pre', 'loot-json', JSON.stringify(node.effectMetadata, null, 2))); container.append(metadata);
  }
  const incoming = state.activeIndex.incomingEdges.get(node.id) || [], outgoing = state.activeIndex.outgoingEdges.get(node.id) || [];
  const metrics = element('div', 'item-metrics');
  for (const [amount, label] of [[new Set(incoming.map(relationKey)).size, 'incoming'], [new Set(outgoing.map(relationKey)).size, 'outgoing'], [state.baseDegree.get(node.id)?.size || 0, 'neighbors']]) {
    const metric = element('span'); metric.append(element('b', '', number(amount)), document.createTextNode(label)); metrics.append(metric);
  }
  container.append(metrics);
  if (node.capabilities && Object.keys(node.capabilities).length) renderCapabilities(container, node.capabilities);
  for (const [direction, label, edges] of [['incoming', 'Incoming', incoming], ['outgoing', 'Outgoing', outgoing]]) {
    const section = element('section', 'direction-section'), heading = element('h3', 'direction-heading', label);
    heading.append(element('span', '', direction === 'incoming' ? '→ this node' : 'this node →')); section.append(heading);
    if (!edges.length) section.append(element('p', 'no-results', 'No visible relationships.'));
    appendRelationships(section, edges, direction); container.append(section);
  }
  container.append(element('p', 'recipe-footer', `Snapshot coverage from ${node.minVersion || state.graph.version}${node.maxVersion ? ` through ${node.maxVersion}` : ''}.`));
}

function renderCapabilities(container, capabilities) {
  const section = element('section', 'node-capabilities'); section.append(element('h3', '', 'Uses'));
  const food = capabilities.food;
  if (food) {
    const parts = [];
    if (food.nutrition !== undefined) parts.push(`${food.nutrition} hunger points`);
    if (food.saturation !== undefined) parts.push(`${food.saturation} saturation`);
    const label = capabilities.consumable && capabilities.playerConsumable !== false ? 'Edible' : 'Food for mobs';
    section.append(element('p', 'metadata-row', `${label}${parts.length ? ` · ${parts.join(' · ')}` : ''}`));
  }
  const consumable = capabilities.consumable;
  if (consumable) {
    const seconds = consumable.consume_seconds ?? consumable.consumeSeconds;
    const animation = String(consumable.animation || 'consume').replaceAll('_', ' ').toLowerCase();
    section.append(element('p', 'metadata-row', `${animation[0].toUpperCase() + animation.slice(1)}${seconds !== undefined ? ` · ${seconds}s` : ''}`));
  }
  if (capabilities.equippable) {
    const slot = capabilities.equippable.slot;
    section.append(element('p', 'metadata-row', `Equippable${slot ? ` · ${String(slot).replaceAll('_', ' ').toLowerCase()} slot` : ''}`));
  }
  if (capabilities.placeable) section.append(element('p', 'metadata-row', 'Placeable as a block'));
  for (const [key, label] of [['tool', 'Mining tool'], ['weapon', 'Weapon'], ['cookingFuel', 'Fuel for cooking stations'], ['brewingFuel', 'Brewing stand fuel'], ['playable', 'Playable in a jukebox']]) {
    if (capabilities[key]) section.append(element('p', 'metadata-row', label));
  }
  const metadata = element('details', 'ingredient-alternatives'); metadata.append(element('summary', 'alternative-label', 'Game item capabilities'));
  metadata.append(element('pre', 'loot-json', JSON.stringify(capabilities, null, 2))); section.append(metadata); container.append(section);
}

function appendRelationships(container, edges, direction) {
  const families = new Map();
  for (const edge of edges) {
    const path = relationshipPath(edge.type, edgeCategory(edge)), family = path[0], type = path.slice(1).join(' / ');
    if (!families.has(family)) families.set(family, new Map());
    const types = families.get(family);
    if (!types.has(type)) types.set(type, new Map());
    const records = types.get(type), id = relationKey(edge);
    if (!records.has(id)) records.set(id, []); records.get(id).push(edge);
  }
  for (const [family, types] of families) {
    const section = element('details', 'relation-family'); section.open = true;
    const summary = element('summary', '', family), count = [...types.values()].reduce((sum, records) => sum + records.size, 0);
    summary.append(element('span', '', number(count))); section.append(summary);
    let first = true;
    for (const [type, records] of types) {
      section.append(element('h4', 'relation-type-heading', type));
      for (const [id, recordEdges] of records) {
        const recipe = state.index.recipes.get(id), relation = state.index.relationships.get(id);
        if (recipe) section.append(recipeCard(recipe, first, direction));
        else if (relation) section.append(relationshipCard(relation, recordEdges, first));
        first = false;
      }
    }
    container.append(section);
  }
}

function relationshipCard(relation, edges, open = false) {
  const card = element('details', 'recipe-card'); card.open = open;
  const summary = element('summary', '', recipeType(relation.type).label);
  const opposite = edges[0] && (edges[0].source === state.selected ? edges[0].target : edges[0].source);
  const compostInput = relation.type === 'composting' ? relation.ingredients?.find(group => group.consumed !== false)?.items?.[0] : null;
  const context = compostInput ? `${state.index.nodes.get(compostInput)?.name || compostInput} · ${Math.round((relation.layerChance || 0) * 100)}%` : state.index.nodes.get(opposite)?.name || opposite;
  if (context) summary.append(element('span', 'recipe-summary-result', context));
  card.append(summary);
  function fillBody() {
    const body = element('div', 'recipe-body'); body.append(element('div', 'recipe-id', relation.id));
    if (relation.note) body.append(element('p', 'recipe-note', relation.note));
    if (relation.ingredients?.length || relation.results?.length) {
      if (relation.ingredients?.length) body.append(element('h4', '', 'INPUTS'));
      for (const group of relation.ingredients || []) body.append(ingredientRows(group));
      if (relation.results?.length) body.append(element('h4', '', 'OUTPUTS'));
      for (const output of relation.results || []) body.append(ingredientRows({ items: [output.item || output.nodeId], count: output.count, components: output.components }));
    } else {
      for (const [label, refs] of [['INPUTS', relation.inputs], ['OUTPUTS', relation.outputs]]) {
        if (!refs?.length) continue;
        body.append(element('h4', '', label));
        const row = element('div', 'ingredient-row');
        refs.slice(0, 8).forEach(ref => row.append(itemButton(typeof ref === 'string' ? ref : ref.nodeId))); body.append(row);
        if (refs.length > 8) {
          const more = element('details', 'ingredient-alternatives'); more.append(element('summary', 'alternative-label', `${refs.length - 8} more nodes`));
          const rest = element('div', 'ingredient-row'); refs.slice(8).forEach(ref => rest.append(itemButton(typeof ref === 'string' ? ref : ref.nodeId))); more.append(rest); body.append(more);
        }
      }
    }
    const pairs = [...new Map(edges.map(edge => [`${edge.source}>${edge.target}`, edge])).values()];
    body.append(element('h4', '', 'CONNECTIONS'));
    function pairRow(edge) {
      const row = element('div', 'ingredient-row'); row.append(itemButton(edge.source), element('span', 'alternative-label', '→'), itemButton(edge.target)); return row;
    }
    pairs.slice(0, 8).forEach(edge => body.append(pairRow(edge)));
    if (pairs.length > 8) {
      const more = element('details', 'ingredient-alternatives'); more.append(element('summary', 'alternative-label', `${number(pairs.length - 8)} more connections`));
      pairs.slice(8).forEach(edge => more.append(pairRow(edge))); body.append(more);
    }
    const loot = relation.loot || (relation.sourceLootTable || relation.conditions?.some?.(entry => entry?.value) || relation.modifiers?.some?.(entry => entry?.value) ? relation : null);
    if (loot) renderLoot(body, loot);
    else if (relation.conditions) {
      body.append(element('h4', '', 'CONDITIONS'));
      for (const condition of Array.isArray(relation.conditions) ? relation.conditions : [relation.conditions]) {
        body.append(element('p', 'metadata-row', typeof condition === 'string' ? condition : JSON.stringify(condition)));
      }
    }
    if (relation.layerChance !== undefined) body.append(element('p', 'recipe-note', `${Math.round(relation.layerChance * 100)}% chance of a successful compost layer after the first addition · ${relation.layersRequired || 7} successful layers per Bone Meal.`));
    const ignored = new Set(['id', 'name', 'type', 'category', 'minVersion', 'maxVersion', 'note', 'raw', 'source', 'sourceClass', 'gameClass', 'code', 'ingredients', 'results', 'inputs', 'outputs', 'loot', 'item', 'sourceLootTable', 'resolvedLootTable', 'entryPath', 'conditions', 'modifiers', 'selection', 'rawEntry', 'conditional', 'unmodifiedItem', 'layerChance', 'layersRequired', 'layerProviderId', 'layerProvider', 'tag']);
    for (const [key, value] of Object.entries(relation)) {
      if (ignored.has(key) || value === null || value === undefined) continue;
      const row = element('div', 'metadata-row'); row.append(element('b', '', `${key.replaceAll('_', ' ').replace(/([a-z])([A-Z])/g, '$1 $2')}: `), document.createTextNode(typeof value === 'object' ? JSON.stringify(value) : String(value))); body.append(row);
    }
    body.append(element('p', 'recipe-footer', `Coverage from ${relation.minVersion || state.version}${relation.maxVersion ? ` through ${relation.maxVersion}` : ''}`)); card.append(body);
  }
  card.addEventListener('toggle', () => { if (card.open && card.childElementCount === 1) fillBody(); }); if (open) fillBody();
  return card;
}

function renderLoot(body, loot) {
  const readable = value => String(value || '').replaceAll('minecraft:', '').replaceAll('_', ' ');
  const amount = value => typeof value === 'number' ? String(value) : value?.min !== undefined && value?.max !== undefined ? `${value.min}–${value.max}` : value?.n !== undefined ? `binomial (${value.n}, ${value.p})` : 'game-dependent';
  if (loot.conditions?.length) {
    body.append(element('h4', '', 'CONDITIONS'));
    for (const { value } of loot.conditions) {
      const type = value.type || value.condition;
      let description = readable(type);
      if (type?.endsWith('killed_by_player')) description = 'Requires a kill credited to a player';
      else if (type?.endsWith('random_chance') && typeof value.chance === 'number') description = `${Math.round(value.chance * 10000) / 100}% random chance`;
      else if (type?.endsWith('match_tool')) description = 'Requires a matching tool or tool enchantment';
      else if (type?.endsWith('block_state_property')) description = `Requires a matching ${readable(value.block)} block state`;
      else if (type?.endsWith('entity_properties')) description = `Requires matching ${readable(value.entity || 'entity')} properties`;
      else if (type?.endsWith('survives_explosion')) description = 'Must survive an explosion';
      body.append(element('p', 'metadata-row', description));
    }
  }
  if (loot.modifiers?.length) {
    body.append(element('h4', '', 'COUNTS & MODIFIERS'));
    for (const { value } of loot.modifiers) {
      const type = value.type || value.function;
      let description = readable(type);
      if (type?.endsWith('set_count')) description = `Count: ${amount(value.count)}${value.add ? ' added to the current count' : ''}`;
      else if (type?.endsWith('enchanted_count_increase')) description = `${readable(value.enchantment || 'looting')} count bonus: ${amount(value.count)} per level`;
      else if (type?.endsWith('set_components')) description = `Item components: ${componentDescription({ components: value.components })}`;
      else if (type?.endsWith('enchant_randomly')) description = 'May receive a random enchantment';
      else if (type?.endsWith('enchant_with_levels')) description = `Enchanting level: ${amount(value.levels)}`;
      body.append(element('p', 'metadata-row', description));
    }
  }
  const choices = (loot.selection || []).filter(value => value.type !== 'pool');
  if (choices.length) body.append(element('p', 'recipe-footer', `Relative selection weights: ${choices.map(value => `${value.weight ?? 1}${value.quality ? ` (quality ${value.quality})` : ''}`).join(' → ')}. Conditions and luck can affect selection.`));
  const raw = element('details', 'ingredient-alternatives'); raw.append(element('summary', 'alternative-label', 'Game loot conditions & data'));
  const pre = element('pre', 'loot-json', JSON.stringify({ sourceLootTable: loot.sourceLootTable, resolvedLootTable: loot.resolvedLootTable, conditions: loot.conditions, modifiers: loot.modifiers, selection: loot.selection, rawEntry: loot.rawEntry }, null, 2));
  raw.append(pre); body.append(raw);
}

function ingredientRows(group) {
  const row = element('div', 'ingredient-row');
  const minimum = group.count ?? 1;
  const amount = group.maxCount && group.maxCount !== minimum ? `${minimum}–${group.maxCount}` : String(minimum);
  const qualifier = group.optional ? ' (optional)' : group.consumed === false ? ' (retained)' : '';
  row.append(element('span', 'alternative-label', `${amount}×${group.role ? ` ${group.role}` : ''}${qualifier}`));
  const alternatives = group.items || (group.item ? [group.item] : []);
  const visible = alternatives.slice(0, 5);
  for (const [i, id] of visible.entries()) {
    if (i) row.append(element('span', 'alternative-label', 'or'));
    row.append(itemButton(id));
  }
  if (alternatives.length > visible.length) {
    const more = element('details', 'ingredient-alternatives');
    const summary = element('summary', 'alternative-label', `+${alternatives.length - visible.length} alternatives${group.tag ? ` · #${group.tag.replace('minecraft:', '')}` : ''}`);
    more.append(summary);
    const rest = element('div', 'ingredient-row');
    alternatives.slice(visible.length).forEach(id => rest.append(itemButton(id)));
    more.append(rest); row.append(more);
  } else if (group.tag) row.append(element('span', 'alternative-label', `#${group.tag.replace('minecraft:', '')}`));
  if (group.components || group.predicates) row.append(element('span', 'alternative-label', componentDescription(group)));
  return row;
}

function componentDescription(value) {
  const components = value.components || value.predicates || {};
  const parts = Object.entries(components).map(([key, val]) => {
    const name = key.replace('minecraft:', '').replaceAll('_', ' ');
    if (key.endsWith('potion_contents')) {
      const potion = typeof val === 'string' ? val : val.potion || val.potions;
      return potion ? (Array.isArray(potion) ? potion.join(', ') : potion).replaceAll('minecraft:', '').replaceAll('_', ' ') : name;
    }
    return `${name}: ${typeof val === 'string' || typeof val === 'number' ? val : JSON.stringify(val)}`;
  });
  return parts.join(' · ');
}

function recipeCard(recipe, open = false, direction = 'outgoing') {
  const card = element('details', 'recipe-card'); card.open = open;
  const info = recipeType(recipe.type); card.style.setProperty('--type-color', info.color);
  const summary = element('summary');
  const result = recipe.results?.[0];
  if (result) summary.append(icon(state.index.nodes.get(result.item)));
  summary.append(element('span', 'type-dot'), element('span', '', info.label));
  const resultLabel = [result && componentDescription(result), recipe.bannerPattern?.replace('minecraft:', '').replaceAll('_', ' '), direction === 'outgoing' && result ? state.index.nodes.get(result.item)?.name || result.item : ''].filter(Boolean).join(' · ');
  if (resultLabel) { summary.append(element('span', 'recipe-summary-result', resultLabel)); summary.title = `${info.label} · ${resultLabel}`; }
  card.append(summary);
  const fillBody = () => {
  const body = element('div', 'recipe-body');
  body.append(element('div', 'recipe-id', recipe.id));
  const notes = [recipe.note, ...(Array.isArray(recipe.notes) ? recipe.notes : recipe.notes ? [recipe.notes] : [])].filter(Boolean);
  if (recipe.dynamic && !notes.length) notes.push('The result depends on the input item’s contents or components.');
  if (notes.length) body.append(element('p', 'recipe-note', notes.join(' ')));
  if (recipe.pattern && recipe.key) {
    const grid = element('div', 'recipe-grid'); grid.setAttribute('aria-label', 'Crafting grid');
    for (let row = 0; row < 3; row++) for (let column = 0; column < 3; column++) {
      const slot = element('div');
      const symbol = recipe.pattern[row]?.[column], group = recipe.key[symbol];
      const id = group?.items?.[0];
      if (id) { slot.append(icon(state.index.nodes.get(id))); slot.title = `${state.index.nodes.get(id)?.name || id}${group.items.length > 1 ? ' (any listed alternative)' : ''}`; }
      grid.append(slot);
    }
    body.append(grid);
  }
  body.append(element('h4', '', 'INGREDIENTS'));
  for (const group of recipe.ingredients || []) body.append(ingredientRows(group));
  if (!recipe.ingredients?.length) body.append(element('p', 'no-results', 'Ingredients are determined by the game at runtime.'));
  body.append(element('h4', '', recipe.resultAlternatives ? 'RESULT · ONE OF THESE' : 'RESULT'));
  const results = element('div', 'ingredient-row');
  for (const output of recipe.results || []) {
    const row = element('div', 'ingredient-row');
    row.append(element('span', 'alternative-label', `${output.count ?? 1}×`), itemButton(output.item));
    const components = componentDescription(output);
    if (components) row.append(element('span', 'alternative-label', components));
    results.append(row);
  }
  body.append(results);
  if (recipe.resultFromIngredient !== undefined) body.append(element('p', 'recipe-note', 'The result keeps the identity of the input in the base ingredient group; alternatives are not produced together.'));
  if (recipe.experience !== undefined || recipe.cookingtime !== undefined || recipe.cookingTime !== undefined) {
    const parts = [];
    const ticks = recipe.cookingtime ?? recipe.cookingTime;
    if (ticks !== undefined) parts.push(`${ticks / 20}s cooking time`);
    if (recipe.experience !== undefined) parts.push(`${recipe.experience} XP`);
    body.append(element('p', 'recipe-footer', parts.join(' · ')));
  }
  body.append(element('div', 'recipe-footer', `Recipe relationship · ${recipe.type} · from ${recipe.minVersion || state.graph.version}${recipe.maxVersion ? ` to ${recipe.maxVersion}` : ''}`));
  card.append(body);
  };
  // Large hubs have hundreds of recipes; build their contents only when opened.
  card.addEventListener('toggle', () => { if (card.open && card.childElementCount === 1) fillBody(); });
  if (open) fillBody();
  return card;
}

function selectEdge(group) {
  state.selectedEdge = group.key;
  const container = $('details'); container.classList.add('has-selection'); container.replaceChildren(detailsTop('CONNECTION DETAILS'));
  const illustration = element('div', 'edge-illustration');
  illustration.append(itemButton(group.source), element('span', '', '→'), itemButton(group.target));
  container.append(illustration, element('h2', 'edge-detail-title', relationshipPath(group.type, group.category).join(' / ')));
  container.append(element('p', 'edge-explanation', `${number(group.edges.length)} connections share this curve. All underlying relationships are preserved below.`));
  appendRelationships(container, group.edges, 'outgoing'); requestDraw();
  syncMobileSelection();
}

function requestDraw() {
  if (!state.frame) state.frame = requestAnimationFrame(() => { state.frame = null; draw(); });
}

function screenToWorld(x, y) {
  return { x: (x - state.camera.x) / state.camera.zoom, y: (y - state.camera.y) / state.camera.zoom };
}

function viewport() {
  const a = screenToWorld(-70, -70), b = screenToWorld(state.width + 70, state.height + 70);
  return { left: a.x, top: a.y, right: b.x, bottom: b.y };
}

function overlaps(a, b) {
  return a && a.left <= b.right && a.right >= b.left && a.top <= b.bottom && a.bottom >= b.top;
}

function pathCurve(c) {
  ctx.beginPath(); ctx.moveTo(c.ax, c.ay);
  if (c.loop) ctx.bezierCurveTo(c.cx, c.cy, c.dx, c.dy, c.bx, c.by);
  else ctx.quadraticCurveTo(c.cx, c.cy, c.bx, c.by);
}

function nodePath(node, position, radius) {
  ctx.beginPath();
  if (nodeKind(node) === 'category') {
    for (let side = 0; side < 6; side++) {
      const angle = side * Math.PI / 3;
      const x = position.x + Math.cos(angle) * radius, y = position.y + Math.sin(angle) * radius;
      if (side) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    }
    ctx.closePath();
  } else ctx.arc(position.x, position.y, radius, 0, Math.PI * 2);
}

function focusGeometry(id) {
  const focused = state.selected && state.mode !== 'all' && state.view.depth.get(id) <= 1;
  return { focused, radius: focused ? Math.max(18, (mobile.matches ? 20 : 14) / state.camera.zoom) : 18,
    imageSize: focused ? Math.max(26, (mobile.matches ? 26 : 18) / state.camera.zoom) : 26 };
}

function drawEdge(group, highlighted = false) {
  if (!group.curve) return;
  const c = { ...group.curve };
  // Focus icons keep a minimum screen size, so visible curve ends follow their circles.
  for (const [id, end, controlX, controlY] of [[group.source, 'a', c.cx, c.cy], [group.target, 'b', c.loop ? c.dx : c.cx, c.loop ? c.dy : c.cy]]) {
    const geometry = focusGeometry(id);
    if (!geometry.focused) continue;
    const p = state.positions.get(id), dx = controlX - p.x, dy = controlY - p.y, distance = Math.hypot(dx, dy) || 1;
    c[`${end}x`] = p.x + dx / distance * geometry.radius;
    c[`${end}y`] = p.y + dy / distance * geometry.radius;
  }
  const selected = state.selectedEdge === group.key || state.hover?.edge === group;
  ctx.globalAlpha = selected ? 1 : highlighted ? .85 : state.mode === 'nearby' && state.selected ? .12 : state.selected ? .05 : .16;
  ctx.strokeStyle = group.color;
  ctx.lineWidth = (selected ? 2.3 : highlighted ? 1.3 : .7) / state.camera.zoom;
  pathCurve(c); ctx.stroke();
  if (state.camera.zoom > .42 || highlighted || selected) {
    const dx = c.bx - (c.loop ? c.dx : c.cx), dy = c.by - (c.loop ? c.dy : c.cy);
    const angle = Math.atan2(dy, dx), size = Math.max(5, 4.5 / state.camera.zoom);
    ctx.fillStyle = group.color; ctx.beginPath(); ctx.moveTo(c.bx, c.by);
    ctx.lineTo(c.bx - Math.cos(angle - .42) * size, c.by - Math.sin(angle - .42) * size);
    ctx.lineTo(c.bx - Math.cos(angle + .42) * size, c.by - Math.sin(angle + .42) * size);
    ctx.closePath(); ctx.fill();
  }
}

function nodeImage(node) {
  if (!node.icon?.startsWith('assets/')) return null;
  if (!state.images.has(node.id)) {
    const img = new Image(); img.src = iconSource(node);
    img.addEventListener('load', requestDraw, { once: true });
    state.images.set(node.id, img);
  }
  const image = state.images.get(node.id);
  return image.complete && image.naturalWidth ? image : null;
}

function draw() {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, state.width, state.height);
  if (!state.view) return;
  const camera = state.camera, bounds = viewport();
  ctx.translate(camera.x, camera.y); ctx.scale(camera.zoom, camera.zoom);
  ctx.imageSmoothingEnabled = false;
  const highlightedEdges = [];
  for (const group of state.groups) {
    if (!overlaps(group.bounds, bounds)) continue;
    if (group.source === state.selected || group.target === state.selected || state.selectedEdge === group.key || state.hover?.edge === group) highlightedEdges.push(group);
    else drawEdge(group);
  }
  highlightedEdges.forEach(group => drawEdge(group, true));
  const visibleNodes = [], labels = [];
  for (const node of state.view.nodes) {
    const position = state.positions.get(node.id);
    if (!position || position.x < bounds.left || position.x > bounds.right || position.y < bounds.top || position.y > bounds.bottom) continue;
    visibleNodes.push({ node, position });
  }
  for (const { node, position } of visibleNodes) {
    const selected = node.id === state.selected, hovered = state.hover?.node?.id === node.id;
    const highlighted = selected || hovered || state.neighbors.has(node.id);
    ctx.globalAlpha = state.selected && !highlighted ? (state.view.depth.get(node.id) === 2 ? .28 : .1) : 1;
    const geometry = focusGeometry(node.id);
    const showImage = camera.zoom >= .45 || selected || hovered || geometry.focused;
    const radius = showImage ? geometry.radius : Math.max(3.5, 3 / camera.zoom);
    nodePath(node, position, radius);
    ctx.fillStyle = selected ? '#e2ecff' : showImage ? (nodeKind(node) === 'category' ? '#f3effc' : '#ffffff') : '#93a9c8'; ctx.fill();
    ctx.strokeStyle = selected ? '#3976d6' : hovered ? '#6b95ce' : '#d9e2ef';
    ctx.lineWidth = (selected || hovered ? 1.8 : .8) / camera.zoom; ctx.stroke();
    if (showImage) {
      const image = nodeImage(node);
      if (image) ctx.drawImage(image, position.x - geometry.imageSize / 2, position.y - geometry.imageSize / 2, geometry.imageSize, geometry.imageSize);
      else { ctx.fillStyle = '#b8c9e0'; ctx.fillRect(position.x - 5, position.y - 5, 10, 10); }
    }
    if (camera.zoom >= .85 || selected || hovered || geometry.focused) labels.push({ node, position, highlighted, radius, focused: geometry.focused });
  }
  // Labels get a small solid backing so recipe lines never obscure the text.
  for (const { node, position, highlighted, radius, focused } of labels) {
    const size = Math.max(11, 11 / camera.zoom);
    ctx.font = `${highlighted ? '600 ' : ''}${size}px "Segoe UI",sans-serif`; ctx.textAlign = 'center';
    const width = ctx.measureText(node.name).width, y = focused ? position.y + radius + 6 / camera.zoom + size : position.y + 30 + size * .25;
    ctx.globalAlpha = state.selected && !highlighted ? (state.view.depth.get(node.id) === 2 ? .28 : .1) : .92;
    ctx.fillStyle = '#f8fafc'; ctx.fillRect(position.x - width / 2 - 4, y - size + 1, width + 8, size + 4);
    ctx.fillStyle = highlighted ? '#496688' : '#8395ae'; ctx.fillText(node.name, position.x, y);
  }
  ctx.textAlign = 'left'; ctx.globalAlpha = 1;
  $('zoom-level').textContent = `${Math.round(camera.zoom * 100)}%`;
  $('interaction-hint').textContent = !state.selected ? 'Drag to pan · Scroll to zoom · Select a node to inspect its connections' : 'Drag to pan · Scroll to zoom · Select a distinct connection of this node';
}

function fit() {
  if (!state.view?.nodes.length) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const nodes = state.mode === 'direct' && state.selected ? state.view.nodes.filter(node => state.view.depth.get(node.id) <= 1) : state.view.nodes;
  for (const node of nodes) {
    const p = state.positions.get(node.id); if (!p) continue;
    minX = Math.min(minX, p.x - 45); maxX = Math.max(maxX, p.x + 45);
    minY = Math.min(minY, p.y - 45); maxY = Math.max(maxY, p.y + 45);
  }
  const availableWidth = availableCanvasWidth();
  const top = mobile.matches ? 130 : 85, bottom = mobile.matches ? (state.selected || state.selectedEdge ? 140 : 75) : 65;
  const width = Math.max(1, availableWidth - 70), height = Math.max(1, state.height - top - bottom);
  const zoom = Math.min(1.4, width / (maxX - minX || 1), height / (maxY - minY || 1));
  state.camera = { zoom, x: availableWidth / 2 - (minX + maxX) / 2 * zoom, y: (state.height + top - bottom) / 2 - (minY + maxY) / 2 * zoom };
  requestDraw();
}

function zoomAt(factor, x = availableCanvasWidth() / 2, y = state.height / 2) {
  const world = screenToWorld(x, y), zoom = Math.max(.025, Math.min(5, state.camera.zoom * factor));
  state.camera.zoom = zoom; state.camera.x = x - world.x * zoom; state.camera.y = y - world.y * zoom;
  requestDraw();
}

function localPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function hitNode(point) {
  if (!state.view) return null;
  const world = screenToWorld(point.x, point.y);
  let closest = null, distance = Infinity;
  for (const node of state.view.nodes) {
    const p = state.positions.get(node.id); if (!p) continue;
    const geometry = focusGeometry(node.id), radius = geometry.focused ? geometry.radius + 2 / state.camera.zoom : Math.max(20, (mobile.matches ? 22 : 9) / state.camera.zoom);
    const d = Math.hypot(p.x - world.x, p.y - world.y);
    if (d < radius && d < distance) { closest = node; distance = d; }
  }
  return closest;
}

function curvePoint(c, t) {
  const u = 1 - t;
  if (c.loop) return { x: u ** 3 * c.ax + 3 * u ** 2 * t * c.cx + 3 * u * t ** 2 * c.dx + t ** 3 * c.bx, y: u ** 3 * c.ay + 3 * u ** 2 * t * c.cy + 3 * u * t ** 2 * c.dy + t ** 3 * c.by };
  return { x: u * u * c.ax + 2 * u * t * c.cx + t * t * c.bx, y: u * u * c.ay + 2 * u * t * c.cy + t * t * c.by };
}

function segmentDistance(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}

function hitEdge(point) {
  if (!state.selected || state.camera.zoom < .45) return null;
  const p = screenToWorld(point.x, point.y), tolerance = 5 / state.camera.zoom;
  const bounds = { left: p.x - tolerance, right: p.x + tolerance, top: p.y - tolerance, bottom: p.y + tolerance };
  const candidates = [];
  for (const group of state.groups) {
    if (group.source !== state.selected && group.target !== state.selected) continue;
    if (!group.curve || !overlaps(group.bounds, bounds)) continue;
    let a = curvePoint(group.curve, 0), distance = Infinity;
    for (let i = 1; i <= 16; i++) {
      const b = curvePoint(group.curve, i / 16); distance = Math.min(distance, segmentDistance(p, a, b)); a = b;
    }
    candidates.push({ group, distance: distance * state.camera.zoom, incident: group.source === state.selected || group.target === state.selected });
  }
  return pickEdge(candidates, state.camera.zoom, state.selected);
}

function showHover(point) {
  const node = hitNode(point), edge = node ? null : hitEdge(point);
  state.hover = node ? { node } : edge ? { edge } : null;
  canvas.style.cursor = node || edge ? 'pointer' : 'grab';
  const tooltip = $('tooltip'); tooltip.hidden = !state.hover;
  if (state.hover) {
    tooltip.replaceChildren();
    if (node) tooltip.append(document.createTextNode(node.name), element('small', '', `${state.baseDegree.get(node.id)?.size || 0} neighbors · Click to inspect`));
    else tooltip.append(document.createTextNode(`${state.index.nodes.get(edge.source).name} → ${state.index.nodes.get(edge.target).name}`), element('small', '', `${recipeType(edge.type).label} · ${edge.recipeIds.size + edge.relationIds.size} relationships`));
    tooltip.style.left = `${Math.max(8, Math.min(point.x + 15, state.width - 255))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(point.y + 15, state.height - 68))}px`;
  }
  requestDraw();
}

canvas.addEventListener('wheel', event => {
  event.preventDefault(); const point = localPoint(event);
  zoomAt(Math.exp(-event.deltaY * .0015), point.x, point.y); $('tooltip').hidden = true;
}, { passive: false });

canvas.addEventListener('pointerdown', event => {
  if (!state.ready || event.button > 0) return;
  canvas.setPointerCapture(event.pointerId);
  const point = localPoint(event); state.pointers.set(event.pointerId, point);
  if (state.pointers.size === 2) {
    const [a, b] = [...state.pointers.values()], middle = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    state.gesture = { pinch: true, distance: Math.hypot(a.x - b.x, a.y - b.y), zoom: state.camera.zoom, world: screenToWorld(middle.x, middle.y), moved: true };
  } else if (state.pointers.size === 1) {
    const node = event.shiftKey ? null : hitNode(point);
    state.gesture = { start: point, previous: point, node, moved: false };
  }
  canvas.classList.add('dragging'); $('tooltip').hidden = true;
});

canvas.addEventListener('pointermove', event => {
  const point = localPoint(event);
  if (!state.pointers.has(event.pointerId)) { if (state.ready) showHover(point); return; }
  state.pointers.set(event.pointerId, point);
  const gesture = state.gesture;
  if (gesture?.pinch && state.pointers.size === 2) {
    const [a, b] = [...state.pointers.values()], middle = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const zoom = Math.max(.025, Math.min(5, gesture.zoom * Math.hypot(a.x - b.x, a.y - b.y) / Math.max(gesture.distance, 1)));
    state.camera = { zoom, x: middle.x - gesture.world.x * zoom, y: middle.y - gesture.world.y * zoom };
  } else if (gesture && !gesture.pinch) {
    if (Math.hypot(point.x - gesture.start.x, point.y - gesture.start.y) > 4) gesture.moved = true;
    if (gesture.moved) {
      const dx = point.x - gesture.previous.x, dy = point.y - gesture.previous.y;
      if (gesture.node) {
        const p = state.positions.get(gesture.node.id); p.x += dx / state.camera.zoom; p.y += dy / state.camera.zoom;
        state.groups.filter(group => group.source === gesture.node.id || group.target === gesture.node.id).forEach(updateCurve);
      } else { state.camera.x += dx; state.camera.y += dy; }
    }
    gesture.previous = point;
  }
  requestDraw();
});

function pointerEnd(event) {
  const gesture = state.gesture, point = localPoint(event);
  state.pointers.delete(event.pointerId);
  if (!state.pointers.size) {
    canvas.classList.remove('dragging'); state.gesture = null;
    if (event.type === 'pointerup' && gesture && !gesture.moved && !gesture.pinch) {
      if (gesture.node) selectNode(gesture.node.id);
      else { const edge = hitEdge(point); if (edge) selectEdge(edge); else clearSelection(); }
    }
  } else if (state.pointers.size === 1) {
    const remaining = [...state.pointers.values()][0]; state.gesture = { start: remaining, previous: remaining, node: null, moved: true };
  }
}
canvas.addEventListener('pointerup', pointerEnd);
canvas.addEventListener('pointercancel', pointerEnd);
canvas.addEventListener('pointerleave', () => { if (!state.pointers.size) { state.hover = null; $('tooltip').hidden = true; requestDraw(); } });
canvas.addEventListener('keydown', event => {
  const pan = { ArrowLeft: [80, 0], ArrowRight: [-80, 0], ArrowUp: [0, 80], ArrowDown: [0, -80] }[event.key];
  if (pan) { event.preventDefault(); state.camera.x += pan[0]; state.camera.y += pan[1]; requestDraw(); }
  else if (['+', '='].includes(event.key)) { event.preventDefault(); zoomAt(1.25); }
  else if (event.key === '-') { event.preventDefault(); zoomAt(.8); }
  else if (event.key === 'Escape') clearSelection();
});
document.addEventListener('keydown', event => {
  if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) { event.preventDefault(); if (mobile.matches) openMobilePanel('search'); else $('search').focus(); }
});
$('search').addEventListener('input', event => { state.query = event.target.value; state.limit = 30; renderSearch(); });
$('search').addEventListener('focus', () => { if (state.base) renderSearch(); });
$('search').addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); $('item-list').querySelector('.item-row')?.click(); $('search-results').hidden = true; }
  if (event.key === 'ArrowDown') { event.preventDefault(); $('item-list').querySelector('.item-row')?.focus(); }
  if (event.key === 'Escape') { $('search-results').hidden = true; $('search').blur(); }
});
document.addEventListener('pointerdown', event => { if (!event.target.closest('.search-container')) $('search-results').hidden = true; });
$('version').addEventListener('change', event => { state.version = event.target.value; updateView(true); });
$('toggle-types').addEventListener('click', () => {
  if (!state.graph) return;
  state.types = state.types.size ? new Set() : new Set(state.graph.edges.map(filterKey)); updateView();
});
$('self-loops').addEventListener('change', event => { state.showSelfLoops = event.target.checked; updateView(); });
$('toggle-nodes').addEventListener('click', () => {
  if (!state.graph) return;
  state.kinds = state.kinds.size ? new Set() : new Set(state.graph.nodes.map(nodeKind)); updateView(true);
});
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
  state.mode = button.dataset.mode; state.selectedEdge = null; updateView(true);
}));
$('zoom-in').addEventListener('click', () => zoomAt(1.3));
$('zoom-out').addEventListener('click', () => zoomAt(1 / 1.3));
$('fit').addEventListener('click', fit);
$('relayout').addEventListener('click', relayout);

new ResizeObserver(entries => {
  const rect = entries[0].contentRect;
  const oldWidth = state.width, oldHeight = state.height;
  state.width = rect.width; state.height = rect.height;
  const dpr = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
  state.camera.x += (rect.width - oldWidth) / 2; state.camera.y += (rect.height - oldHeight) / 2;
  if (state.ready && !state.focusWorker && (mobile.matches || (state.mode !== 'all' && state.selected))) fit();
  requestDraw();
}).observe(canvas);

async function load() {
  try {
    const response = await fetch('data/graph.json');
    if (!response.ok) throw new Error(`Graph data returned HTTP ${response.status}.`);
    state.graph = validateGraph(await response.json()); state.index = indexGraph(state.graph);
    state.version = state.graph.version;
    state.types = new Set([...state.graph.recipes.map(record => `recipe:${record.type}`), ...(state.graph.relationships || []).map(record => filterKey(record))]);
    state.kinds = new Set(state.graph.nodes.map(nodeKind));
    state.emptyDetails = $('details').firstElementChild.cloneNode(true);
    const versions = [...new Set([...(state.graph.versions || []), state.graph.version])];
    $('version').replaceChildren(...versions.map(version => { const option = element('option', '', version); option.value = version; return option; }));
    $('version').value = state.version; $('version').disabled = false; $('search').disabled = false;
    $('data-note').textContent = `Game-derived data · Java ${state.version}`;
    buildTypeFilters(); populateStarters();
    $('loading-text').textContent = `Arranging ${number(state.graph.nodes.length)} nodes and ${number(state.graph.edges.length)} connections…`;
    const worker = new Worker('graph-worker.js', { type: 'module' });
    const layout = await new Promise((resolve, reject) => {
      worker.onmessage = event => event.data.error ? reject(new Error(event.data.error)) : resolve(event.data);
      worker.onerror = () => reject(new Error('The graph layout worker could not load. Start the local server and reload the page.'));
      worker.postMessage({ nodes: state.graph.nodes.map(({ id, name }) => ({ id, name })), edges: state.graph.edges.map(({ source, target }) => ({ source, target })) });
    });
    worker.terminate(); state.positions = new Map(layout.positions.map(position => [position.id, position]));
    state.fullPositions = state.positions;
    state.ready = true; $('loading').hidden = true; updateView(true);
    $('mobile-search').disabled = false; $('mobile-filters').disabled = false;
    let initialId;
    try { initialId = decodeURIComponent(location.hash.slice(1)); } catch { initialId = ''; }
    if (state.index.nodes.has(initialId)) selectNode(initialId, true);
  } catch (error) {
    console.error(error); $('loading').hidden = false; $('loading').querySelector('h2').textContent = 'The atlas could not open';
    $('loading-text').textContent = `${error.message} Open this app through the local server, rather than double-clicking the HTML file.`;
    $('loading').querySelector('.loading-cube').style.animation = 'none';
  }
}

load();
