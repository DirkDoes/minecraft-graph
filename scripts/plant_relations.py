"""Plant and existing mob/workstation connections, restricted to represented nodes."""
import hashlib
import json
from pathlib import Path

from mob_relations import iter_loot_items

ROOT = Path(__file__).resolve().parents[1]


def build_plants(game, version, existing_nodes):
    if version != "26.3":
        raise ValueError("Plant and NPC interactions need a new version audit")
    metadata = json.loads((ROOT / ".cache/plant-metadata.json").read_text(encoding="utf-8"))
    if metadata["version"] != version or metadata["clientSha1"] != hashlib.sha1((ROOT / ".cache/client.jar").read_bytes()).hexdigest():
        raise ValueError("Regenerate plant metadata for this client")
    block_items = json.loads((ROOT / ".cache/gathering-metadata.json").read_text(encoding="utf-8"))["blockItems"]
    ids = {node["id"] for node in existing_nodes}
    bounds = {"minVersion": version, "maxVersion": None}
    records, edges = [], []

    def block_node(block_id):
        item = block_items[block_id]
        return item if item != "minecraft:air" else "block:" + block_id

    def add(kind, from_id, target, key, note, **extra):
        if from_id not in ids or target not in ids:
            raise ValueError(f"Unknown plant/NPC endpoint: {from_id} -> {target}")
        record_id = "interaction:plant/" + key
        records.append({"id": record_id, "type": kind, "category": "uses", "name": kind.replace("_", " ").title(),
                        "inputs": [{"nodeId": from_id}], "outputs": [{"nodeId": target}], "note": note,
                        "source": "audited_game_registry_and_behavior", **extra, **bounds})
        edges.append({"id": record_id + ":" + from_id + ">" + target, "source": from_id, "target": target,
                      "category": "uses", "type": kind, "relationId": record_id, **bounds})

    omitted = []
    for block_id, class_name in metadata["bonemealable"].items():
        target = block_node(block_id)
        if target not in ids:
            omitted.append(block_id)
            continue
        add("fertilizing", "minecraft:bone_meal", target, "bone_meal/" + block_id,
            "Bone Meal can target this block type. The game's isValidBonemealTarget and success checks depend on block state, space, substrate and surroundings; the represented item must be placed. This link does not promise a harvest or a generated tree.",
            targetBlock=block_id, gameClass=class_name,
            conditions=["Valid block state and surroundings", "Game bonemeal success check"])
    for block_id, crop in metadata["crops"].items():
        for harvest_block in sorted({block_id, crop["matureBlock"]}):
            table = "minecraft:blocks/" + harvest_block.split(":")[1]
            for index, loot in enumerate(iter_loot_items(game, table)):
                add("crop_growing", crop["seed"], loot["item"], f"crop/{block_id}/{harvest_block}/{index}",
                    "Plant this seed/crop item on a valid substrate and grow the crop. These are possible harvest outputs; maturity, random yield, tools and loot conditions are retained. Seed returns are separate self-loops.",
                    targetBlock=block_id, harvestBlock=harvest_block, maxAge=crop["maxAge"], loot=loot)
    for block_id, stem in metadata["stems"].items():
        add("crop_growing", stem["seed"], block_node(stem["fruit"]), "stem/" + block_id,
            "The planted stem must mature and have a valid adjacent fruit position/support. The seed is consumed on planting; fruit generation is conditional.",
            targetBlock=block_id, fruitBlock=stem["fruit"], source="StemBlock registry fruit and seed fields")

    # These are the actual 26.3 job-site block mappings; profession stays a predicate on Villager.
    jobs = {"armorer": "blast_furnace", "butcher": "smoker", "cartographer": "cartography_table", "cleric": "brewing_stand",
            "farmer": "composter", "fisherman": "barrel", "fletcher": "fletching_table", "leatherworker": "cauldron",
            "librarian": "lectern", "mason": "stonecutter", "shepherd": "loom", "toolsmith": "smithing_table", "weaponsmith": "grindstone"}
    for profession, slug in jobs.items():
        add("villager_workstation", "minecraft:" + slug, "mob:minecraft:villager", "job/" + profession,
            "An eligible adult Villager can claim this job-site block and use it to work/restock. The profession must match; nitwits, babies and already locked professions cannot freely switch. This is not a trade offer.",
            profession="minecraft:" + profession, source="VillagerProfession and PoiTypes bootstrap mappings")
    for slug in ("wheat", "carrot", "potato", "beetroot"):
        add("villager_harvesting", "mob:minecraft:villager", "minecraft:" + slug, "farmer/" + slug,
            "A Farmer harvests mature nearby crops when mobGriefing allows it and inventory/AI conditions permit. Seeds/replanting and drops follow the crop's normal rules.",
            profession="minecraft:farmer", source="HarvestFarmland behavior")
    for seed in game.resolve_tag("minecraft:villager_plantable_seeds"):
        add("villager_planting", "mob:minecraft:villager", seed, "planting/" + seed,
            "A Farmer can take this seed/crop item from its inventory and plant its block on nearby empty farmland. Placement validity and mobGriefing must allow it; this does not imply the Farmer harvests every resulting plant.",
            profession="minecraft:farmer", source="HarvestFarmland and minecraft:villager_plantable_seeds")
    for door in game.resolve_tag("minecraft:wooden_doors"):
        for mob in ("zombie", "husk", "zombie_villager", "drowned", "zombified_piglin"):
            add("door_breaking", "mob:minecraft:" + mob, door, f"door/{mob}/{door}",
                "This zombie type can have door-breaking AI enabled. A closed wooden door, Hard difficulty and mobGriefing are required; this is not enabled for every individual.",
                source="Zombie.finalizeSpawn/setCanBreakDoors, navigation.canNavigateGround and BreakDoorGoal", conditions=["Door-breaking-capable individual", "Hard difficulty", "mobGriefing"])
    return {"nodes": [], "relationships": records, "edges": edges,
            "coverage": {"registeredBonemealableBlocks": len(metadata["bonemealable"]), "representedBonemealableBlocks": len(metadata["bonemealable"]) - len(omitted),
                         "unrepresentedBlockTargets": omitted, "cropClasses": metadata["crops"], "stemClasses": metadata["stems"],
                         "jobSites": jobs, "records": len(records), "edges": len(edges),
                         "limitations": ["Bonemeal links express valid target types; world-dependent success and generated feature outputs are not simulated.",
                                         "No new plant, biome, structure, profession or player nodes. Growth targets absent from the existing graph remain omitted."]}}
