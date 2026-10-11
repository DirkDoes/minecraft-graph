"""Structure relationships from vanilla definitions, reachable templates and audited pieces."""
import gzip
import hashlib
import io
import json
import struct
from collections import defaultdict
from pathlib import Path

from PIL import Image

from mob_relations import iter_loot_items

ROOT = Path(__file__).resolve().parents[1]


def read_nbt(payload):
    """Read the standard big-endian NBT used by the game's compressed templates."""
    stream = io.BytesIO(gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload)

    def number(format):
        size = struct.calcsize(format)
        data = stream.read(size)
        if len(data) != size:
            raise ValueError("Truncated structure NBT")
        return struct.unpack(format, data)[0]

    def text():
        return stream.read(number(">H")).decode("utf-8")

    def tag(kind):
        if kind in (1, 2, 3, 4, 5, 6):
            return number({1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}[kind])
        if kind == 8:
            return text()
        if kind == 9:
            item_kind, length = number(">B"), number(">i")
            if length < 0:
                raise ValueError("Negative NBT list length")
            return [tag(item_kind) for _ in range(length)]
        if kind == 10:
            result = {}
            while (item_kind := number(">B")):
                name = text()
                result[name] = tag(item_kind)
            return result
        if kind in (7, 11, 12):
            length = number(">i")
            if length < 0:
                raise ValueError("Negative NBT array length")
            return [number({7: ">b", 11: ">i", 12: ">q"}[kind]) for _ in range(length)]
        raise ValueError(f"Unsupported structure NBT tag {kind}")

    kind = number(">B")
    text()
    value = tag(kind)
    if stream.read(1):
        raise ValueError("Unexpected data after structure NBT")
    return value


def resource_path(folder, resource, suffix=".json"):
    namespace, slug = resource.split(":", 1)
    return f"data/{namespace}/{folder}/{slug}{suffix}"


def names(game, folder):
    prefix = "data/minecraft/" + folder + "/"
    return {"minecraft:" + path.removeprefix(prefix).removesuffix(".json"): json.loads(game.jar.read(path))
            for path in game.jar.namelist() if path.startswith(prefix) and path.endswith(".json")}


class StructureSources:
    def __init__(self, game):
        self.game = game
        self.pools = names(game, "worldgen/template_pool")
        self.processors = names(game, "worldgen/processor_list")
        self.block_tags = names(game, "tags/block")
        self.templates = {}
        self.missing_templates = set()
        self.resolved_tags = {}

    def tag(self, name):
        if name not in self.resolved_tags:
            values = set()
            for value in self.block_tags[name]["values"]:
                value = value if isinstance(value, str) else value["id"]
                values.update(self.tag(value[1:]) if value.startswith("#") else [value])
            self.resolved_tags[name] = values
        return self.resolved_tags[name]

    def template(self, name):
        if name not in self.templates:
            try:
                self.templates[name] = read_nbt(self.game.jar.read(resource_path("structure", name, ".nbt")))
            except KeyError:
                self.missing_templates.add(name)
                self.templates[name] = {}
        return self.templates[name]

    def matches(self, predicate, block):
        kind = predicate["predicate_type"]
        if kind == "minecraft:always_true":
            return True
        if kind in ("minecraft:block_match", "minecraft:random_block_match"):
            return predicate["block"] == block and predicate.get("probability", 1) > 0
        if kind in ("minecraft:blockstate_match", "minecraft:random_blockstate_match"):
            return state_id(predicate["block_state"]) == block and predicate.get("probability", 1) > 0
        if kind == "minecraft:tag_match":
            return block in self.tag(predicate["tag"])
        raise ValueError("Unaudited input predicate " + kind)

    def processed(self, block, processors):
        outputs, loot = {block}, []
        # RuleProcessor applies the first successful rule per processor. This union
        # retains probabilistic branches; deterministic removals do not leak into output.
        def apply(value, capped=False):
            nonlocal outputs
            if isinstance(value, str):
                value = self.processors[value]
            if "processors" in value:
                for processor in value["processors"]:
                    apply(processor)
            elif value["processor_type"] == "minecraft:capped":
                apply(value["delegate"], True)
            elif value["processor_type"] == "minecraft:rule":
                transformed = set()
                for current in outputs:
                    can_remain = True
                    for rule in value["rules"]:
                        predicate = rule["input_predicate"]
                        if not self.matches(predicate, current):
                            continue
                        transformed.add(state_id(rule["output_state"]))
                        modifier = rule.get("block_entity_modifier", {})
                        if modifier.get("type") == "minecraft:append_loot":
                            loot.append({"table": modifier["loot_table"], "processorRule": rule, "capped": capped})
                        certain = (not capped and predicate.get("probability", 1) == 1
                                   and predicate["predicate_type"] not in ("minecraft:blockstate_match", "minecraft:random_blockstate_match")
                                   and rule["location_predicate"]["predicate_type"] == "minecraft:always_true"
                                   and rule.get("position_predicate", {"predicate_type": "minecraft:always_true"})["predicate_type"] == "minecraft:always_true")
                        if certain:
                            can_remain = False
                            break
                    if can_remain:
                        transformed.add(current)
                outputs = transformed
            elif value["processor_type"] not in ("minecraft:block_rot", "minecraft:protected_blocks"):
                raise ValueError("Unaudited structure processor " + value["processor_type"])
        apply(processors)
        return outputs, loot

    def jigsaw(self, definition):
        aliases = defaultdict(set)
        def alias(value):
            kind = value["type"]
            if kind == "minecraft:direct":
                aliases[value["alias"]].add(value["target"])
            elif kind == "minecraft:random":
                aliases[value["alias"]].update(e["data"] for e in value["targets"] if e["weight"] > 0)
            elif kind == "minecraft:random_group":
                for group in value["groups"]:
                    if group["weight"] > 0:
                        for entry in group["data"]:
                            alias(entry)
            else:
                raise ValueError("Unaudited pool alias " + kind)
        for value in definition.get("pool_aliases", []):
            alias(value)
        found, features, visited = {}, {}, {}

        def compatible(value, required_name):
            kind = value["element_type"]
            if not required_name:
                return True
            if kind in ("minecraft:single_pool_element", "minecraft:legacy_single_pool_element"):
                return any(block.get("nbt", {}).get("name") == required_name for block in self.template(value["location"]).get("blocks", []))
            if kind == "minecraft:list_pool_element":
                return bool(value["elements"]) and compatible(value["elements"][0], required_name)
            # FeaturePoolElement supplies a synthetic bottom connector.
            return kind == "minecraft:feature_pool_element" and required_name == "minecraft:bottom"

        def element(value, depth, pool_id, fallback=False):
            kind = value["element_type"]
            if kind in ("minecraft:single_pool_element", "minecraft:legacy_single_pool_element"):
                name, processors = value["location"], value["processors"]
                key = (name, json.dumps(processors, sort_keys=True))
                if key not in found:
                    found[key] = {"template": name, "processors": processors, "pool": pool_id,
                                  "depth": depth, "fallback": fallback, "elementType": kind}
                if depth <= definition["size"]:
                    for block in self.template(name).get("blocks", []):
                        nbt = block.get("nbt", {})
                        if nbt.get("id") == "minecraft:jigsaw" and nbt.get("pool"):
                            for target in aliases.get(nbt["pool"], {nbt["pool"]}):
                                pool(target, depth + 1, nbt.get("target"), depth < definition["size"])
            elif kind == "minecraft:list_pool_element":
                for child in value["elements"]:
                    element(child, depth, pool_id, fallback)
            elif kind == "minecraft:feature_pool_element":
                features[value["feature"]] = {"placedFeature": value["feature"], "pool": pool_id}
            elif kind != "minecraft:empty_pool_element":
                raise ValueError("Unaudited pool element " + kind)

        def pool(name, depth, required_name=None, main=True, fallback=True):
            if name == "minecraft:empty" or depth > definition["size"] + 1:
                return
            visit_key = (name, required_name, main, fallback)
            if visited.get(visit_key, definition["size"] + 2) <= depth:
                return
            visited[visit_key] = depth
            value = self.pools[name]
            candidates = [(name, False)] if main else []
            if fallback and value["fallback"] != "minecraft:empty":
                candidates.append((value["fallback"], True))
            for selected_pool, is_fallback in candidates:
                for entry in self.pools[selected_pool]["elements"]:
                    if entry["weight"] > 0 and compatible(entry["element"], required_name):
                        element(entry["element"], depth, selected_pool, is_fallback)

        pool(definition["start_pool"], 0, definition.get("start_jigsaw_name"), fallback=False)
        return list(found.values()), list(features.values()), {key[0] for key in visited}


def state_id(value):
    return value.split("[", 1)[0] if isinstance(value, str) else value.get("id", value.get("Name"))


IGNORED_BLOCKS = {"minecraft:" + x for x in ("air", "cave_air", "void_air", "structure_void", "structure_block", "jigsaw")}

# shortcut: procedural placement code is audited for this client/version, re-audit these sets before adding another version.
PROCEDURAL_BLOCKS = {
    "buried_treasure": "sand chest",
    "desert_pyramid": "sand sandstone chiseled_sandstone cut_sandstone sandstone_slab sandstone_stairs orange_terracotta blue_terracotta stone_pressure_plate tnt chest suspicious_sand",
    "jungle_pyramid": "chiseled_stone_bricks cobblestone cobblestone_stairs lever mossy_cobblestone redstone_wire repeater sticky_piston tripwire tripwire_hook vine chest dispenser",
    "mineshaft": "cobweb iron_chain rail spawner wall_torch oak_fence oak_log oak_planks",
    "mineshaft_mesa": "cobweb iron_chain rail spawner wall_torch dark_oak_fence dark_oak_log dark_oak_planks",
    "fortress": "lava nether_bricks nether_brick_fence nether_brick_stairs nether_wart soul_sand spawner chest",
    "monument": "dark_prismarine gold_block prismarine prismarine_bricks sea_lantern water wet_sponge",
    "stronghold": "bookshelf cobblestone cobblestone_stairs cobweb cracked_stone_bricks end_portal end_portal_frame infested_stone_bricks iron_bars iron_door ladder lava mossy_stone_bricks oak_door oak_fence oak_planks smooth_stone_slab spawner stone_bricks stone_brick_slab stone_brick_stairs stone_button torch wall_torch water chest",
    "swamp_hut": "cauldron crafting_table oak_fence oak_log potted_red_mushroom spruce_planks spruce_stairs",
    "mansion": "cobblestone chest",
    "igloo": "ladder snow_block",
    "nether_fossil": "dried_ghast",
    "ocean_ruin_cold": "chest suspicious_gravel",
    "ocean_ruin_warm": "chest suspicious_sand",
}
PROCEDURAL_LOOT = {
    "buried_treasure": ["BURIED_TREASURE"],
    "desert_pyramid": ["DESERT_PYRAMID", "DESERT_PYRAMID_ARCHAEOLOGY"],
    "jungle_pyramid": ["JUNGLE_TEMPLE", "JUNGLE_TEMPLE_DISPENSER"],
    "mineshaft": ["ABANDONED_MINESHAFT"], "mineshaft_mesa": ["ABANDONED_MINESHAFT"],
    "fortress": ["NETHER_BRIDGE"],
    "stronghold": ["STRONGHOLD_CORRIDOR", "STRONGHOLD_CROSSING", "STRONGHOLD_LIBRARY"],
    "ocean_ruin_cold": ["OCEAN_RUIN_COLD_ARCHAEOLOGY"],
    "ocean_ruin_warm": ["OCEAN_RUIN_WARM_ARCHAEOLOGY"],
}
PROCEDURAL_MOBS = {
    "swamp_hut": ["witch", "cat"], "monument": ["elder_guardian"],
}
PROCEDURAL_SPAWNERS = {
    "mineshaft": ["cave_spider"], "mineshaft_mesa": ["cave_spider"],
    "fortress": ["blaze"], "stronghold": ["silverfish"],
}
SOURCE_CLASSES = {
    "buried_treasure": "BuriedTreasurePieces.BuriedTreasurePiece", "desert_pyramid": "DesertPyramidPiece/DesertPyramidStructure",
    "jungle_pyramid": "JungleTemplePiece", "mineshaft": "MineshaftPieces/MineshaftStructure.Type", "mineshaft_mesa": "MineshaftPieces/MineshaftStructure.Type",
    "fortress": "NetherFortressPieces", "monument": "OceanMonumentPieces", "stronghold": "StrongholdPieces",
    "swamp_hut": "SwampHutPiece", "mansion": "WoodlandMansionPieces/WoodlandMansionStructure",
    "igloo": "IglooPieces", "nether_fossil": "NetherFossilPieces", "ocean_ruin_cold": "OceanRuinPieces", "ocean_ruin_warm": "OceanRuinPieces",
}


def structure_emblem(slug, existing):
    """Small transparent emblems assembled from the app's official block/item renders."""
    representative = {
        "ancient_city": "reinforced_deepslate sculk soul_lantern", "bastion_remnant": "gilded_blackstone blackstone gold_block",
        "buried_treasure": "chest sand heart_of_the_sea", "desert_pyramid": "cut_sandstone orange_terracotta suspicious_sand",
        "end_city": "purpur_block end_stone_bricks elytra", "fortress": "nether_bricks nether_wart blaze_rod",
        "igloo": "snow_block iron_bars brewing_stand", "jungle_pyramid": "mossy_cobblestone tripwire_hook chest",
        "mansion": "dark_oak_log cobblestone red_carpet", "monument": "prismarine sea_lantern wet_sponge",
        "nether_fossil": "bone_block dried_ghast soul_sand", "stronghold": "stone_bricks end_portal_frame iron_bars",
        "swamp_hut": "spruce_planks cauldron crafting_table", "trail_ruins": "mud_bricks suspicious_gravel terracotta",
        "trial_chambers": "tuff_bricks copper_bulb trial_spawner", "amethyst_geode": "amethyst_block calcite smooth_basalt",
        "desert_well": "sandstone sandstone_slab suspicious_sand", "monster_room": "mossy_cobblestone spawner chest",
        "end_gateway_return": "bedrock ender_pearl end_stone", "end_platform": "obsidian end_stone ender_pearl",
        "end_gateway_delayed": "bedrock ender_pearl end_stone", "end_podium_active": "bedrock end_stone ender_eye",
        "end_podium_inactive": "bedrock end_stone torch",
        "end_spike": "obsidian end_crystal iron_bars", "fossil_coal": "bone_block coal_ore sand",
        "fossil_diamonds": "bone_block deepslate_diamond_ore sand", "sulfur_spring": "sulfur cinnabar tuff",
        "void_start_platform": "stone cobblestone barrier",
    }
    art = representative.get(slug)
    if art is None:
        art = ("campfire white_banner oak_log" if slug.startswith("abandoned_camp") else
               "crying_obsidian obsidian netherrack" if slug.startswith("ruined_portal") else
               "oak_planks rail cobweb" if slug.startswith("mineshaft") else
               "oak_planks chest spruce_trapdoor" if slug.startswith("shipwreck") else
               "sandstone suspicious_sand chest" if slug == "ocean_ruin_warm" else
               "stone_bricks suspicious_gravel chest" if slug == "ocean_ruin_cold" else
               "dark_oak_log crossbow iron_bars" if slug == "pillager_outpost" else
               "sandstone hay_block bell" if slug == "village_desert" else
               "acacia_planks hay_block bell" if slug == "village_savanna" else
               "spruce_planks snow_block bell" if slug == "village_snowy" else
               "spruce_planks mossy_cobblestone bell" if slug == "village_taiga" else
               "oak_planks hay_block bell" if slug == "village_plains" else None)
    if art is None:
        raise ValueError("Structure emblem has no audited representative " + slug)
    output = Image.new("RGBA", (64, 64))
    for item, (size, position) in zip(art.split(), ((42, (1, 0)), (34, (29, 3)), (38, (14, 26)))):
        source = ROOT / existing["minecraft:" + item]["icon"]
        with Image.open(source) as image:
            output.alpha_composite(image.convert("RGBA").resize((size, size), Image.Resampling.NEAREST), position)
    target = ROOT / "assets/structures" / (slug + ".png")
    target.parent.mkdir(parents=True, exist_ok=True)
    output.save(target)


def procedural_templates(sources, slug, definition, metadata):
    fields = metadata["templateFields"]
    if slug == "igloo":
        selected = fields["IglooPieces"].values()
    elif slug == "nether_fossil":
        selected = fields["NetherFossilPieces"]["FOSSILS"]
    elif slug.startswith("shipwreck"):
        selected = fields["ShipwreckPieces"]["STRUCTURE_LOCATION_BEACHED" if definition["is_beached"] else "STRUCTURE_LOCATION_OCEAN"]
    elif slug.startswith("ocean_ruin"):
        selected = [template for field, values in fields["OceanRuinPieces"].items()
                    if ("WARM" in field) == (definition["biome_temp"] == "warm") for template in values]
    else:
        prefix = {"end_city": "end_city/", "mansion": "woodland_mansion/"}.get(slug)
        if slug.startswith("ruined_portal"):
            prefix = "ruined_portal/"
        selected = sorted("minecraft:" + path.removeprefix("data/minecraft/structure/").removesuffix(".nbt")
                          for path in sources.game.jar.namelist() if prefix and path.startswith("data/minecraft/structure/" + prefix) and path.endswith(".nbt"))
    return [{"template": template, "processors": {"processors": []}, "sourceClass": SOURCE_CLASSES.get(slug, definition["type"])} for template in selected]


def portal_outputs(sources, block, definition, metadata):
    """Possible RuinedPortalPiece processor outputs for its actual setup variants."""
    result = set()
    for setup in definition["setups"]:
        output = {block}
        mossy = setup["mossiness"] > 0
        if block in {"minecraft:stone", "minecraft:stone_bricks", "minecraft:chiseled_stone_bricks"}:
            output.update({"minecraft:cracked_stone_bricks", "minecraft:stone_brick_stairs"})
            if mossy:
                output.update({"minecraft:mossy_stone_bricks", "minecraft:mossy_stone_brick_stairs"})
        if block in sources.tag("minecraft:stairs"):
            output.update({"minecraft:stone_slab", "minecraft:stone_brick_slab"})
            if mossy:
                output.update({"minecraft:mossy_stone_brick_stairs", "minecraft:mossy_stone_brick_slab"})
        if mossy and block in sources.tag("minecraft:slabs"):
            output.add("minecraft:mossy_stone_brick_slab")
        if mossy and block in sources.tag("minecraft:walls"):
            output.add("minecraft:mossy_stone_brick_wall")
        if block == "minecraft:obsidian":
            output.add("minecraft:crying_obsidian")
        if block == "minecraft:lava":
            if setup["placement"] == "on_ocean_floor":
                output = {"minecraft:magma_block", "minecraft:netherrack"} if setup["can_be_cold"] else {"minecraft:magma_block"}
            else:
                output.add("minecraft:magma_block")
                if setup["can_be_cold"]:
                    output.add("minecraft:netherrack")
        if setup["replace_with_blackstone"]:
            output = {metadata["blackstoneReplacements"].get(value, value) for value in output}
        result.update(output)
    return result


def feature_templates(feature_outputs, feature):
    """Find templates and their actual processors inside feature-based structures."""
    found = {}
    def walk(value, trail=()):
        if isinstance(value, str):
            if value in trail:
                raise ValueError("Cyclic structure feature " + value)
            definition = feature_outputs.features.get(value, feature_outputs.placements.get(value))
            if definition is None:
                raise ValueError("Unknown structure feature " + value)
            walk(definition, trail + (value,))
        elif isinstance(value, list):
            for entry in value:
                walk(entry, trail)
        elif "data" in value:
            if value.get("weight", 1) > 0:
                walk(value["data"], trail)
        elif value.get("type") == "minecraft:fossil":
            for key, processor in (("fossil_structures", "fossil_processors"), ("overlay_structures", "overlay_processors")):
                for template in value[key]:
                    entry = {"template": template, "processors": value[processor], "feature": feature}
                    found[(template, json.dumps(entry["processors"], sort_keys=True))] = entry
        elif value.get("type") == "minecraft:template":
            for entry in value["templates"]:
                if entry["weight"] > 0:
                    template = entry["data"]["id"]
                    item = {"template": template, "processors": value.get("processors", {"processors": []}), "feature": feature}
                    found[(template, json.dumps(item["processors"], sort_keys=True))] = item
        else:
            for key in ("feature", "features", "default", "feature_true", "feature_false"):
                if key in value:
                    walk(value[key], trail)
    walk(feature)
    return list(found.values())


def build_structures(game, version, existing_nodes):
    if version != "26.3":
        raise ValueError("Structure procedural generation requires a new version audit")
    from biome_relations import FeatureOutputs, biome_feature_structures
    metadata = json.loads((ROOT / ".cache/structure-metadata.json").read_text(encoding="utf-8"))
    sha = hashlib.sha1(Path(game.jar.filename).read_bytes()).hexdigest()
    if metadata["version"] != version or metadata["clientSha1"] != sha:
        raise ValueError("Structure metadata does not match this client; regenerate ExportStructureMetadata.java")
    sources, feature_outputs = StructureSources(game), FeatureOutputs(game)
    definitions = names(game, "worldgen/structure")
    biome_tags = names(game, "tags/worldgen/biome")
    block_items = json.loads((ROOT / ".cache/gathering-metadata.json").read_text(encoding="utf-8"))["blockItems"]
    language = json.loads(game.jar.read("assets/minecraft/lang/en_us.json"))
    ids = {node["id"] for node in existing_nodes}
    existing = {node["id"]: node for node in existing_nodes}
    bounds = {"minVersion": version, "maxVersion": None}
    nodes, records, edges = [], [], []
    structure_nodes = {}
    coverage = {"registeredStructures": len(definitions), "structures": {}, "lootTables": set(), "templateEntitiesNotRepresented": set()}

    def block_node(block):
        if block not in block_items:
            raise ValueError("Unregistered generated block " + block)
        item = block_items[block]
        target = item if item != "minecraft:air" else "block:" + block
        if target not in ids:
            if item != "minecraft:air":
                raise ValueError("Missing structure item node " + target)
            slug = block.split(":")[1]
            nodes.append({"id": target, "kind": "block", "blockId": block,
                          "name": language.get("block.minecraft." + slug, slug.replace("_", " ").title()),
                          "icon": "assets/blocks/" + slug + ".png", **bounds})
            ids.add(target)
        return target

    def add(kind, source, target, key, note, category="worldgen", **extra):
        if source not in ids or target not in ids:
            raise ValueError(f"Unknown structure endpoint {source} -> {target}")
        record_id = "structure:" + key
        records.append({"id": record_id, "type": kind, "category": category,
                        "inputs": [{"nodeId": source}], "outputs": [{"nodeId": target}], "note": note,
                        "source": "vanilla_structure_definitions_templates_and_audited_code", **extra, **bounds})
        edges.append({"id": "edge:" + record_id, "source": source, "target": target,
                      "type": kind, "category": category, "relationId": record_id, **bounds})

    def biome_members(value, trail=()):
        if isinstance(value, list):
            return set().union(*(biome_members(v, trail) for v in value))
        if not value.startswith("#"):
            return {value}
        name = value[1:]
        if name in trail:
            raise ValueError("Cyclic structure biome tag " + name)
        return set().union(*(biome_members(v if isinstance(v, str) else v["id"], trail + (name,))
                             for v in biome_tags[name]["values"]))

    def inspect(sid, slug, definition, templates, pool_features, biome_ids, feature_id=None):
        block_evidence, item_evidence, mob_evidence, spawner_evidence, loot_evidence = (defaultdict(list) for _ in range(5))

        def block(value, evidence):
            if value not in IGNORED_BLOCKS:
                # This graph represents block types, so repeated positions/facings
                # from one source template are one provenance link.
                evidence = {k: v for k, v in evidence.items() if k not in ("position", "palette", "state")}
                block_evidence[value].append(evidence)

        def entity(nbt, evidence, spawned=False):
            entity_id = nbt.get("id")
            if not entity_id:
                return
            target = "mob:" + entity_id
            if target in ids:
                (spawner_evidence if spawned else mob_evidence)[target].append({**evidence, "entityNbt": nbt})
            elif entity_id == "minecraft:cushion":
                item_evidence["minecraft:" + nbt["color"] + "_cushion"].append({**evidence, "entityNbt": nbt})
            elif entity_id == "minecraft:armor_stand":
                item_evidence["minecraft:armor_stand"].append({**evidence, "entityNbt": nbt})
            else:
                coverage["templateEntitiesNotRepresented"].add(entity_id)
            for passenger in nbt.get("Passengers", []):
                entity(passenger, evidence, spawned)

        def loot(table, evidence):
            loot_evidence[table].append(evidence)

        def container(nbt, evidence):
            if nbt.get("LootTable"):
                loot(nbt["LootTable"], {**evidence, "container": nbt.get("id")})
            for stack in nbt.get("Items", []):
                if stack.get("id") in game.items and stack.get("count", stack.get("Count", 1)) > 0:
                    item_evidence[stack["id"]].append({**evidence, "fixedStack": stack})
            if nbt.get("item", {}).get("id") in game.items:
                stack = nbt["item"]
                item_evidence[stack["id"]].append({**evidence, "fixedStack": stack})
            if nbt.get("id") == "minecraft:armor_stand":
                for slot, stack in nbt.get("equipment", {}).items():
                    if stack.get("id") in game.items and stack.get("count", 1) > 0:
                        item_evidence[stack["id"]].append({**evidence, "decorationEntity": "minecraft:armor_stand", "equipmentSlot": slot, "fixedStack": stack})
            if nbt.get("SpawnData"):
                entity(nbt["SpawnData"].get("entity", {}), evidence, True)
            for potential in nbt.get("SpawnPotentials", []):
                if potential.get("weight", 1) > 0:
                    entity(potential.get("data", {}).get("entity", {}), {**evidence, "spawnPotential": potential}, True)
            for mode in ("normal_config", "ominous_config"):
                if mode not in nbt:
                    continue
                config_id = nbt[mode]
                config = json.loads(game.jar.read(resource_path("trial_spawner", config_id))) if isinstance(config_id, str) else config_id
                config_context = {**evidence, "spawnerMode": mode, "spawnerConfig": config_id, "config": config}
                for potential in config.get("spawn_potentials", []):
                    if potential["weight"] > 0:
                        entity(potential["data"]["entity"], {**config_context, "spawnPotential": potential}, True)
                for entry in config.get("loot_tables_to_eject", metadata["trialSpawnerDefaults"]["loot_tables_to_eject"]):
                    if entry["weight"] > 0:
                        loot(entry["data"], {**config_context, "lootWeight": entry["weight"], "trigger": "Trial completion reward"})
                if mode == "ominous_config":
                    loot(config.get("items_to_drop_when_ominous", metadata["trialSpawnerDefaults"]["items_to_drop_when_ominous"]),
                         {**config_context, "trigger": "Ominous trial item spawner; item selection includes thrown projectiles"})
            if nbt.get("config", {}).get("loot_table"):
                loot(nbt["config"]["loot_table"], {**evidence, "vaultConfig": nbt["config"], "trigger": "Eligible player unlocks vault with configured key"})

        def marker(text, evidence):
            if slug == "end_city":
                if text.startswith("Chest"):
                    loot(metadata["lootFields"]["END_CITY_TREASURE"], evidence)
                elif text.startswith("Sentry"):
                    entity({"id": "minecraft:shulker"}, evidence)
                elif text.startswith("Elytra"):
                    item_evidence["minecraft:elytra"].append(evidence)
                    item_evidence["minecraft:item_frame"].append(evidence)
            elif slug == "igloo" and text == "chest":
                loot(metadata["lootFields"]["IGLOO_CHEST"], evidence)
            elif slug.startswith("shipwreck"):
                field = {"treasure_chest": "SHIPWRECK_TREASURE", "supply_chest": "SHIPWRECK_SUPPLY", "map_chest": "SHIPWRECK_MAP"}.get(text)
                if field:
                    loot(metadata["lootFields"][field], evidence)
            elif slug.startswith("ocean_ruin"):
                if text == "chest":
                    field = "UNDERWATER_RUIN_BIG" if "/big_" in evidence["template"] else "UNDERWATER_RUIN_SMALL"
                    loot(metadata["lootFields"][field], evidence)
                elif text == "drowned":
                    entity({"id": "minecraft:drowned"}, evidence)
            elif slug == "mansion":
                mob = {"Mage": "evoker", "Warrior": "vindicator", "Group of Allays": "allay"}.get(text)
                if mob:
                    entity({"id": "minecraft:" + mob}, evidence)
                elif text.startswith("Chest"):
                    loot(metadata["lootFields"]["WOODLAND_MANSION"], evidence)

        for entry in templates:
            template = sources.template(entry["template"])
            palettes = template.get("palettes", [template.get("palette", [])])
            used = {b["state"] for b in template.get("blocks", [])}
            for palette_index, palette in enumerate(palettes):
                for index in used:
                    state = palette[index]
                    original = state_id(state)
                    possible, processor_loot = sources.processed(original, entry["processors"])
                    evidence = {**entry, "palette": palette_index, "state": state}
                    for value in possible:
                        if slug.startswith("ruined_portal"):
                            for output in portal_outputs(sources, value, definition, metadata):
                                block(output, {**evidence, "processor": "RuinedPortalPiece.setup/BlockAgeProcessor/BlackstoneReplaceProcessor", "setups": definition["setups"]})
                        else:
                            block(value, evidence)
                    for reference in processor_loot:
                        loot(reference["table"], {**evidence, **reference})
            for b in template.get("blocks", []):
                nbt = b.get("nbt", {})
                evidence = {**entry, "position": b["pos"]}
                if nbt.get("id") == "minecraft:jigsaw":
                    block(state_id(nbt.get("final_state", "minecraft:air")), {**evidence, "jigsawFinalState": nbt.get("final_state")})
                elif nbt.get("id") == "minecraft:structure_block":
                    marker(nbt.get("metadata", ""), {**evidence, "marker": nbt.get("metadata", "")})
                else:
                    container(nbt, evidence)
            for value in template.get("entities", []):
                entity(value["nbt"], {**entry, "position": value["pos"]})
                container(value["nbt"], {**entry, "position": value["pos"]})
        for entry in pool_features:
            for output in feature_outputs.placed(entry["placedFeature"]):
                block(output, entry)
        if feature_id:
            if not templates:
                for output in feature_outputs.feature(feature_id):
                    block(output, {"feature": feature_id, "definition": feature_outputs.features[feature_id]})
            if feature_id == "minecraft:monster_room":
                for mob in ("skeleton", "zombie", "spider"):
                    entity({"id": "minecraft:" + mob}, {"sourceClass": "MonsterRoomFeature", "condition": "Weighted dungeon spawner selection"}, True)
                loot(metadata["lootFields"]["SIMPLE_DUNGEON"], {"sourceClass": "MonsterRoomFeature.createChest"})
            if feature_id == "minecraft:end_spike":
                item_evidence["minecraft:end_crystal"].append({"sourceClass": "SpikeFeature.placeSpike", "condition": "Crystal placed on top of generated End spike"})
            if feature_id == "minecraft:end_podium_active":
                block("minecraft:dragon_egg", {"sourceClass": "EndDragonFight.setDragonKilled", "condition": "Only after the first dragon kill; hasPreviouslyKilledDragon is false"})
        evidence = {"sourceClass": SOURCE_CLASSES.get(slug, definition.get("type")), "condition": "Piece, terrain and random-generation checks"}
        for value in PROCEDURAL_BLOCKS.get(slug, "").split():
            block("minecraft:" + value, evidence)
        for field in PROCEDURAL_LOOT.get(slug, []):
            loot(metadata["lootFields"][field], {**evidence, "lootTableField": field})
        for value in PROCEDURAL_MOBS.get(slug, []):
            entity({"id": "minecraft:" + value}, evidence)
        for value in PROCEDURAL_SPAWNERS.get(slug, []):
            entity({"id": "minecraft:" + value}, evidence, True)
        if slug.startswith("mineshaft"):
            item_evidence["minecraft:chest_minecart"].append({**evidence, "entityType": "minecraft:chest_minecart"})
        if slug.startswith("ruined_portal"):
            for value in ("netherrack", "magma_block"):
                block("minecraft:" + value, {"sourceClass": "RuinedPortalPiece.spreadNetherrack/addNetherrackDripColumns"})
            if any(s["vines"] for s in definition["setups"]):
                block("minecraft:vine", {"sourceClass": "RuinedPortalPiece.maybeAddVines"})
            if any(s["overgrown"] for s in definition["setups"]):
                block("minecraft:jungle_leaves", {"sourceClass": "RuinedPortalPiece.maybeAddLeavesAbove"})

        for biome in sorted(biome_ids):
            add("structure_biome", sid, "biome:" + biome, slug + "/biome/" + biome.split(":")[1],
                "The structure can generate in this biome. Structure placement, spacing, terrain and height checks still apply.",
                biomeSelector=definition.get("biomes"), featureId=feature_id)
        for value, evidence in sorted(block_evidence.items()):
            evidence = list({json.dumps(entry, sort_keys=True): entry for entry in evidence}.values())
            add("structure_block", sid, block_node(value), slug + "/block/" + value.split(":")[1],
                "This block can be placed by the structure's template, processor or procedural piece. It is not guaranteed in every variant; markers, empty air and terrain-only tests are omitted.",
                blockId=value, generationSources=evidence, conditional=True)
        for value, evidence in sorted(item_evidence.items()):
            add("structure_item", sid, value, slug + "/item/" + value.split(":")[1],
                "This item or decoration is placed as fixed structure content, separately from randomly rolled container loot.",
                generationSources=evidence, conditional=True)
        for kind, mapping, note in (("structure_generated_mob", mob_evidence, "Placed during structure generation; not a biome natural-spawn entry."),
                                    ("structure_spawner_mob", spawner_evidence, "Produced by a generated spawner when its activation, light, difficulty and player/proximity rules allow it; not an initially placed resident.")):
            for target, evidence in sorted(mapping.items()):
                add(kind, sid, target, slug + "/" + kind + "/" + target.split(":")[-1], note,
                    generationSources=evidence, conditional=True)
        for category, override in definition.get("spawn_overrides", {}).items():
            for index, spawn in enumerate(override["spawns"]):
                if spawn["weight"] <= 0:
                    continue
                add("structure_spawn_mob", sid, "mob:" + spawn["type"], slug + "/spawn/" + category + "/" + str(index),
                    "The structure overrides this category's natural spawn list inside its configured bounding box. Spawn placement, light, difficulty and population checks apply. This is distinct from initial residents or spawner-produced mobs.",
                    spawnCategory=category, boundingBox=override["bounding_box"], spawnEntry=spawn, conditional=True)
        loot_contexts = {}
        for table, evidence in sorted(loot_evidence.items()):
            coverage["lootTables"].add(table)
            # Multiple instances share the same possible outputs; keep their contexts together.
            evidence = list({json.dumps(value, sort_keys=True): value for value in evidence}.values())
            loot_contexts[table] = evidence
            for index, drop in enumerate(iter_loot_items(game, table)):
                add("structure_loot", sid, drop["item"], slug + "/loot/" + table.replace(":", "/") + "/" + str(index),
                    "Possible structure container, archaeology, vault or trial reward output. Loot predicates, weighted selection, item counts/components and the source context are retained; this is not a guaranteed drop.",
                    category="loot", loot=drop, sourceLootTable=table, contextRef={"nodeId": sid, "lootTable": table}, conditional=True)
        structure_nodes[sid]["lootContexts"] = loot_contexts
        coverage["structures"][sid] = {"templates": sorted({entry["template"] for entry in templates}),
            "templateVariants": len(templates), "placedFeatures": sorted({entry["placedFeature"] for entry in pool_features}),
            "blocks": sorted(block_evidence), "fixedItems": sorted(item_evidence), "generatedMobs": sorted(mob_evidence),
            "spawnerMobs": sorted(spawner_evidence), "lootTables": sorted(loot_evidence), "biomes": sorted(biome_ids),
            "spawnOverrides": definition.get("spawn_overrides", {}), "proceduralClass": SOURCE_CLASSES.get(slug)}

    def new_structure(slug, name, definition, **extra):
        sid = "structure:minecraft:" + slug
        node = {"id": sid, "kind": "structure", "structureId": "minecraft:" + slug, "name": name,
                "icon": "assets/structures/" + slug + ".png", "iconDescription": "Representative blocks from this structure, rendered from game assets.",
                "note": "Possible vanilla generation, with per-variant conditions retained. Dimensions are reached through biome relationships.",
                "definition": definition, **extra, **bounds}
        nodes.append(node); ids.add(sid)
        structure_nodes[sid] = node
        structure_emblem(slug, existing)
        return sid

    for resource, definition in sorted(definitions.items()):
        slug = resource.split(":")[1]
        name = slug.replace("_", " ").title()
        sid = new_structure(slug, name, definition)
        if definition["type"] == "minecraft:jigsaw":
            templates, features, pools = sources.jigsaw(definition)
        else:
            templates, features, pools = procedural_templates(sources, slug, definition, metadata), [], {}
            if not templates and slug not in PROCEDURAL_BLOCKS:
                raise ValueError("Structure generator is not audited: " + resource)
        inspect(sid, slug, definition, templates, features, biome_members(definition["biomes"]))
        coverage["structures"][sid]["pools"] = sorted(pools)

    feature_biomes = biome_feature_structures(game)
    for resource, biomes in sorted(feature_biomes.items()):
        slug = resource.split(":")[1]
        definition = feature_outputs.features[resource]
        label = {"monster_room": "Dungeon", "amethyst_geode": "Amethyst Geode", "desert_well": "Desert Well",
                 "fossil_coal": "Overworld Fossil (Coal)", "fossil_diamonds": "Overworld Fossil (Diamonds)"}.get(slug, slug.replace("_", " ").title())
        sid = new_structure(slug, label, definition, featureId=resource, generationKind="feature")
        inspect(sid, slug, definition, feature_templates(feature_outputs, resource), [], biomes, resource)

    runtime_sites = {
        "minecraft:end_podium_inactive": ("End Exit Fountain (Inactive)", "Initial central End fight arena; no exit portal until the dragon is defeated"),
        "minecraft:end_podium_active": ("End Exit Fountain (Active)", "EndDragonFight activates the central exit portal after a dragon is defeated"),
        "minecraft:end_gateway_delayed": ("Central End Gateway", "EndDragonFight creates a gateway at a selected position approximately 96 blocks from the central arena after a dragon kill"),
    }
    for resource, (label, trigger) in runtime_sites.items():
        if resource in feature_biomes:
            continue
        slug = resource.split(":")[1]
        definition = feature_outputs.features[resource]
        sid = new_structure(slug, label, definition, featureId=resource, generationKind="runtime", runtimeTrigger=trigger,
                            sourceClass="EndDragonFight.spawnExitPortal/spawnNewGateway", positionCondition="Central End island around the world origin; vanilla End biome source selects minecraft:the_end here")
        structure_nodes[sid]["note"] = trigger + ". Central End island around the world origin; the vanilla End biome source selects The End here. This site is generated by End fight events, separately from ordinary biome decoration."
        inspect(sid, slug, definition, feature_templates(feature_outputs, resource), [], {"minecraft:the_end"}, resource)
        coverage["structures"][sid]["runtimeTrigger"] = trigger

    coverage.update({"featureStructures": len(feature_biomes), "runtimeSites": sorted(runtime_sites), "nodes": sum(n["kind"] == "structure" for n in nodes),
        "additionalBlocks": sorted(n["blockId"] for n in nodes if n["kind"] == "block"), "records": len(records), "edges": len(edges),
        "templatesInspected": len(sources.templates), "allVanillaTemplates": sum(p.startswith("data/minecraft/structure/") and p.endswith(".nbt") for p in game.jar.namelist()),
        "missingVanillaTemplateReferences": sorted(sources.missing_templates),
        "lootTables": sorted(coverage["lootTables"]), "templateEntitiesNotRepresented": sorted(coverage["templateEntitiesNotRepresented"]),
        "limitations": ["Possible outputs across structure variants, not a seed-specific simulation. Jigsaw depth and connector names are checked, including terminal fallbacks; collision, connector orientation, distance and terrain constraints are conditional generation checks rather than simulated.",
                        "Procedural piece and processor extras were audited against this version's game code; adding another version requires a new audit.",
                        "Dynamic items picked up by residents and copied surrounding terrain are not enumerable fixed structure contents.",
                        "Icons are representative game-block emblems, not full structure previews.",
                        "The optional world-setting bonus chest is not represented; this is a starter item container, not biome decoration or a registered structure."]})
    return {"nodes": nodes, "relationships": records, "edges": edges, "coverage": coverage}
