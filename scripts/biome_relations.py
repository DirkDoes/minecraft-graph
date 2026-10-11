"""Biome, dimension and natural generation relationships from the vanilla worldgen registries."""
import json
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMPTY_BLOCKS = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air", "minecraft:structure_void", "minecraft:structure_block", "minecraft:jigsaw"}
STRUCTURE_FEATURES = {"minecraft:amethyst_geode", "minecraft:monster_room", "minecraft:desert_well", "minecraft:fossil_coal", "minecraft:fossil_diamonds", "minecraft:sulfur_spring",
                      "minecraft:end_gateway_delayed", "minecraft:end_gateway_return", "minecraft:end_platform", "minecraft:end_podium_active", "minecraft:end_podium_inactive",
                      "minecraft:end_spike", "minecraft:bonus_chest", "minecraft:void_start_platform"}


def registry(game, name):
    prefix = "data/minecraft/worldgen/" + name + "/"
    return {"minecraft:" + path.removeprefix(prefix).removesuffix(".json"): json.loads(game.jar.read(path))
            for path in game.jar.namelist() if path.startswith(prefix) and path.endswith(".json")}


class FeatureOutputs:
    """Read output providers, never placement/replacement match predicates."""
    def __init__(self, game, exclude_structures=False):
        self.game = game
        self.features = registry(game, "feature")
        self.placements = registry(game, "placed_feature")
        self.providers = registry(game, "block_state_provider")
        self.block_tags = {"minecraft:" + path.removeprefix("data/minecraft/tags/block/").removesuffix(".json"): json.loads(game.jar.read(path))
                           for path in game.jar.namelist() if path.startswith("data/minecraft/tags/block/") and path.endswith(".json")}
        self.exclude_structures = exclude_structures
        self.visited_types = set()
        self.feature_cache = {}

    def tag(self, value, trail=()):
        if isinstance(value, list):
            return set().union(*(self.tag(item, trail) for item in value))
        if not value.startswith("#"):
            return {value}
        name = value[1:]
        if name in trail:
            raise ValueError(f"Cyclic block tag: {name}")
        return set().union(*(self.tag(item["id"] if isinstance(item, dict) else item, trail + (name,))
                             for item in self.block_tags[name]["values"]))

    def provider(self, value):
        if isinstance(value, str):
            return self.provider(self.providers[value]) if value in self.providers else self.tag(value)
        if isinstance(value, list):
            return set().union(*(self.provider(item) for item in value))
        if "id" in value:
            return {value["id"]}
        kind = value["type"].removeprefix("minecraft:")
        if kind in {"rotated", "simple_state_provider"}:
            return self.provider(value["state"])
        if kind == "randomized_int":
            return self.provider(value["source"])
        if kind == "weighted":
            return set().union(*(self.provider(entry["data"]) for entry in value["entries"] if entry["weight"] > 0))
        if kind == "random_block":
            return self.tag(value["blocks"])
        if kind == "rule_based":
            result = self.provider(value["fallback"]) if "fallback" in value else set()
            for rule in value["rules"]:
                result.update(self.provider(rule["then"]))
            return result
        if kind in {"noise", "dual_noise", "noise_threshold"}:
            return set().union(*(self.provider(value[key]) for key in ("states", "default_state", "low_states", "high_states") if key in value))
        raise ValueError(f"Unaudited block state provider: {kind}")

    def placed(self, value, trail=()):
        if isinstance(value, str):
            if value in self.placements:
                value = self.placements[value]
            else:
                return self.feature(value, trail)
        return self.feature(value if "type" in value else value["feature"], trail)

    def references(self, value, trail=(), feature=False):
        """Reachable named feature IDs, including structure-like decoration roots."""
        if isinstance(value, str):
            if not feature and value in self.placements:
                return self.references(self.placements[value]["feature"], trail, True)
            if value not in self.features:
                raise ValueError(f"Unknown feature: {value}")
            if value in trail:
                raise ValueError(f"Cyclic feature: {value}")
            return {value} | self.references(self.features[value], trail + (value,))
        if isinstance(value, list):
            return set().union(*(self.references(item, trail) for item in value))
        if "data" in value:
            return self.references(value["data"], trail)
        if "type" not in value and "feature" in value:
            return self.references(value["feature"], trail, "placement" in value)
        result = set()
        for key in ("feature", "default", "feature_true", "feature_false", "vegetation_feature", "cap_feature"):
            if key in value:
                result.update(self.references(value[key], trail))
        for entry in value.get("features", []):
            result.update(self.references(entry, trail))
        return result

    def template(self, name):
        # Reuse the structure extractor's standard NBT reader instead of another parser.
        from structure_relations import read_nbt
        namespace, slug = name.split(":", 1)
        nbt = read_nbt(self.game.jar.read(f"data/{namespace}/structure/{slug}.nbt"))
        palettes = nbt.get("palettes", [nbt.get("palette", [])])
        return {palette[entry["state"]].get("id", palette[entry["state"]].get("Name")) for palette in palettes for entry in nbt["blocks"]}

    def feature(self, value, trail=()):
        if isinstance(value, str):
            if self.exclude_structures and value in STRUCTURE_FEATURES:
                return set()
            if value not in self.features and value in self.placements:
                return self.placed(value, trail)
            if value in trail:
                raise ValueError(f"Cyclic feature: {value}")
            if value not in self.feature_cache:
                self.feature_cache[value] = self.feature(self.features[value], trail + (value,))
            return self.feature_cache[value].copy()
        if "type" not in value and "feature" in value:
            return self.placed(value, trail)
        kind = value["type"].removeprefix("minecraft:")
        self.visited_types.add(kind)
        result = set()
        for key in ("to_place", "state_provider", "state", "block", "ground_state", "trunk_provider", "foliage_provider", "below_trunk_provider", "cap_provider", "stem_provider",
                    "decor_state", "hat_state", "stem_state", "contents", "rim", "fluid", "barrier", "base_block", "pointed_block", "root_state_provider", "hanging_root_state_provider"):
            if key in value:
                result.update(self.provider(value[key]))
        for key in ("feature", "default", "feature_true", "feature_false", "vegetation_feature", "cap_feature"):
            if key in value:
                result.update(self.placed(value[key], trail))
        for entry in value.get("features", []):
            result.update(self.placed(entry.get("data", entry), trail))
        for layer in value.get("layers", []) if isinstance(value.get("layers"), list) else []:
            result.update(self.provider(layer["provider"]))
        for target in value.get("targets", []):
            result.update(self.provider(target["state"]))
        for key, provider in value.get("blocks", {}).items():
            if key.endswith("provider") or key == "inner_placements":
                result.update(self.provider(provider))
        if "root_placer" in value:
            root = value["root_placer"]
            result.update(self.provider(root["root_provider"]))
            for key in ("above_root_placement", "mangrove_root_placement"):
                for field, provider in root.get(key, {}).items():
                    if field.endswith("provider"):
                        result.update(self.provider(provider))
        for decorator in value.get("decorators", []) + value.get("stump_decorators", []) + value.get("log_decorators", []):
            for key in ("provider", "block_provider", "block_state_provider"):
                if key in decorator:
                    result.update(self.provider(decorator[key]))
            name = decorator["type"].removeprefix("minecraft:")
            if decorator.get("probability", 1) > 0:
                result.update({"beehive": {"minecraft:bee_nest"}, "cocoa": {"minecraft:cocoa"}, "trunk_vine": {"minecraft:vine"}, "leave_vine": {"minecraft:vine"},
                               "creaking_heart": {"minecraft:creaking_heart"}, "shelf_mushroom": {"minecraft:shelf_mushroom"}}.get(name, set()))
            if name == "pale_moss":
                if max(decorator.get("leaves_probability", 0), decorator.get("trunk_probability", 0)) > 0:
                    result.add("minecraft:pale_hanging_moss")
                if decorator.get("ground_probability", 0) > 0:
                    result.update(self.feature("minecraft:pale_moss_patch", trail))
        if kind == "template":
            for template in value["templates"]:
                data = template.get("data", template)
                result.update(self.template(data["id"]))
        if kind == "fossil":
            for name in value["fossil_structures"] + value["overlay_structures"]:
                result.update(self.template(name))
        # Procedural outputs verified in 26.3 feature placement methods; predicates/debug markers are omitted.
        defaults = {"bamboo": {"minecraft:bamboo"}, "blue_ice": {"minecraft:blue_ice"}, "chorus_plant": {"minecraft:chorus_plant", "minecraft:chorus_flower"},
                    "large_dripstone": {"minecraft:dripstone_block"}, "sculk_patch": {"minecraft:sculk", "minecraft:sculk_vein", "minecraft:sculk_sensor", "minecraft:sculk_shrieker"},
                    "underwater_magma": {"minecraft:magma_block"}, "vines": {"minecraft:vine"}, "iceberg": {"minecraft:snow_block"},
                    "monster_room": {"minecraft:cobblestone", "minecraft:mossy_cobblestone", "minecraft:spawner", "minecraft:chest"},
                    "end_gateway": {"minecraft:bedrock", "minecraft:end_gateway"}, "end_island": {"minecraft:end_stone"},
                    "end_platform": {"minecraft:obsidian"}, "end_podium": {"minecraft:bedrock", "minecraft:wall_torch", "minecraft:end_stone"},
                    "end_spike": {"minecraft:obsidian", "minecraft:bedrock", "minecraft:iron_bars"},
                    "void_start_platform": {"minecraft:stone", "minecraft:cobblestone"}, "bonus_chest": {"minecraft:chest", "minecraft:torch"}}
        result.update(defaults.get(kind, set()))
        if kind == "end_podium" and value.get("active"):
            result.add("minecraft:end_portal")
        if kind == "bamboo" and value.get("probability", 0) > 0:
            result.add("minecraft:podzol")
        if kind == "waterlogged_vegetation_patch":
            result.add("minecraft:water")
        if kind == "huge_fungus" and value.get("hat_state") == "minecraft:nether_wart_block":
            result.update({"minecraft:weeping_vines", "minecraft:weeping_vines_plant"})
        known = {"tree", "simple_block", "ore", "random_selector", "overlay", "weighted_random_selector", "block_column", "vegetation_patch", "fallen_tree", "spring_feature", "disk",
                 "simple_random_selector", "block_pile", "huge_fungus", "sequence", "netherrack_replace_blobs", "speleothem_cluster", "random_boolean_selector", "root_system", "geode",
                 "waterlogged_vegetation_patch", "delta_feature", "block_blob", "freeze_top_layer", "random_neighbor_spread", "huge_brown_mushroom", "huge_red_mushroom", "spike",
                 "lake", "scattered_ore", "multiface_growth", "no_op", "single_block_pillar", "projected_random_patchy_square", "stepped_column_cluster", "speleothem", "template", "fossil", "coral_claw", "coral_tree"} | set(defaults)
        if kind not in known:
            raise ValueError(f"Unaudited feature type: {kind}")
        if not result - EMPTY_BLOCKS and kind not in {"no_op", "freeze_top_layer", "tree", "coral_tree", "coral_claw", "sequence", "overlay"}:
            raise ValueError(f"Feature unexpectedly has no output: {kind}")
        return result - EMPTY_BLOCKS


def biome_feature_structures(game):
    features = FeatureOutputs(game)
    result = defaultdict(set)
    for biome, definition in registry(game, "biome").items():
        for step in definition["features"]:
            for placed in step:
                for name in features.references(placed) & STRUCTURE_FEATURES:
                    result[name].add(biome)
    return dict(result)


def material_outputs(game, rule, biome):
    rules, conditions = registry(game, "material_rule"), registry(game, "material_condition")

    def condition(value):
        if isinstance(value, str):
            return condition(conditions[value])
        kind = value["type"].removeprefix("minecraft:")
        if kind == "biome":
            allowed = value["biome_is"]
            return biome in ([allowed] if isinstance(allowed, str) else allowed)
        if kind == "not":
            test = condition(value["invert"])
            return not test if isinstance(test, bool) else (test[0], not test[1])
        return json.dumps(value, sort_keys=True), True

    def split(paths, test):
        if isinstance(test, bool):
            return (paths, set()) if test else (set(), paths)
        atom, wanted = test
        matched, unmatched = set(), set()
        for path in paths:
            if (atom, wanted) in path:
                matched.add(path)
            elif (atom, not wanted) in path:
                unmatched.add(path)
            else:
                matched.add(path | {(atom, wanted)})
                unmatched.add(path | {(atom, not wanted)})
        return matched, unmatched

    def walk(value, paths):
        if not paths:
            return set(), set()
        if isinstance(value, str):
            return walk(rules[value], paths)
        kind = value["type"].removeprefix("minecraft:")
        if kind == "block":
            state = value["result_state"]
            return {state if isinstance(state, str) else state["id"]}, set()
        if kind == "ore_vein":
            matched, remaining = split(paths, ("ore_vein:" + value["ore_block"], True))
            return ({value[key] for key in ("filler_block", "ore_block", "raw_ore_block")} if matched else set()), remaining
        if kind == "bandlands":
            return {"minecraft:" + color + "terracotta" for color in ("", "orange_", "yellow_", "brown_", "red_", "white_", "light_gray_")}, set()
        if kind == "condition":
            matched, unmatched = split(paths, condition(value["if_true"]))
            output, remaining = walk(value["then_run"], matched)
            return output, unmatched | remaining
        if kind == "sequence":
            result = set()
            for entry in value["sequence"]:
                output, paths = walk(entry, paths)
                result.update(output)
                if not paths:
                    break
            return result, paths
        raise ValueError(f"Unaudited material rule: {kind}")

    # First matching rules win; keep predicate decisions consistent in all later branches.
    return walk(rule, {frozenset()})[0] - EMPTY_BLOCKS


def build_biomes(game, version, existing_nodes):
    if version != "26.3":
        raise ValueError("Natural generation needs a new game code audit")
    metadata = json.loads((ROOT / ".cache/biome-metadata.json").read_text(encoding="utf-8"))
    biomes = registry(game, "biome")
    if metadata["version"] != version or set(metadata["biomes"]) != set(biomes):
        raise ValueError("Biome registry metadata does not match the game")
    language = json.loads(game.jar.read("assets/minecraft/lang/en_us.json"))
    block_items = json.loads((ROOT / ".cache/gathering-metadata.json").read_text(encoding="utf-8"))["blockItems"]
    preset = registry(game, "world_preset")["minecraft:normal"]
    dimensions = preset["dimensions"]
    bounds = {"minVersion": version, "maxVersion": None}
    ids = {node["id"] for node in existing_nodes}
    existing = {node["id"]: node for node in existing_nodes}
    nodes, records, edges = [], [], []

    def add(kind, source, target, suffix, note, **extra):
        if target not in ids:
            raise ValueError(f"Missing natural generation endpoint: {target}")
        record_id = "worldgen:" + suffix
        records.append({"id": record_id, "category": "worldgen", "type": kind, "inputs": [{"nodeId": source}], "outputs": [{"nodeId": target}],
                        "note": note, "source": "vanilla_worldgen_definitions_and_audited_code", **extra, **bounds})
        edges.append({"id": record_id, "source": source, "target": target, "category": "worldgen", "type": kind, "relationId": record_id, **bounds})

    def block_node(block):
        item = block_items[block]
        return item if item != "minecraft:air" else "block:" + block

    def icon(folder, slug, item):
        target = ROOT / "assets" / folder / (slug + ".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / existing[item]["icon"], target)
        return target.relative_to(ROOT).as_posix()

    dimension_biomes, biome_dimensions = {}, {}
    for dim, definition in dimensions.items():
        slug = dim.split(":")[1]
        source = definition["generator"]["biome_source"]
        if source["type"] == "minecraft:multi_noise":
            parameters = registry(game, "multi_noise_biome_source_parameter_list")[source["preset"]]
            members = metadata["presets"][parameters["preset"]]
        elif source["type"] == "minecraft:the_end":
            members = metadata["endBiomes"]
        else:
            raise ValueError(f"Unexpected normal world biome source: {source}")
        dimension_biomes[dim] = list(members)
        for biome in members:
            biome_dimensions[biome] = dim
        art = {"overworld": "grass_block", "the_nether": "netherrack", "the_end": "end_stone"}[slug]
        node = {"id": "dimension:" + dim, "kind": "dimension", "dimensionId": dim,
                "name": {"overworld": "Overworld", "the_nether": "The Nether", "the_end": "The End"}[slug],
                "icon": icon("dimensions", slug, "minecraft:" + art), "note": "A vanilla dimension. Structures connect through their biome rather than directly to this dimension.", **bounds}
        nodes.append(node); ids.add(node["id"])
    # The Void is a real registry biome, available in the Overworld's generated flat preset.
    flat_void = registry(game, "flat_level_generator_preset")["minecraft:the_void"]
    if flat_void["settings"]["biome"] != "minecraft:the_void":
        raise ValueError("Unexpected Void flat preset")
    biome_dimensions["minecraft:the_void"] = "minecraft:overworld"
    if set(biome_dimensions) != set(biomes):
        raise ValueError("Unmapped registered biomes")
    features = FeatureOutputs(game, exclude_structures=True)
    representative = {"desert": "cactus", "badlands": "red_sand", "eroded_badlands": "red_sand", "wooded_badlands": "terracotta", "swamp": "lily_pad", "mangrove_swamp": "mangrove_log",
                      "pale_garden": "pale_oak_log", "dappled_forest": "poplar_log", "cherry_grove": "cherry_leaves", "mushroom_fields": "red_mushroom_block", "lush_caves": "moss_block",
                      "dripstone_caves": "pointed_dripstone", "sulfur_caves": "sulfur", "deep_dark": "sculk", "basalt_deltas": "basalt", "soul_sand_valley": "soul_sand",
                      "crimson_forest": "crimson_nylium", "warped_forest": "warped_nylium", "nether_wastes": "netherrack", "the_void": "barrier", "warm_ocean": "brain_coral_block",
                      "bamboo_jungle": "bamboo", "sunflower_plains": "sunflower", "flower_forest": "allium", "meadow": "dandelion"}
    for biome, definition in sorted(biomes.items()):
        slug = biome.split(":")[1]
        dim = biome_dimensions[biome]
        art = representative.get(slug)
        if art is None:
            art = ("end_stone" if dim == "minecraft:the_end" else "packed_ice" if "frozen" in slug or slug == "ice_spikes" else
                   "snow_block" if "snow" in slug or slug in {"grove", "jagged_peaks"} else "water_bucket" if "ocean" in slug or "river" in slug else
                   "sand" if "beach" in slug else "stone" if "stony" in slug else "birch_log" if "birch" in slug else "spruce_log" if "taiga" in slug else
                   "jungle_log" if "jungle" in slug else "acacia_log" if "savanna" in slug else "oak_log" if "forest" in slug else "grass_block")
        node_id = "biome:" + biome
        nodes.append({"id": node_id, "kind": "biome", "biomeId": biome, "name": language["biome.minecraft." + slug],
                      "icon": icon("biomes", slug, "minecraft:" + art), "temperature": definition["temperature"], "downfall": definition["downfall"],
                      "note": "Natural generation and spawn possibilities from this biome's vanilla definitions. Icons use representative game blocks. Placement, height, climate and mob-specific checks still apply; structure contents connect through the structure.", **bounds})
        ids.add(node_id)
        add("biome_dimension", node_id, "dimension:" + dim, "dimension/" + slug,
            "This biome is selected by the dimension's vanilla biome source." if slug != "the_void" else "The Void is used by the Overworld's The Void flat-world preset; it does not generate in a normal Overworld.",
            biomeSource=dimensions[dim]["generator"]["biome_source"] if slug != "the_void" else {"type": "minecraft:flat", "preset": "minecraft:the_void"})
        evidence = defaultdict(set)
        if slug != "the_void":
            settings_id = dimensions[dim]["generator"]["settings"]
            settings = registry(game, "noise_settings")[settings_id]
            for block in {settings["default_block"], settings["default_fluid"]} | material_outputs(game, settings["material_rule"], biome):
                evidence[block].add("noise_settings/" + settings_id + " + biome-filtered material rules")
            if dim == "minecraft:overworld":
                evidence["minecraft:lava"].add("NoiseChunk fluid picker: deep lava aquifers below y=-54")
        for step, placements in enumerate(definition["features"]):
            for placed in placements:
                for block in features.placed(placed):
                    evidence[block].add("placed_feature/" + placed + " (generation step " + str(step) + ")")
                if "minecraft:freeze_top_layer" in features.references(placed) and definition["has_precipitation"] and definition["temperature"] < 0.46:
                    for block in ("minecraft:ice", "minecraft:snow"):
                        evidence[block].add("SnowAndFreezeFeature with Biome.shouldFreeze/shouldSnow: cold enough at the position's height")
        for block, sources in sorted(evidence.items()):
            if block in EMPTY_BLOCKS:
                continue
            add("biome_block", node_id, block_node(block), "block/" + slug + "/" + block.split(":")[1],
                "This block can be produced by the biome's natural terrain or decoration, outside structure generation. This describes possible outputs, not guaranteed presence in every chunk; placement predicates, height, random chances and local climate still apply.",
                blockId=block, generationSources=sorted(sources), conditions=["Vanilla natural generation", "Placement and block survival checks", "Suitable height and terrain"])
        spawns = definition["attributes"]["minecraft:gameplay/natural_mob_spawns"]
        if spawns["modifier"] != "overlay":
            raise ValueError("Unexpected natural spawn attribute modifier")
        for category, entries in spawns["argument"]["spawns_by_category"].items():
            for index, entry in enumerate(entries):
                target = "mob:" + entry["type"]
                add("biome_spawn", node_id, target, "spawn/" + slug + "/" + category + "/" + entry["type"].split(":")[1] + "/" + str(index),
                    "The biome lists this entity for natural spawning, separately from entities placed during structure generation and structure-specific spawn overrides. Mob-specific light, floor/fluid, altitude, difficulty and population checks apply; the weight is relative to entries in this spawn category.",
                    spawnCategory=category, spawnWeight=entry["weight"], spawnCount=entry["count"], spawnCost=spawns["argument"]["spawn_costs"].get(entry["type"]),
                    conditions=["Natural spawning enabled", "Mob-specific spawn placement checks", "Category population cap", "Suitable terrain, light and fluid"])
    return {"nodes": nodes, "relationships": records, "edges": edges, "coverage": {"registeredBiomes": len(biomes), "dimensions": len(dimensions),
            "dimensionBiomes": dimension_biomes, "naturalBlockRelationships": sum(r["type"] == "biome_block" for r in records),
            "naturalSpawnRelationships": sum(r["type"] == "biome_spawn" for r in records), "featureTypesAudited": sorted(features.visited_types),
            "excludedFeatureStructures": sorted(STRUCTURE_FEATURES), "limitations": ["Outputs describe possible vanilla generation, subject to placement, terrain, height and climate checks; they do not guarantee presence in a particular seed.",
                "Empty air and template marker blocks are omitted. The Void is linked via its Overworld flat-world preset, not normal terrain."]}}
