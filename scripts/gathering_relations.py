"""Game-derived gathering, kept separate from crafting recipes."""
import json
from pathlib import Path


def build_gathering(game, version, mob_nodes):
    from mob_relations import iter_loot_items

    if version != "26.3":
        raise ValueError("Gathering interaction triggers must be audited for this game version")
    bounds = {"minVersion": version, "maxVersion": None}
    metadata_path = Path(__file__).resolve().parents[1] / '.cache/gathering-metadata.json'
    gathering_metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    if gathering_metadata['version'] != version:
        raise ValueError('Regenerate the gathering metadata for this version')
    nodes, relations, edges = {}, [], []
    mob_ids = {node["id"] for node in mob_nodes}
    language = json.loads(game.jar.read("assets/minecraft/lang/en_us.json"))
    table_ids = sorted("minecraft:" + path.removeprefix("data/minecraft/loot_table/").removesuffix(".json")
                       for path in game.jar.namelist()
                       if path.startswith("data/minecraft/loot_table/") and path.endswith(".json"))
    covered = set()

    def block_source(slug, representative="minecraft:stone"):
        block_id = "minecraft:" + slug
        item = gathering_metadata['blockItems'][block_id]
        if item != 'minecraft:air':
            if item not in game.items:
                raise ValueError(f'Unregistered block item: {item}')
            return item
        node_id = "block:" + block_id
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "name": language.get("block.minecraft." + slug, slug.replace("_", " ").title()),
                              "kind": "block", "blockId": block_id, "icon": f"assets/blocks/{slug}.png",
                              "iconNote": "Static default block state from the game's block models and textures.", **bounds}
        return node_id

    def add(kind, sources, output, note, *, identifier, metadata=None):
        if output not in game.items:
            raise ValueError(f"Unknown gathering output: {output}")
        relation_id = "gathering:" + identifier
        relation = {"id": relation_id, "type": kind, "category": "gathering", "name": kind.replace("_", " ").title(),
                    "inputs": [{"nodeId": source} for source in sources], "outputs": [{"nodeId": output}],
                    "note": note, **bounds, **(metadata or {})}
        relations.append(relation)
        for source in sources:
            if source not in game.items and source not in nodes and source not in mob_ids:
                raise ValueError(f"Unknown gathering source: {source}")
            edges.append({"id": f"{relation_id}:{source}>{output}", "source": source, "target": output,
                          "category": "gathering", "type": kind, "relationId": relation_id, **bounds})

    def loot(table_id, sources, kind, note):
        covered.add(table_id)
        records = list(iter_loot_items(game, table_id))
        if callable(sources):
            sources = sources(records[0]["item"] if records else "minecraft:stone")
        for index, record in enumerate(records):
            add(kind, sources, record["item"], note + " Loot conditions, counts and selection weights are preserved below; this is a possible outcome, not a guaranteed drop.",
                identifier=f"{table_id}:{'|'.join(sources)}:{index}", metadata={"source": "vanilla_loot_table", "loot": record})

    # Components point to context-dependent layer providers; they are not yield chances.
    compostables = 0
    for item, components in sorted(game.components.items()):
        component = components.get("minecraft:compostable")
        if not component:
            continue
        provider_id = component["layers"]
        if not isinstance(provider_id, str):
            raise ValueError(f"Unexpected compostable layer provider: {item}")
        namespace, slug = provider_id.split(":", 1)
        provider = json.loads(game.jar.read(f"data/{namespace}/context_int_provider/{slug}.json"))
        default = provider.get("default") if isinstance(provider, dict) else provider
        chance = None
        if isinstance(default, (int, float)):
            chance = 1 if default > 0 else 0
        elif isinstance(default, dict) and default.get("type") == "minecraft:weighted_list":
            distribution = default["distribution"]
            chance = sum(part["weight"] for part in distribution if part["data"] > 0) / sum(part["weight"] for part in distribution)
        if chance is None:
            raise ValueError(f"Unknown composting layer distribution: {provider_id}")
        add("composting", [item, "minecraft:composter"], "minecraft:bone_meal",
            "Consumes compostable items in a composter. Seven successful layer additions fill it; after maturation, harvest one Bone Meal. The empty composter's first addition succeeds. A single item does not produce one Bone Meal.",
            identifier="composting:" + item,
            metadata={"source": "vanilla_item_component", "ingredients": [{"items": [item], "count": 1}, {"items": ["minecraft:composter"], "count": 1, "consumed": False, "role": "station"}],
                      "results": [{"item": "minecraft:bone_meal", "count": 1}], "layersRequired": 7, "layerChance": chance,
                      "layerProviderId": provider_id, "raw": component, "layerProvider": provider})
        compostables += 1

    for table_id in table_ids:
        if table_id.startswith("minecraft:blocks/"):
            slug = table_id.split("/", 1)[1]
            loot(table_id, lambda item, slug=slug: [block_source(slug, item)], "block_drop", "Break or harvest this block with the required tool and state. Silk Touch, Fortune, crop age and other restrictions depend on the branch.")

    passive = {
        "armadillo_shed": ("armadillo", "An armadillo periodically sheds a scute while mob drops are enabled."),
        "cat_morning_gift": ("cat", "A tamed cat that sleeps near its owner may bring a morning gift."),
        "chicken_lay": ("chicken", "An adult chicken periodically lays an egg; variant controls egg color."),
        "panda_sneeze": ("panda", "A baby panda may drop slime when sneezing."),
        "sniffer_digging": ("sniffer", "An adult sniffer digs seeds from eligible ground after its cooldown."),
        "turtle_grow": ("turtle", "A baby turtle drops a scute when it becomes an adult."),
    }
    for slug, (mob, note) in passive.items():
        loot("minecraft:gameplay/" + slug, ["mob:minecraft:" + mob], "passive_drop", note)
    for table_id in table_ids:
        if table_id.startswith("minecraft:gameplay/hero_of_the_village/"):
            profession = table_id.rsplit("/", 1)[1].removesuffix("_gift").replace("_", " ")
            loot(table_id, ["mob:minecraft:villager"], "gifting", f"A {profession} villager may give this gift to a player with Hero of the Village, after its gift cooldown.")
    loot("minecraft:gameplay/fishing", ["minecraft:fishing_rod"], "fishing", "Catch an item with a fishing rod. Open water and luck affect the selected loot branch.")
    loot("minecraft:gameplay/piglin_bartering", ["mob:minecraft:piglin", "minecraft:gold_ingot"], "bartering", "Give one Gold Ingot to an adult piglin; it chooses one barter outcome. Babies do not barter.")
    for mob in ["bogged", "mooshroom", "sheep", "snow_golem"]:
        note = {"bogged": "Shear an unsheared bogged for mushrooms.", "mooshroom": "Shear an adult mooshroom for mushrooms; this converts it into a cow.", "sheep": "Shear an adult, unsheared sheep for 1–3 wool matching its color.", "snow_golem": "Shear a snow golem that still wears its pumpkin, removing the pumpkin."}[mob]
        loot("minecraft:shearing/" + mob, ["mob:minecraft:" + mob, "minecraft:shears"], "shearing", note + " Shears are retained and lose durability.")
    loot("minecraft:brush/armadillo", ["mob:minecraft:armadillo", "minecraft:brush"], "brushing", "Brush an adult armadillo to obtain a scute; the brush loses 16 durability.")
    loot("minecraft:harvest/beehive", ["minecraft:beehive", "minecraft:shears"], "honey_harvesting", "Shear a hive at honey level 5. Bees are needed to fill it; smoke prevents anger. Shears are retained.")
    loot("minecraft:harvest/beehive", ["minecraft:bee_nest", "minecraft:shears"], "honey_harvesting", "Shear a bee nest at honey level 5. Bees are needed to fill it; smoke prevents anger. Shears are retained.")
    for slug, plant in [("cave_vine", "cave_vines"), ("sweet_berry_bush", "sweet_berry_bush")]:
        loot("minecraft:harvest/" + slug, lambda item, plant=plant: [block_source(plant, item)], "harvesting", "Interact with a fruit-bearing cave vine or berry bush at age greater than one; harvesting changes its age or berry state.")
    loot("minecraft:carve/pumpkin", ["minecraft:pumpkin", "minecraft:shears"], "carving", "Use shears to turn a pumpkin into a carved pumpkin, also releasing four Pumpkin Seeds. Shears lose durability.")
    loot("minecraft:till/rooted_dirt", ["minecraft:rooted_dirt"], "tilling", "Till Rooted Dirt with a hoe to convert it into Dirt and release a Hanging Root.")

    for hive in ["minecraft:beehive", "minecraft:bee_nest"]:
        add("honey_harvesting", [hive, "minecraft:glass_bottle"], "minecraft:honey_bottle",
            "Use a glass bottle on a hive or nest at honey level 5. One bottle becomes one Honey Bottle; honey level resets. Bees fill the hive, and smoke prevents anger.",
            identifier="bottle_honey:" + hive, metadata={"source": "audited_game_interaction", "sourceClass": "net.minecraft.world.level.block.BeehiveBlock", "results": [{"item": "minecraft:honey_bottle", "count": 1}]})
    for mob in ["cow", "goat", "mooshroom"]:
        add("milking", ["mob:minecraft:" + mob, "minecraft:bucket"], "minecraft:milk_bucket",
            "Use an empty bucket on an adult animal; one bucket becomes one Milk Bucket. The animal is retained.",
            identifier="milking:" + mob, metadata={"source": "audited_game_interaction", "results": [{"item": "minecraft:milk_bucket", "count": 1}]})

    for fluid, output in [("water", "water_bucket"), ("lava", "lava_bucket"), ("powder_snow", "powder_snow_bucket")]:
        source = block_source(fluid, "minecraft:" + output)
        add("bucket_filling", [source, "minecraft:bucket"], "minecraft:" + output,
            "Use an empty bucket on a collectable source block. Flowing water and lava cannot be picked up. One empty bucket becomes one filled bucket.",
            identifier="bucket_filling:" + fluid, metadata={"source": "audited_game_interaction", "sourceClass": "net.minecraft.world.item.BucketItem"})
    add("bottling", [block_source("water", "minecraft:water_bucket"), "minecraft:glass_bottle"], "minecraft:potion",
        "Use a glass bottle on source water to obtain one Water Bottle. The registered item is Potion with water potion contents.",
        identifier="water_bottle", metadata={"source": "audited_game_interaction", "results": [{"item": "minecraft:potion", "count": 1, "components": {"minecraft:potion_contents": {"potion": "minecraft:water"}}}]})
    add("bottling", ["mob:minecraft:ender_dragon", "minecraft:glass_bottle"], "minecraft:dragon_breath",
        "Use a glass bottle inside an active breath cloud created by an Ender Dragon. The cloud radius shrinks by 0.5; the dragon itself is not bottled.",
        identifier="dragon_breath", metadata={"source": "audited_game_interaction", "sourceClass": "net.minecraft.world.item.BottleItem"})
    for mob in ["cod", "salmon", "pufferfish", "tropical_fish", "axolotl", "tadpole", "sulfur_cube"]:
        bucket = "minecraft:bucket" if mob == "sulfur_cube" else "minecraft:water_bucket"
        note = "Capture a living eligible mob using a Water Bucket; its variant and other components are carried into the bucket."
        if mob == "sulfur_cube":
            note = "Capture an eligible unprimed adult Sulfur Cube using an empty Bucket; its components are carried into the bucket."
        add("mob_capture", ["mob:minecraft:" + mob, bucket], "minecraft:" + mob + "_bucket", note,
            identifier="mob_capture:" + mob, metadata={"source": "audited_game_interaction", "sourceClass": "net.minecraft.world.entity.Bucketable"})
    for output in ["mushroom_stew", "suspicious_stew"]:
        note = "Use a bowl on an adult mooshroom to get Mushroom Stew. The bowl becomes the stew and the animal is retained."
        if output == "suspicious_stew":
            note = "A brown adult mooshroom must first consume an eligible flower and store its stew effect. Using a bowl produces Suspicious Stew with that effect and clears the stored effect."
        add("milking", ["mob:minecraft:mooshroom", "minecraft:bowl"], "minecraft:" + output, note,
            identifier="mooshroom_stew:" + output, metadata={"source": "audited_game_interaction", "sourceClass": "net.minecraft.world.entity.animal.cow.MushroomCow"})
    for flower, effects in gathering_metadata['suspiciousStewIngredients'].items():
        add('milking', [flower, 'mob:minecraft:mooshroom', 'minecraft:bowl'], 'minecraft:suspicious_stew',
            'First feed this flower to an adult brown mooshroom with no stored stew effect. Then use a bowl to obtain Suspicious Stew with the listed effect; the stored effect is consumed.',
            identifier='flower_stew:' + flower, metadata={'source': 'game_suspicious_effect_holder', 'stewEffects': effects,
                                                        'results': [{'item': 'minecraft:suspicious_stew', 'count': 1, 'components': {'minecraft:suspicious_stew_effects': effects}}]})
    add("carving", ["minecraft:pumpkin", "minecraft:shears"], "minecraft:carved_pumpkin",
        "Shear a Pumpkin to create a Carved Pumpkin and release four Pumpkin Seeds. Shears are retained and lose durability.",
        identifier="carved_pumpkin", metadata={"source": "audited_game_interaction"})
    add("tilling", ["minecraft:rooted_dirt"], "minecraft:dirt",
        "Use a hoe to turn Rooted Dirt into Dirt, also releasing a Hanging Root.",
        identifier="till_rooted_dirt", metadata={"source": "audited_game_interaction"})
    add('ramming', ['mob:minecraft:goat'], 'minecraft:goat_horn',
        'An adult goat with a remaining horn can drop one horn when it rams a block in #minecraft:snaps_goat_horn. One horn is removed; the instrument depends on its screaming state and UUID.',
        identifier='goat_horn', metadata={'source': 'audited_game_interaction', 'sourceClass': 'net.minecraft.world.entity.ai.behavior.RamTarget', 'blockTag': 'minecraft:snaps_goat_horn'})
    for table_id in table_ids:
        if table_id.startswith('minecraft:archaeology/'):
            context = table_id.rsplit('/', 1)[1]
            sand = context in ['desert_pyramid', 'desert_well', 'ocean_ruin_warm']
            source = 'minecraft:suspicious_sand' if sand else 'minecraft:suspicious_gravel'
            loot(table_id, [source, 'minecraft:brush'], 'archaeology',
                 'Brush the suspicious block generated in ' + context.replace('_', ' ') + '. Its stored loot table is determined by structure generation; breaking the block destroys the buried loot.')

    return {"nodes": list(nodes.values()), "relationships": relations, "edges": edges,
            "coverage": {"compostableItems": compostables, "gatheringRecords": len(relations), "gatheringEdges": len(edges),
                         "blockLootTables": sum(t.startswith("minecraft:blocks/") for t in covered), "lootTables": sorted(covered),
                         "limitations": ["Gathering edges describe possible complete interactions; tools, states, variant conditions and randomness remain attached to records.",
                                         "Blocks without inventory items use representative dropped-item artwork.",
                                         "Villager trading, chest loot and full world transformations are not yet mapped."]}}
