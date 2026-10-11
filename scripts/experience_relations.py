"""Experience orb sources and coral death transitions for the audited game snapshot."""
import json
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
ORB = "entity:minecraft:experience_orb"
# These Mob subclasses have zero death XP in the 26.3 constructors/reward methods.
NO_DEATH_XP = {"allay", "bat", "copper_golem", "creaking", "iron_golem", "snow_golem", "villager", "wandering_trader"}


def build_experience(game, recipes, version, existing_nodes, existing_edges):
    if version != "26.3":
        raise ValueError("Experience sources need a new game behavior audit")
    metadata = json.loads((ROOT / ".cache/gathering-metadata.json").read_text(encoding="utf-8"))
    if metadata["version"] != version or not metadata.get("coralDeaths") or not metadata.get("blockExperience"):
        raise ValueError("Regenerate gathering metadata with experience and coral mappings")
    mob_report = json.loads((ROOT / ".cache/mob-models.json").read_text(encoding="utf-8"))
    if mob_report["entities"]["minecraft:experience_orb"]["mob"]:
        raise ValueError("Experience orb must be a non-mob entity")
    bounds = {"minVersion": version, "maxVersion": None}
    language = json.loads(game.jar.read("assets/minecraft/lang/en_us.json"))
    node = {"id": ORB, "kind": "entity", "entityType": "minecraft:experience_orb",
            "name": language["entity.minecraft.experience_orb"], "icon": "assets/entities/experience_orb.png",
            "note": "A non-mob entity carrying experience points. Sources below describe conditional game actions; an item alone does not produce an orb.", **bounds}
    # ExperienceOrbRenderer at age zero multiplies the sprite by RGB (127,255,3).
    texture = Image.open(BytesIO(game.jar.read("assets/minecraft/textures/entity/experience/experience_orb.png"))).convert("RGBA")
    icon_path = ROOT / node["icon"]
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    sprite = texture.crop((0, 0, 16, 16))
    ImageChops.multiply(sprite, Image.new("RGBA", sprite.size, (127, 255, 3, 255))).save(icon_path)
    ids = {item["id"] for item in existing_nodes} | {ORB}
    records, edges = [], []

    def block_node(block_id):
        item = metadata["blockItems"][block_id]
        return item if item != "minecraft:air" else "block:" + block_id

    def add(kind, sources, target, key, note, category="experience", **extra):
        if any(source not in ids for source in sources) or target not in ids:
            raise ValueError(f"Missing experience/coral endpoint: {sources} -> {target}")
        record_id = "experience:" + key
        records.append({"id": record_id, "category": category, "type": kind,
                        "inputs": [{"nodeId": source} for source in sources], "outputs": [{"nodeId": target}],
                        "note": note, "source": "audited_game_code_and_registry", **extra, **bounds})
        for source in sources:
            edges.append({"id": record_id + ":" + source, "source": source, "target": target,
                          "category": category, "type": kind, "relationId": record_id, **bounds})

    for living, dead in metadata["coralDeaths"].items():
        add("coral_dying", [block_node(living)], block_node(dead), "coral/" + living,
            "The placed living coral changes to its matching dead coral after its scheduled water check fails. Coral blocks need neighboring water; plants and fans can also survive waterlogged. Inventory items do not die. Dead coral cannot be revived with water.",
            category="interactions", placedBlock=living, resultBlock=dead,
            conditions=["Placed living coral", "No qualifying surrounding water or waterlogging"],
            sourceClass="CoralBlock/CoralPlantBlock/CoralFanBlock/CoralWallFanBlock.tick")
    xp_blocks = dict(metadata["blockExperience"])
    # These use custom spawnAfterBreak methods instead of DropExperienceBlock.
    xp_blocks.update({"minecraft:redstone_ore": {"min": 1, "max": 5}, "minecraft:deepslate_redstone_ore": {"min": 1, "max": 5},
                      "minecraft:spawner": {"min": 15, "max": 43}, "minecraft:sculk_sensor": {"min": 5, "max": 5},
                      "minecraft:calibrated_sculk_sensor": {"min": 5, "max": 5}, "minecraft:sculk_shrieker": {"min": 5, "max": 5}})
    for block, xp in xp_blocks.items():
        add("mining_experience", [block_node(block)], ORB, "mining/" + block,
            "Break this placed block with a valid tool while block drops are enabled. Silk Touch suppresses ore/sculk experience; a mob spawner awards XP when destroyed even though it has no ordinary item drop. XP is separate from the block's loot.",
            blockId=block, experience=xp, conditions=["Valid harvest/tool", "Block drops enabled", "No Silk Touch (except spawner)"])
    for mob in (n for n in existing_nodes if n["kind"] == "mob"):
        slug = mob["entityType"].split(":")[1]
        if slug in NO_DEATH_XP:
            continue
        note = ("The Ender Dragon awards death-animation experience while mob loot is enabled: 12,000 on the first dragon-fight kill, 500 on later kills."
                if slug == "ender_dragon" else
                "A qualifying kill awards experience while mob loot is enabled. Normally requires recent player/tamed-wolf damage; some mobs always drop XP. Age, size, equipment and enchantments can affect rewards; ordinary animal babies and baby sulfur cubes give none. Sculk catalyst consumption can prevent orbs spawning.")
        add("mob_experience", [mob["id"]], ORB, "mob/" + slug, note, sourceClass=mob["sourceClass"],
            conditions=["Qualifying death", "Mob loot enabled", "Positive experience reward", "Not consumed by a sculk catalyst"])
    stations = {"smelting": "furnace", "blasting": "blast_furnace", "smoking": "smoker"}
    for recipe in recipes:
        if recipe["type"] not in stations or recipe.get("experience", 0) <= 0:
            continue
        sources = sorted({item for group in recipe["ingredients"] for item in group["items"]})
        sources.append("minecraft:" + stations[recipe["type"]])
        add("smelting_experience", sources, ORB, "cooking/" + recipe["id"],
            "Complete this cooking recipe in its listed workstation and collect stored experience by taking output or breaking the station. The recipe's XP per operation may be fractional; the game rounds probabilistically. Campfire cooking gives no XP.",
            cookingRecipeId=recipe["id"], experiencePerOperation=recipe["experience"],
            conditions=["Complete cooking recipe", "Collect stored workstation experience"])
    breeding_mobs = sorted({edge["target"] for edge in existing_edges if edge["type"] == "breeding" and edge["target"].startswith("mob:")})
    for mob in breeding_mobs:
        add("breeding_experience", [mob], ORB, "breeding/" + mob,
            "Successful player-initiated animal breeding spawns 1–7 XP, subject to mob loot rules. Merely feeding or taming an animal does not award this breeding XP.", experience={"min": 1, "max": 7})
    add("fishing_experience", ["minecraft:fishing_rod"], ORB, "fishing", "Successfully catch fishing loot; reeling in a catch awards 1–6 XP independently of the selected item.", experience={"min": 1, "max": 6})
    add("bottle_experience", ["minecraft:experience_bottle"], ORB, "bottle", "Throw a Bottle o' Enchanting; its projectile breaks and spawns experience worth 3–11 XP.", experience={"min": 3, "max": 11})
    add("disenchanting_experience", ["minecraft:grindstone"], ORB, "grindstone", "Use a grindstone to remove non-curse enchantments. Experience depends on the removed enchantments; plain repair and curse-only items award none.")
    return {"nodes": [node], "relationships": records, "edges": edges,
            "coverage": {"coralStateMappings": len(metadata["coralDeaths"]), "miningExperienceBlocks": len(xp_blocks),
                         "mobExperienceSources": len([r for r in records if r["type"] == "mob_experience"]),
                         "noDeathExperienceMobs": sorted(NO_DEATH_XP), "limitations": ["XP rewards remain conditional; customized enchantment/advancement rewards, player deaths and trade offers are not enumerated."]}}
