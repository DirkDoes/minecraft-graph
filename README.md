# Minecraft Atlas

An interactive knowledge graph for **Minecraft Java Edition 26.3**: items, categories, mobs, status effects, structures, biomes, dimensions, recipes, loot, gathering and interactions. The latest stable release was verified against Mojang's version manifest on 11 October 2026; the installed client jar matches its official SHA1.

## Open the app

Open the hosted app at **[dirkdoes.github.io/minecraft-graph](https://dirkdoes.github.io/minecraft-graph/)**. GitHub Pages publishes the static files from the root of `main`; `.nojekyll` skips Jekyll processing. Pushing changes to `main` updates the hosted site.

To run it locally:

With Node.js 22 or newer, run this from the project folder:

```powershell
node server.mjs
```

Open **http://127.0.0.1:3000**. `npm start` does the same thing. No package installation, Minecraft login, or internet connection is needed to use the app. Keep the terminal running; press Ctrl+C to stop. Use localhost rather than opening `index.html` directly, because the browser needs to load modules, graph data, and a layout worker.

Search any node: results identify its kind, including structures, biomes and dimensions. Categories have hexagonal badges and graph nodes; structures are rounded squares, and other nodes are circular. Selecting a search result opens **Direct**, arranges its neighborhood, and fits it on screen. Drag the canvas to pan, scroll to zoom, and drag a node to move it. `/` focuses search; arrows pan and plus/minus zoom on the canvas. **All** shows the full graph; **Direct** hides unrelated nodes and connections; **Nearby** adds a faded second hop. Both local views rearrange automatically. **Rearrange** lays out the visible graph again, and **Fit** adjusts its zoom. Select a node before picking one of its incident edges; ambiguous overlapping curves cannot be picked.

On phones, the graph fills the screen. **Search nodes** and **Filters** open touch-sized bottom panels; selecting a search result returns to the graph. Tap the selected node's **Details** strip to inspect relationships, then close the panel to continue exploring with the selection intact. Drag to pan and pinch to zoom. Desktop sidebars keep their existing layout.

The left sidebar contains the version and checkbox trees. **Recipes → Crafting** includes shaped, shapeless and special crafting recipes; other stations have their own branches. Disabling a parent disables every child. Membership, Gathering, Loot, Uses, Status effects, Spawning, Interactions, Experience and World generation are separate roots. World generation separates structure contents and biome rules; structure loot appears under Loot. Spawn eggs, buckets, constructed mobs and status-effect spawning can be filtered separately. **Show self-loops** starts off; it hides edges from a node to itself without deleting their records. Node filters include every represented kind, including **Other entities** for the Experience Orb. Loose nodes keep their grid layout without a surrounding box or title.

## Included data

| Inventory | Count |
| --- | ---: |
| Registered item IDs, including Air | 1,658 |
| Official item-tag categories | 236 |
| Actual mob types | 90 |
| Additional blocks without inventory items | 73 |
| Registered status effects plus Burning | 41 |
| Additional non-mob entities (Experience Orb) | 1 |
| Structure nodes (52 registered, 10 feature sites, 3 End fight sites) | 65 |
| Registered biomes | 67 |
| Dimensions | 3 |
| Official recipe JSON files | 2,042 |
| Additional workstation operations | 1,140 |
| Total recipe records | 3,182 |
| Original directed item recipe connections | 25,594 |
| Generic relationship records | 13,830 |
| Total directed connections | 55,198 |

The inventory comes from the game's own data generator and item registry, so unobtainable items and items without recipes remain present. Every recipe JSON in the verified client is retained and mapped, including crafting, cooking, stonecutting, smithing, brewing, and dynamic crafting serializers. Nested item tags expand to their actual alternatives. Shaped layouts, input/output quantities, optional ingredients, potion predicates, and component-dependent conditions remain attached to recipe records.

Loom, anvil, grindstone, and cartography operations are separately labeled additions derived from game tags, default components, and audited menu logic. They include all 42 usable loom patterns. Anvil renaming and enchanting-table rolls are outside item-production recipes.

Every nonempty official item tag becomes a category. Items point to their categories, nested categories point to their parents, and tagged recipe ingredients add category→result edges alongside every original item→result edge. For example, Oak Planks→Planks→Crafting Table supplements Oak Planks→Crafting Table. Identity recipes preserve their required matching input item.

Mob classification audits all 161 entity registry entries against the actual `Mob` base class, yielding 90 mobs including those without loot. Death-table edges retain inherited predicates, alternative ordering, weights, rolls, counts and modifiers. Conditional raw/cooked drops and enchanted books are mapped separately. Creeper music-disc drops use the game's allowed tag and killing-source conditions, rather than every music disc. Audited runtime exceptions cover witch-held drinking potions and charged-creeper head drops. Arbitrary equipment or items picked up by mobs are not enumerated.

Gathering includes every one of the 1,201 block loot tables, all compostable item components and their exact layer providers, fishing, piglin bartering, villager gifts, passive animal drops, shearing, brushing, honey/berry harvesting, pumpkin carving, rooted-dirt tilling, milking, mooshroom stews, source-block buckets, water bottles, dragon breath, mob capture, goat horns and all six archaeology tables. Tools, component/state restrictions and random branches remain attached to the relationship. Composting requires seven successful layers before producing one Bone Meal; an item's layer chance is not a chance to directly produce Bone Meal.

Recipe edges mean **this ingredient participates in this complete recipe**, with arrows from ingredient to result. Other edges express membership, a possible drop, or participation in a complete gathering interaction. An input alone does not imply a guaranteed output. Opposite directions are separate edges. Parallel connections may share a drawn curve; selecting it exposes all underlying records. Item nodes represent registry IDs: potion contents, enchantments, durability, and banner patterns are conditions/components rather than extra nodes for every possible stack.

All 40 registered status effects have official icons and game-derived metadata; **Burning** is explicitly labeled as an entity state rather than a registered effect. Conditional links cover food and potion effects, tipped arrows, beacons and conduits, mob attacks and auras, immunity, effect removal, death protection and effect consequences. A potion→effect edge requires its recorded contents; water and empty potion variants do not grant every effect. Witch attacks link to the appropriate potion item with its contents, then the item links to the effect. Oozing→Slime and Infested→Silverfish are effect consequences, rather than bottle→mob edges. Oozing brewing uses a Slime Block, and curing a Zombie Villager uses Weakness plus an ordinary Golden Apple.

Uses and spawning include actual spawn-egg and mob-bucket mappings, thrown eggs, constructed golems/Withers, Creaking Hearts, egg blocks, feeding, breeding, taming, healing, equipment, fuels, mining rules, block transformations, copper waxing/weathering and tool-target interactions. Mob behaviors include conversions, infection, predators, repellents, pollination, hive use and copper golem statue activation. Bone Meal targets come from all registered `BonemealableBlock` implementations, and crop-growing links retain their conditional harvest loot. Edible, equippable and placeable capabilities appear in node details without inventing Player or action nodes. A food component used by mobs does not necessarily mean the player can eat the item. Multi-input requirements, alternatives, world state and game rules remain on the full relationship records.

Experience Orbs are non-mob entities. Conditional XP sources include qualifying mob kills, mining, all positive-XP furnace/blast-furnace/smoker recipes, breeding, fishing, Bottles o' Enchanting and grindstone disenchanting. Campfire cooking grants no XP, and mobs with zero death XP have no kill link. Living coral, coral fans (including wall states) and coral blocks point to the matching dead form when their placed water check fails; there is no reverse revival link. Coral targets and ordinary block XP ranges come directly from the registered game classes. Custom XP rules and the zero-XP mob exceptions are audited for 26.3.

World generation uses the game's structure definitions, reachable templates and pools, biome features, terrain material rules and biome sources. Structures point to their allowed biomes; biomes point to their dimensions. There is no direct structure-to-dimension shortcut. Structure blocks, container loot and archaeology stay attached to the structure. Natural terrain and decoration point from the biome to their possible blocks; a structure's contents alone never create a biome-to-block link. Structure-like decoration features such as monster rooms and geodes also have structure nodes.

Mob relationships distinguish **Generated residents**, **Spawner mobs** and **Natural spawning overrides** from ordinary **Biome spawning**. A fortress can have both Blaze spawner and natural-spawning links. Ancient City reaches Warden through Sculk Shrieker summoning, with its activation, warning and spawning conditions; Warden is not an initially generated city resident. Loot relationships preserve container/table attribution and conditional selection rules. These are possible outputs: terrain checks, random choices, template processors, height, difficulty and other recorded conditions still apply. Biome and dimension badges use representative game blocks, and structure badges use representative contents. The optional starter bonus chest is outside this structure inventory.

[data/provenance.json](data/provenance.json) records sources, checksum, counts, and coverage limits. [Mojang's release notes](https://www.minecraft.net/en-us/article/minecraft-java-edition-26-3) describe this version.

## Rendering and scale

The graph uses native Canvas rather than a DOM element for every edge. A Web Worker computes layout; drawing is requested when the view changes. Item icons are baked once from real game textures and inventory models: 761 flat items, 835 block models, and 62 special entity renders. All 90 mob icons use actual game meshes and textures. Icons use nearest-neighbor sampling and pixelated browser scaling. No per-node live 3D scene is needed.

All nodes and relationships are loaded. View modes and filters make dense regions readable. Nearby places the selection at the center, direct neighbors on an inner ring, and faded second-hop neighbors on outer rings. Much larger modded graphs would warrant benchmarking and a spatial index or WebGL renderer before expansion. Repeated mining/fuel rules share records while retaining their individual edges.

[assets/icon-coverage.json](assets/icon-coverage.json), [assets/mobs/coverage.json](assets/mobs/coverage.json) and [assets/blocks/coverage.json](assets/blocks/coverage.json) list artwork coverage. Icons use static default states, representative skins and simplified lighting; animations, glint, custom components, player skins and some extra mob layers are not rendered. Player Head uses the bundled Steve skin; Air is intentionally transparent. Mob models face the camera. Inventory-less blocks use their actual block models and textures, including Fire, Soul Fire, Nether Portal and Frosted Ice. Animated textures use one static frame. Fluids use simplified cubes with their still textures; Water uses the game's Plains tint. Asset revision URLs refresh rebuilt artwork despite the local server's image cache.

## Versioned graph format

[data/graph.json](data/graph.json) contains `nodes`, `recipes`, `relationships` and `edges`, plus `version`, `versions`, and `schemaVersion`. Every node, record and edge has an inclusive version interval:

```json
{ "minVersion": "26.3", "maxVersion": null }
```

An entity appears when `minVersion <= selectedVersion <= maxVersion`; `null` means no known upper bound. Comparisons are numeric, so `26.10` sorts after `26.3`. Endpoint availability and the recipe's interval also constrain edges. Only 26.3 is loaded today. The lower bound describes the start of this dataset's coverage, **not historical introduction dates**.

Recipe edges use `category: "recipe"`, a specific `type` such as `smelting` or `loom`, and `recipeId` referring to the full recipe. Other edges use `relationId`, with categories including `membership`, `gathering`, `loot`, `uses`, `spawning`, `effects` and `worldgen`. Each edge has exactly one record reference. Node kinds are `item`, `category`, `mob`, `block`, `effect`, `entity`, `structure`, `biome` and `dimension`; IDs use distinct namespaces (`minecraft:oak_planks`, `tag:minecraft:planks`, `mob:minecraft:skeleton`, `block:minecraft:water`, `effect:minecraft:hunger`, `structure:minecraft:fortress`, `biome:minecraft:nether_wastes`, `dimension:minecraft:the_nether`). Burning uses `effect:state:burning`. Endpoint/record availability, selected node kinds, category-qualified relationship filters and the self-loop toggle all constrain visible edges.

Recipes contain ingredient groups with `items` alternatives and quantities, and result records with item IDs/counts. Dynamic recipes carry conditions; official recipes retain raw game JSON. Generic records retain their inputs/outputs, notes and source metadata; loot records preserve the game's conditional selection data. Future relationship categories and version snapshots can use the same interval fields; importing historical data or editing graph records through a UI is not implemented.

## Rebuild and check

Prebuilt data and icons are included. Extraction uses Python with Pillow and Java 25. Full model baking also requires NumPy. In this workspace Java 25 is installed at the path below:

```powershell
python scripts/extract_data.py --java "C:\Program Files\Java\jdk-25.0.2\bin\java.exe"
```

The extractor refreshes Mojang metadata, reuses a local client only after checksum verification, and otherwise downloads the official client and required libraries into `.cache`. It runs the Java mob geometry, block/stew mapping, effect/potion, interaction, plant, biome and structure exporters when reports are missing or their source/jar changes. `--minecraft-dir` selects a different launcher directory; `--offline` reuses verified cached inputs. Unknown recipe serializers, loot entries and consume effects fail explicitly. Supplemental workstation and interaction triggers are audited for 26.3 and reject another release until reviewed. Python extraction needs Pillow for generated icons; full model baking also needs NumPy.

Then regenerate icons using the resolved game classpath:

```powershell
$taskClassPath = (Get-Content .cache/classpath.txt -Raw).Trim()
& "C:\Program Files\Java\jdk-25.0.2\bin\java.exe" --class-path $taskClassPath scripts/ExportItemGeometry.java .cache/special-models.json
python scripts/render_icons.py
python scripts/render_mobs.py
python scripts/render_blocks.py
```

Checks:

```powershell
node --test tests/*.test.mjs
python -m unittest discover -s scripts -p 'test_*.py'
python -m unittest discover -s tests -p test_icons.py
```

Minecraft names, textures, models, and game data belong to Mojang/Microsoft. This is an unofficial local project.

The inventories of recipes, tags, effect registries, referenced tool rules, block transformers and the documented component mappings are checked exhaustively. Hand-coded interactions are audited finite rules, **not a claim that every possible emergent Minecraft interaction is enumerated**. World generation links describe possible outputs and placement rules, not the contents of a particular seed. Arbitrary customized stacks/equipment, complete world simulation and villager trade offers remain outside this update. Detailed coverage and any omitted existing-node mappings are in `data/provenance.json`.
