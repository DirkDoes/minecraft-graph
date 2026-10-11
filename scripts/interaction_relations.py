"""Finite vanilla interactions between the graph's existing entities.

Registry/component/tag/transformer inventories are exhaustive. Hand-coded triggers
are version-pinned, audited game rules; they do not simulate a whole world.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_interactions(game, version, existing_nodes):
    if version != "26.3":
        raise ValueError("Interaction triggers require a new game-version audit")
    metadata = json.loads((ROOT / ".cache/interaction-metadata.json").read_text(encoding="utf-8"))
    client_hash = hashlib.sha1((ROOT / ".cache/client.jar").read_bytes()).hexdigest()
    if metadata["version"] != version or metadata["clientSha1"] != client_hash:
        raise ValueError("Regenerate interaction metadata for this exact client")
    block_items = json.loads((ROOT / ".cache/gathering-metadata.json").read_text(encoding="utf-8"))["blockItems"]
    node_ids = {node["id"] for node in existing_nodes}
    bounds = {"minVersion": version, "maxVersion": None}
    relationships, edges, capabilities = [], [], {}
    omitted_blocks = set()
    raw_tags = {}
    tag_cache = {}

    def namespaced(value):
        return value if ":" in value else "minecraft:" + value

    def mob(value):
        return "mob:" + namespaced(value)

    def block(value):
        value = namespaced(value)
        item = block_items[value]
        result = item if item != "minecraft:air" else "block:" + value
        if result in node_ids:
            return result
        omitted_blocks.add(value)
        return None

    def read_json(path):
        return json.loads(game.jar.read(path))

    def resolve(domain, tag, ancestors=()):
        tag = namespaced(tag.removeprefix("#"))
        if domain == "item":
            return game.resolve_tag(tag)
        key = domain, tag
        if key in tag_cache:
            return tag_cache[key]
        if key in ancestors:
            raise ValueError(f"Cyclic {domain} tag {tag}")
        namespace, slug = tag.split(":", 1)
        document = read_json(f"data/{namespace}/tags/{domain}/{slug}.json")
        raw_tags[f"{domain}:{tag}"] = document
        values = set()
        for entry in document["values"]:
            entry = entry["id"] if isinstance(entry, dict) else entry
            if entry.startswith("#"):
                values.update(resolve(domain, entry, ancestors + (key,)))
            else:
                values.add(namespaced(entry))
        tag_cache[key] = sorted(values)
        return tag_cache[key]

    def targets(domain, value):
        if isinstance(value, list):
            return sorted({entry for part in value for entry in targets(domain, part)})
        return resolve(domain, value) if value.startswith("#") else [namespaced(value)]

    def add(kind, inputs, outputs, note, identifier, *, category="uses", source="audited_game_interaction", source_class=None, **extra):
        inputs, outputs = list(dict.fromkeys(inputs)), list(dict.fromkeys(outputs))
        if not inputs or not outputs:
            raise ValueError(f"Empty interaction {identifier}")
        for endpoint in inputs + outputs:
            if endpoint not in node_ids:
                raise ValueError(f"Unknown interaction endpoint {endpoint}: {identifier}")
        relation_id = "interaction:" + identifier
        record = {"id": relation_id, "category": category, "type": kind, "name": kind.replace("_", " ").capitalize(),
                  "inputs": [{"nodeId": entry} for entry in inputs], "outputs": [{"nodeId": entry} for entry in outputs],
                  "note": note, "source": source, **bounds, **extra}
        if source_class:
            record["sourceClass"] = source_class
        relationships.append(record)
        for start in inputs:
            for end in outputs:
                edges.append({"id": f"{relation_id}:{start}>{end}", "category": category, "type": kind,
                              "source": start, "target": end, "relationId": relation_id, **bounds})

    def tag_sources(tag):
        tag = namespaced(tag)
        values = game.resolve_tag(tag)
        category = "tag:" + tag
        return values + ([category] if category in node_ids else [])

    def tag_use(kind, tag, output, note, *, source_class, identifier=None, **extra):
        tag = namespaced(tag)
        add(kind, tag_sources(tag), [output], note, identifier or f"{kind}:{tag}:{output}",
            source="vanilla_item_tag_and_audited_interaction", source_class=source_class,
            ingredients=[{"items": game.resolve_tag(tag), "tag": tag, "count": 1}], rawTag=game.tags[tag], **extra)

    # Use the actual SpawnEggItem class/component and MobBucketItem.type registry mappings.
    for item, entity in sorted(metadata["spawnEggs"].items()):
        add("spawn_egg", [item], [mob(entity)], "Use this spawn egg to create its default mob; placement, collision and difficulty rules still apply. Customized entity data can change its entity type.",
            "spawn_egg:" + item, category="spawning", source="vanilla_item_class_and_component", source_class="net.minecraft.world.item.SpawnEggItem", raw=game.components[item]["minecraft:entity_data"])
    for item, entity in sorted(metadata["mobBuckets"].items()):
        add("bucket_release", [item], [mob(entity)], "Empty the filled mob bucket at a valid position to release its contained mob. Stored bucket entity data is restored; the bucket is returned.",
            "bucket_release:" + item, category="spawning", source="vanilla_item_class", source_class="net.minecraft.world.item.MobBucketItem")
    egg_items = [item for item, components in game.components.items() if "minecraft:chicken/variant" in components and item in game.resolve_tag("minecraft:eggs")]
    for item in sorted(egg_items):
        add("egg_hatching", [item], [mob("chicken")], "A thrown egg has a 1/8 chance to hatch. A successful hatch makes one chick, with a further 1/32 chance of four instead. The egg's Chicken Variant component selects its variant.",
            "egg_hatching:" + item, category="spawning", source_class="net.minecraft.world.entity.projectile.throwableitemprojectile.ThrownEgg", hatchChance=1/8, fourChicksConditionalChance=1/32,
            raw=game.components[item]["minecraft:chicken/variant"])
    add("ender_pearl_spawn", ["minecraft:ender_pearl"], [mob("endermite")], "A player-owned Ender Pearl impact has a 5% chance to spawn an Endermite at the player's origin before teleporting. Monster spawning must be enabled and difficulty must not be Peaceful. No night-time restriction.",
        "ender_pearl_spawn", category="spawning", source_class="net.minecraft.world.entity.projectile.throwableitemprojectile.ThrownEnderpearl", chance=.05,
        conditions=["Player owner connected to server", "Monster spawning enabled", "Difficulty not Peaceful"])
    pumpkins = ["minecraft:carved_pumpkin", "minecraft:jack_o_lantern"]
    for slug, material, count, shape in [("snow_golem", ["minecraft:snow_block"], 2, "two Snow Blocks stacked beneath a pumpkin"),
                                        ("iron_golem", ["minecraft:iron_block"], 4, "a T of four Iron Blocks, with air beside the lower block"),
                                        ("copper_golem", [block(b) for b in resolve("block", "minecraft:copper")], 1, "one Copper block from the copper block tag beneath a pumpkin")]:
        add("mob_building", material + pumpkins, [mob(slug)], "Build " + shape + "; place a Carved Pumpkin or Jack o'Lantern last. The construction blocks are consumed. Copper Golem construction leaves a matching Copper Chest at the copper block position." if slug == "copper_golem" else "Build " + shape + "; place a Carved Pumpkin or Jack o'Lantern last. The construction blocks are consumed.",
            "mob_building:" + slug, category="spawning", source_class="net.minecraft.world.level.block.CarvedPumpkinBlock",
            ingredients=[{"items": material, "count": count}, {"items": pumpkins, "count": 1}], pattern=shape)
    sand = [block(b) for b in resolve("block", "minecraft:wither_summon_base_blocks")]
    add("mob_building", sand + ["minecraft:wither_skeleton_skull"], [mob("wither")], "Build a T of four Soul Sand/Soul Soil blocks and three Wither Skeleton Skulls along the top; place a skull last. Difficulty must not be Peaceful. All seven pattern blocks are consumed.",
        "mob_building:wither", category="spawning", source_class="net.minecraft.world.level.block.WitherSkullBlock", ingredients=[{"items": sand, "count": 4}, {"items": ["minecraft:wither_skeleton_skull"], "count": 3}], conditions=["Difficulty not Peaceful", "Valid T-shaped construction with surrounding space"])
    add("creaking_heart_spawn", ["minecraft:creaking_heart"], [mob("creaking")], "An awake heart between two aligned Pale Oak Logs can create one linked Creaking near it. Requires the environment's Creaking Active attribute (normally nighttime), monster spawning, non-Peaceful difficulty, a player within 32 blocks and a valid spawn position. The heart remains.",
        "creaking_heart_spawn", category="spawning", source_class="net.minecraft.world.level.block.entity.CreakingHeartBlockEntity", conditions=["Heart awake and aligned between Pale Oak Logs", "Creaking Active environment attribute", "Monster spawning enabled", "Difficulty not Peaceful", "Player within 32 blocks", "No existing linked protector"])
    add("mob_summoning", ["minecraft:sculk_shrieker"], [mob("warden")],
        "A placed Sculk Shrieker with can_summon=true can summon a Warden after player-attributed activation raises the shared warning level to 4. It must not already be shrieking; difficulty must not be Peaceful and spawn_wardens must be enabled. Warnings are blocked by a nearby Warden or any participating player's 200-tick warning cooldown. After the 90-tick shriek, the game tries up to 20 nearby positions with a full upper collision face beneath, no liquid and enough unobstructed space. Ordinary player-placed shriekers have can_summon=false and cannot summon one; the block is not consumed.",
        "sculk_shrieker_warden", category="spawning", source_class="net.minecraft.world.level.block.entity.SculkShriekerBlockEntity / net.minecraft.world.entity.monster.warden.WardenSpawnTracker / net.minecraft.util.SpawnUtil",
        requiredBlockState={"block": "minecraft:sculk_shrieker", "can_summon": True}, warningLevelRequired=4,
        warningIncreaseCooldownTicks=200, warningDecayIntervalTicks=12000, sharedWarningPlayerRadius=16,
        nearbyWardenCheckCube=[48, 48, 48], responseDelayTicks=90, spawnAttempts=20, spawnRangeXZ=5, spawnRangeY=6,
        activation={"stepping": "A player or entity attributable to a player steps on the block",
                    "vibrationEvent": "minecraft:sculk_sensor_tendrils_clicking", "vibrationListenerRadius": 8,
                    "vibrationChecks": "Player-attributed event, no vibration occlusion, adjacent chunks ticking"},
        conditions=["Placed block state can_summon=true", "Not already shrieking at activation", "Player-attributed stepping or accepted sensor vibration",
                    "Difficulty not Peaceful", "Game rule minecraft:spawn_wardens=true", "No Warden in the 48×48×48 check cube around the shrieker",
                    "No warning cooldown among the triggering player and participating alive non-spectator players within 16 blocks",
                    "Shared warning level reaches 4", "Response follows the 90-tick shriek or removal while shrieking",
                    "A candidate position within the world border has a full upper collision face beneath, no liquid, and unobstructed Warden geometry"])
    add("mob_summoning", [mob("evoker")], [mob("vex")], "An Evoker's summoning spell creates three Vexes with limited lives. The spell's cooldown and nearby Vex count affect whether it casts.", "evoker_vex", category="spawning", source_class="net.minecraft.world.entity.monster.illager.Evoker$EvokerSummonSpellGoal", count=3)
    for slug in ["slime", "magma_cube"]:
        add("mob_splitting", [mob(slug)], [mob(slug)], "On death, a mob larger than size 1 splits into 2–4 children of half its size; the parent is removed. Size-1 mobs do not split.", "mob_splitting:" + slug, category="spawning", source_class="net.minecraft.world.entity.monster.cubemob.AbstractCubeMob", conditions=["Dying parent size greater than 1"], count={"min": 2, "max": 4})
    add("mob_splitting", [mob("sulfur_cube")], [mob("sulfur_cube")], "A dying, unprimed adult Sulfur Cube (size 2) splits into exactly two baby Sulfur Cubes (size 1). A primed or size-1 cube does not split.", "mob_splitting:sulfur_cube", category="spawning", source_class="net.minecraft.world.entity.monster.cubemob.SulfurCube", conditions=["Dying unprimed parent size greater than 1"], count=2)
    for egg, entity, note in [("turtle_egg", "turtle", "Eggs progress through cracks and hatch into baby turtles on sand. Incubation ticks and time of day affect hatching; egg count controls the hatch count."),
                             ("sniffer_egg", "sniffer", "A Sniffer Egg progresses through cracks and hatches into a baby Sniffer. Moss accelerates incubation; the egg is consumed."),
                             ("frogspawn", "tadpole", "Frogspawn in valid water hatches into 2–5 Tadpoles after its delay; the frogspawn block is removed.")]:
        add("block_hatching", ["minecraft:" + egg], [mob(entity)], note, "block_hatching:" + egg, category="spawning", source_class="net.minecraft.world.level.block." + {"turtle_egg": "TurtleEggBlock", "sniffer_egg": "SnifferEggBlock", "frogspawn": "FrogspawnBlock"}[egg])
    add("hydration_spawning", ["minecraft:dried_ghast", block("water")], [mob("happy_ghast")], "A continuously waterlogged Dried Ghast advances hydration levels from 0 to 3, then spawns one baby Happy Ghast on its next hydration tick and removes the block. Hydration ticks are scheduled 5000 ticks apart; drying reverses hydration progress. Chunk ticking must continue.", "dried_ghast_hydrating", category="spawning", source_class="net.minecraft.world.level.block.DriedGhastBlock", requiredBlockState={"block": "minecraft:dried_ghast", "waterlogged": True}, hydrationTickDelay=5000, count=1)
    for copper_id, chest_id in sorted(metadata["copperConstructionChests"].items()):
        add("construction_side_product", [block(copper_id)] + pumpkins, [block(chest_id)], "Building a Copper Golem replaces its copper construction block with a matching Copper Chest, preserving its wax/oxidation stage when standalone. Connection to an adjacent compatible Copper Chest can align both to the least oxidized connected state; this mapping describes the standalone case.", "copper_construction_chest:" + copper_id, source="vanilla_game_mapping_and_audited_interaction", source_class="net.minecraft.world.level.block.CopperChestBlock", conditions=["Valid Copper Golem construction", "Standalone chest or no lower oxidation connected chest"])
    for host, infested in sorted(metadata["infestation"].items()):
        add("infested_release", [block(infested)], [mob("silverfish")], "Breaking the infested block without Silk Touch can release a Silverfish when block drops are enabled. Nearby Silverfish can also wake its inhabitant while mob griefing is enabled.", "infested_release:" + infested, category="spawning", source_class="net.minecraft.world.level.block.InfestedBlock", conditions=["Block drops enabled and no Silk Touch, or awakened by nearby Silverfish with mob griefing"])
        add("infestation", [block(host), mob("silverfish")], [block(infested)], "An idle Silverfish with mob griefing enabled can hide in an adjacent compatible host block, replacing it with its infested state and removing the Silverfish.", "infestation:" + host, source="vanilla_block_mapping_and_audited_interaction", source_class="net.minecraft.world.entity.monster.Silverfish$SilverfishMergeWithStoneGoal")

    # These food tags are read by the named mob's isFood/interaction/brain code.
    food_mobs = {"armadillo": ["armadillo"], "axolotl": ["axolotl"], "bee": ["bee"], "camel": ["camel"], "camel_husk": ["camel_husk"], "cat": ["cat"],
                 "chicken": ["chicken"], "cow": ["cow", "mooshroom"], "fox": ["fox"], "frog": ["frog", "tadpole"], "goat": ["goat"], "happy_ghast": ["happy_ghast"],
                 "hoglin": ["hoglin"], "horse": ["horse", "donkey", "mule"], "llama": ["llama", "trader_llama"], "nautilus": ["nautilus", "zombie_nautilus"],
                 "ocelot": ["ocelot"], "panda": ["panda"], "parrot": ["parrot"], "pig": ["pig"], "piglin": ["piglin"], "rabbit": ["rabbit"], "sheep": ["sheep"],
                 "sniffer": ["sniffer"], "strider": ["strider"], "sulfur_cube": ["sulfur_cube"], "turtle": ["turtle"], "wolf": ["wolf"], "zombie_horse": ["zombie_horse"]}
    mob_report = json.loads((ROOT / ".cache/mob-models.json").read_text(encoding="utf-8"))["entities"]
    for food, entities in sorted(food_mobs.items()):
        for entity in entities:
            note = "Any one item in this food tag can be fed to this mob. Age, breeding cooldown, health and ownership requirements depend on the interaction; feeding does not guarantee a baby or healing."
            if entity in ["happy_ghast", "sulfur_cube", "tadpole"]:
                note = "Feed a baby with any one item in this tag to accelerate its growth; this mob does not breed from this food."
            elif entity == "piglin":
                note = "A Piglin can pick up and eat a dropped item from this food tag while its eating cooldown permits; this is separate from gold bartering."
            elif entity in ["nautilus", "zombie_nautilus"]:
                note = "A tame Nautilus or baby accepts this food tag. An untamed adult accepts only the Nautilus Taming Items subset. Fish buckets return their bucket after feeding."
            elif entity == "parrot":
                note = "Offer a Parrot one item from this seed tag to attempt taming; parrots do not breed."
            elif entity == "camel_husk":
                note = "A Camel Husk accepts Rabbit's Foot to heal 2 health when injured. It cannot breed or be a baby."
            elif entity == "zombie_horse":
                note = "A Zombie Horse accepts Red Mushrooms to heal 3 health or increase temper. It cannot enter love mode or breed."
            tag_use("feeding", food + "_food", mob(entity), note, source_class=mob_report[namespaced(entity)]["class"])
    tag_use("feeding", "fishes", mob("dolphin"), "A baby Dolphin accepts a fish to speed growth; an adult is set to seek treasure. Dolphins do not breed. The fish tag includes cooked fish in this game version.", source_class=mob_report["minecraft:dolphin"]["class"])
    for item, components in sorted(game.components.items()):
        if "minecraft:villager_food" in components:
            add("feeding", [item], [mob("villager")], "Villagers can pick up and consume this food to accumulate food points for breeding. Willingness also requires a partner, available beds, age and cooldown checks; mob griefing controls item pickup.",
                "villager_food:" + item, source="vanilla_item_component_and_audited_interaction", raw=components["minecraft:villager_food"], source_class="net.minecraft.world.entity.npc.villager.Villager")
    breedable = {"armadillo", "axolotl", "bee", "camel", "cat", "chicken", "cow", "mooshroom", "fox", "frog", "goat", "hoglin", "nautilus", "ocelot", "panda", "pig", "rabbit", "sheep", "sniffer", "strider", "turtle", "wolf"}
    for food, entities in sorted(food_mobs.items()):
        for entity in entities:
            if entity in breedable:
                note = "Feed one item from this tag to each of two eligible adults to enter love mode. A compatible partner, breeding cooldown and species-specific state must permit breeding. Cats, Wolves and Nautiluses must be tamed. Panda breeding requires nearby bamboo; Turtles lay Turtle Eggs, Frogs lay Frogspawn and Sniffers drop Sniffer Eggs."
                tag_use("breeding", food + "_food", mob(entity), note, source_class=mob_report[namespaced(entity)]["class"])
    for entity in ["horse", "donkey"]:
        add("breeding", ["minecraft:golden_carrot", "minecraft:golden_apple", "minecraft:enchanted_golden_apple"], [mob(entity)], "Any one of these golden foods puts an eligible tamed adult Horse/Donkey into love mode. Two Horses produce a Horse, two Donkeys a Donkey, and a Horse with a Donkey produces a Mule. A Mule cannot breed.", "equine_breeding:" + entity, source_class="net.minecraft.world.entity.animal.equine.AbstractHorse", alternatives=True)
    for entity in ["llama", "trader_llama"]:
        add("breeding", ["minecraft:hay_block"], [mob(entity)], "Hay Bale puts an eligible tamed adult Llama into love mode; it requires a compatible partner and breeding cooldown. Wheat feeds a Llama but does not trigger breeding.", "llama_breeding:" + entity, source_class="net.minecraft.world.entity.animal.equine.Llama")
    for animal, egg in [("turtle", "turtle_egg"), ("frog", "frogspawn"), ("sniffer", "sniffer_egg")]:
        add("egg_laying", [mob(animal)], ["minecraft:" + egg], "After successful breeding, this mob produces its egg stage. Turtles lay 1–4 eggs on home-beach sand; Frogs lay Frogspawn in valid water; Sniffers drop a Sniffer Egg.", "egg_laying:" + animal, category="spawning", source_class=mob_report[namespaced(animal)]["class"])
    add("hybrid_breeding", [mob("horse"), mob("donkey")], [mob("mule")], "Breed a tamed adult Horse with a tamed adult Donkey using golden foods; their baby is a Mule. Mules cannot breed.", "horse_donkey_mule", category="spawning", source_class="net.minecraft.world.entity.animal.equine.Horse")
    for animal, tag, note, kind in [("wolf", None, "Give a Bone to an untamed, non-angry Wolf. Each attempt has a 1/3 success chance.", "taming"),
                                  ("cat", "cat_food", "Feed an untamed Cat a fish from this tag while it trusts the approaching player; a taming attempt may fail.", "taming"),
                                  ("ocelot", "ocelot_food", "Feed an Ocelot a fish from this tag while it trusts the approaching player to attempt gaining trust. Ocelots become trusting, rather than becoming owned Cats.", "trust"),
                                  ("parrot", "parrot_food", "Offer one seed from this tag to an untamed Parrot; each taming attempt has a 1/10 chance.", "taming"),
                                  ("nautilus", "nautilus_taming_items", "Offer Pufferfish or a Pufferfish Bucket to an untamed adult Nautilus to attempt taming. Other food-tag fish cannot tame an untamed adult.", "taming"),
                                  ("zombie_nautilus", "nautilus_taming_items", "Offer Pufferfish or a Pufferfish Bucket to an untamed adult Zombie Nautilus to attempt taming.", "taming")]:
        if tag:
            tag_use(kind, tag, mob(animal), note, source_class=mob_report[namespaced(animal)]["class"])
        else:
            add(kind, ["minecraft:bone"], [mob(animal)], note, "taming:wolf", source_class=mob_report["minecraft:wolf"]["class"], chance=1/3)
    for animal in ["horse", "donkey", "mule", "zombie_horse", "llama", "trader_llama"]:
        foods = game.resolve_tag("minecraft:" + ("zombie_horse_food" if animal == "zombie_horse" else "llama_food" if "llama" in animal else "horse_food"))
        foods = [food for food in foods if food != "minecraft:hay_block" or "llama" in animal]
        add("taming_support", foods, [mob(animal)], "These foods increase temper while conditions allow, improving later riding-based taming attempts; feeding itself does not tame the animal.", "taming_support:" + animal, source_class="net.minecraft.world.entity.animal.equine." + ("Llama" if "llama" in animal else "AbstractHorse"), alternatives=True)
    horse_healing = {"wheat": 2, "sugar": 1, "hay_block": 20, "apple": 3, "carrot": 3, "golden_carrot": 4, "golden_apple": 10, "enchanted_golden_apple": 10}
    for animal in ["horse", "donkey", "mule", "zombie_horse", "llama", "trader_llama", "camel", "camel_husk", "cat", "wolf", "nautilus", "zombie_nautilus"]:
        if animal in ["horse", "donkey", "mule"]:
            healing = horse_healing
        elif animal == "zombie_horse":
            healing = {"red_mushroom": 3}
        elif "llama" in animal:
            healing = {"wheat": 2, "hay_block": 10}
        elif animal in ["camel", "camel_husk"]:
            healing = {item.split(":", 1)[1]: 2 for item in game.resolve_tag("minecraft:" + animal + "_food")}
        else:
            tag = "nautilus" if "nautilus" in animal else animal
            scale, fallback = (2, 2) if animal == "wolf" else (2, 1) if "nautilus" in animal else (1, 1)
            healing = {item.split(":", 1)[1]: scale * game.components[item]["minecraft:food"]["nutrition"] if "minecraft:food" in game.components[item] else fallback for item in game.resolve_tag("minecraft:" + tag + "_food")}
        for food, amount in healing.items():
            item = "minecraft:" + food
            add("healing", [item], [mob(animal)], f"Feed an injured animal to restore {amount} health from the default stack, capped at its maximum. Cats and Wolves must be tamed; an untamed adult Nautilus uses its taming-food branch instead. Cats scale nutrition by 1, Wolves/Nautiluses by 2; custom food components can change those amounts.",
                f"healing:{animal}:{food}", source_class=mob_report[namespaced(animal)]["class"], healing=amount)
    add("healing", ["minecraft:iron_ingot"], [mob("iron_golem")], "Interact with an injured Iron Golem using an Iron Ingot; consumes one ingot and restores 25 health, capped at maximum.", "iron_golem_healing", source_class="net.minecraft.world.entity.animal.golem.IronGolem", healing=25)
    tag_use("mob_swallowing", "sulfur_cube_swallowable", mob("sulfur_cube"), "Offer one allowed item to an adult, unprimed Sulfur Cube. It stores the item in its body slot and changes archetype; shearing retrieves its stored item. It does not swallow every item.", source_class="net.minecraft.world.entity.monster.cubemob.SulfurCube")

    # Default item capabilities describe player uses without inventing Player/action nodes.
    component_keys = {"minecraft:food": "food", "minecraft:equippable": "equippable", "minecraft:tool": "tool", "minecraft:weapon": "weapon", "minecraft:cooking_fuel": "cookingFuel", "minecraft:brewing_fuel": "brewingFuel", "minecraft:jukebox_playable": "playable"}
    for item, components in sorted(game.components.items()):
        entry = {label: components[key] for key, label in component_keys.items() if key in components}
        if item in metadata["placedBlocks"]:
            entry["placeable"] = {"blockId": metadata["placedBlocks"][item], "conditions": "Valid placement context, supporting blocks and survival checks"}
        if item in metadata["placedFluids"]:
            entry["placeable"] = {"blockId": metadata["placedFluids"][item], "conditions": "Valid bucket emptying context; water evaporates in ultrawarm dimensions"}
        if entry:
            capabilities[item] = entry
        equip = components.get("minecraft:equippable", {})
        if "allowed_entities" in equip:
            for entity in targets("entity_type", equip["allowed_entities"]):
                if mob(entity) in node_ids:
                    add("equipping", [item], [mob(entity)], "Equip this item in the mob's " + equip["slot"] + " slot. Mob-specific age, taming, ownership and current equipment rules still apply; allowed entities do not guarantee automatic pickup.", "equipping:" + item + ":" + entity, source="vanilla_item_component", raw=equip)
                    if equip.get("can_be_sheared"):
                        add("equipment_shearing", ["minecraft:shears"], [mob(entity)], "Use Shears to remove shearable equipped items. The mob's equipment, ownership and age requirements apply; the equipped item is returned.", "equipment_shearing:" + item + ":" + entity, source="vanilla_item_component", equippedItem=item, raw=equip)
                        add("equipment_retrieval", ["minecraft:shears", mob(entity)], [item], "Shear this specific equipped item off the mob. This possible retrieval requires that exact item in the specified slot and the mob's ownership/age rules; empty or differently equipped mobs do not yield it.", "equipment_retrieval:" + item + ":" + entity, source="vanilla_item_component", requiredEquipment={equip["slot"]: item}, raw=equip)
        fuel = components.get("minecraft:cooking_fuel")
        if fuel:
            add("cooking_fuel", [item], ["minecraft:" + station for station in ["furnace", "blast_furnace", "smoker"]], "This default Cooking Fuel component supplies burn time to each station. Burn time and speed use context providers, so fast-cooking stations can consume fuel faster. A fuel edge is not a smelting recipe.", "cooking_fuel:" + item, source="vanilla_item_component", raw=fuel)
        if "minecraft:brewing_fuel" in components:
            add("brewing_fuel", [item], ["minecraft:brewing_stand"], "This item supplies fuel uses to a Brewing Stand through its default Brewing Fuel component; it is distinct from brewing ingredients.", "brewing_fuel:" + item, source="vanilla_item_component", raw=components["minecraft:brewing_fuel"])
        if "minecraft:jukebox_playable" in components:
            add("jukebox_playback", [item], ["minecraft:jukebox"], "Insert the playable item in a Jukebox to play its song. Comparator output and playback duration depend on the song record; the item can be removed.", "jukebox:" + item, source="vanilla_item_component", raw=components["minecraft:jukebox_playable"])

    # Decode every rule from all transformer files used by default item components.
    transformer_items = {}
    for item, components in game.components.items():
        if "minecraft:block_transformer" in components:
            transformer_items.setdefault(components["minecraft:block_transformer"], []).append(item)

    def predicate_blocks(predicate):
        if "offset" in predicate and predicate["offset"] != [0, 0, 0]:
            return None
        kind = predicate["type"]
        if kind == "minecraft:matching_blocks":
            return set(targets("block", predicate["blocks"]))
        if kind == "minecraft:matching_block_tag":
            return set(resolve("block", predicate["tag"]))
        if kind in ["minecraft:all_of", "minecraft:any_of"]:
            parts = [value for child in predicate["predicates"] if (value := predicate_blocks(child)) is not None]
            if not parts:
                return None
            return set.intersection(*parts) if kind == "minecraft:all_of" else set.union(*parts)
        raise ValueError(f"Unknown transformation predicate {predicate}")

    transform_rules = 0
    for transformer_id, tools in sorted(transformer_items.items()):
        namespace, slug = transformer_id.split(":", 1)
        for section_index, section in enumerate(read_json(f"data/{namespace}/block_transformer/{slug}.json")):
            provider = section["block_state_provider"]
            if provider["type"] != "minecraft:rule_based":
                raise ValueError(f"Unknown transformer provider {transformer_id}")
            for rule_index, rule in enumerate(provider["rules"]):
                transform_rules += 1
                output_state = rule["then"]
                if output_state.get("type") == "minecraft:copy_properties":
                    output_state = output_state["source"]
                output = block(output_state["id"])
                hosts = predicate_blocks(rule["if_true"])
                if not hosts:
                    raise ValueError(f"Transformer has no source blocks {transformer_id}")
                for host in sorted(hosts):
                    original = block(host)
                    if not output or not original:
                        continue
                    identifier = f"{transformer_id}:{section_index}:{rule_index}:{host}"
                    add("block_transform", [original] + sorted(tools), [output], "Use any one tool with this Block Transformer component on the source block. The exact block-state/neighbor/face predicates, durability cost and output-state provider are preserved. Multiple inputs show participation, not that a tool alone produces the result.", "block_transform:" + identifier, source="vanilla_block_transformer", raw={"rule": rule, "transformer": {k: v for k, v in section.items() if k != "block_state_provider"}}, transformerId=transformer_id)
                    add("block_transform_tool", sorted(tools), [original], "Use any one matching tool on this block to apply the associated transformation; state, neighbor and clicked-face restrictions must match the preserved rule.", "block_transform_tool:" + identifier, source="vanilla_block_transformer", raw=rule, resultNode=output)
    for original_id, waxed_id in sorted(metadata["waxables"].items()):
        original, waxed = block(original_id), block(waxed_id)
        if original and waxed:
            add("waxing", [original, "minecraft:honeycomb"], [waxed], "Use Honeycomb on an unwaxed copper block to prevent oxidation; consumes one Honeycomb and preserves block properties.", "waxing:" + original_id, source="vanilla_game_mapping", source_class="net.minecraft.world.item.HoneycombItem")
            add("waxing_tool", ["minecraft:honeycomb"], [original], "Apply Honeycomb to wax this copper block; the matching waxed state is produced and one Honeycomb is consumed.", "waxing_tool:" + original_id, source="vanilla_game_mapping", resultNode=waxed)
    for original_id, changed_id in sorted(metadata["oxidation"].items()):
        original, changed = block(original_id), block(changed_id)
        if original and changed:
            add("oxidizing", [original], [changed], "An unwaxed placed copper block can weather into its next oxidation stage on random ticks. Nearby copper ages, random-tick speed and its weathering chance affect progress.", "oxidizing:" + original_id, source="vanilla_game_mapping", source_class="net.minecraft.world.level.block.WeatheringCopper")

    mining_targets = 0
    for item, components in sorted(game.components.items()):
        tool = components.get("minecraft:tool")
        if not tool:
            continue
        candidates = sorted({b for rule in tool.get("rules", []) if rule.get("correct_for_drops") or rule.get("speed", 0) > 1 for b in targets("block", rule["blocks"])})
        groups = {}
        for block_id in candidates:
            target = block(block_id)
            if not target:
                continue
            matching = [rule for rule in tool["rules"] if block_id in targets("block", rule["blocks"])]
            correct = next((rule["correct_for_drops"] for rule in matching if "correct_for_drops" in rule), tool.get("default_correct_for_drops", False))
            speed = next((rule["speed"] for rule in matching if "speed" in rule), tool.get("default_mining_speed", 1))
            if not correct and speed <= 1:
                continue
            groups.setdefault((correct, speed), {})[block_id] = target
            mining_targets += 1
        for index, ((correct, speed), group) in enumerate(sorted(groups.items())):
            add("mining_tool", [item], list(group.values()), "This tool has a matching mining-speed or correct-for-drops rule for these blocks. Rules are evaluated in order per property; the preserved result says whether it is correct for drops. Actual loot still depends on block state, enchantments and loot predicates.", "mining_tool:" + item + ":" + str(index), source="vanilla_item_tool_component_and_block_tags", blockIds=sorted(group), miningSpeed=speed, correctForDrops=correct, raw=tool)

    # Interaction tools are separate from gathering-output participation edges.
    for animal in ["sheep", "mooshroom", "bogged", "snow_golem"]:
        add("shearing_tool", ["minecraft:shears"], [mob(animal)], "Shear this mob when its age and unsheared state permit. Sheep yield their colored wool; Mooshrooms become Cows, Bogged lose mushrooms and Snow Golems lose their pumpkin.", "shearing_tool:" + animal, source_class=mob_report[namespaced(animal)]["class"])
    for hive in ["beehive", "bee_nest"]:
        for tool in ["shears", "glass_bottle"]:
            add("harvesting_tool", ["minecraft:" + tool], ["minecraft:" + hive], "Use the tool on a hive at honey level 5; Shears harvest Honeycomb and Glass Bottles collect Honey Bottles. Honey level resets; smoke prevents bee anger.", f"hive_tool:{hive}:{tool}", source_class="net.minecraft.world.level.block.BeehiveBlock")
        for campfire in ["campfire", "soul_campfire"]:
            add("smoking_bees", ["minecraft:" + campfire], ["minecraft:" + hive], "Smoke from a lit campfire beneath the hive pacifies its bees for harvesting. CampfireBlock.isSmokeyPos checks up to five blocks below with its obstruction rules; an arbitrary nearby campfire is insufficient.", f"smoking_bees:{hive}:{campfire}", source_class="net.minecraft.world.level.block.CampfireBlock")
    for campfire in ["campfire", "soul_campfire"]:
        tag_use("extinguishing", "douses_campfires", "minecraft:" + campfire, "Use a tool from this tag on a lit campfire to extinguish it; the tool loses durability and the campfire remains unlit.", source_class="net.minecraft.world.level.block.CampfireBlock")
        add("campfire_smoke", ["minecraft:hay_block"], ["minecraft:" + campfire], "A Hay Bale directly below a campfire marks it as a signal fire, raising its smoke column. It does not extend the hive smoke detection range beyond five blocks.", "campfire_smoke:" + campfire, source_class="net.minecraft.world.level.block.CampfireBlock")
        for igniter in ["flint_and_steel", "fire_charge"]:
            add("igniting", ["minecraft:" + igniter], ["minecraft:" + campfire], "Ignite an unlit, non-waterlogged campfire; Flint and Steel loses durability, while a Fire Charge is consumed.", f"campfire_igniting:{campfire}:{igniter}", source_class="net.minecraft.world.item." + ("FlintAndSteelItem" if igniter == "flint_and_steel" else "FireChargeItem"))
        add("extinguishing", ["minecraft:water_bucket"], ["minecraft:" + campfire], "Waterlog the campfire with water to extinguish it; the bucket becomes empty and the campfire remains.", "campfire_water:" + campfire, source_class="net.minecraft.world.level.block.CampfireBlock")
    dye_items = [item for item, components in game.components.items() if "minecraft:dye" in components]
    for item in sorted(dye_items):
        add("dyeing", [item], [mob("sheep")], "Use a dye on a living, unsheared Sheep to set its wool color; consumes one dye when the color changes. Sheared Sheep cannot be dyed until their wool regrows.", "dyeing_sheep:" + item, source_class="net.minecraft.world.item.DyeItem", color=game.components[item]["minecraft:dye"])
    for animal, tag in [("wolf", "wolf_collar_dyes"), ("cat", "cat_collar_dyes")]:
        tag_use("dyeing", tag, mob(animal), "The owner can use a collar dye on their tamed animal; one dye is consumed when its collar color changes.", source_class=mob_report[namespaced(animal)]["class"])
    tag_use("igniting", "creeper_igniters", mob("creeper"), "Use Flint and Steel or Fire Charge on a Creeper to ignite its fuse. The durable tool takes damage or the Fire Charge is consumed; this does not charge the Creeper.", source_class=mob_report["minecraft:creeper"]["class"])
    for item in ["flint_and_steel", "fire_charge"]:
        add("igniting", ["minecraft:" + item], [mob("sulfur_cube")], "Use this igniter on an adult unprimed Sulfur Cube with an explosive archetype and explosions enabled to prime it. Other archetypes cannot be ignited this way.", "sulfur_igniting:" + item, source_class=mob_report["minecraft:sulfur_cube"]["class"])
    tag_use("mob_duplication", "duplicates_allays", mob("allay"), "Give an Amethyst Shard to a dancing Allay whose duplication cooldown has expired. It produces another Allay, consumes the shard, and both enter the 6000-tick cooldown.", source_class=mob_report["minecraft:allay"]["class"])
    add("dancing", ["minecraft:jukebox"], [mob("allay"), mob("parrot")], "A playing Jukebox lets nearby Allays and Parrots dance within their respective distance/state checks. An empty or stopped Jukebox does not trigger dancing.", "jukebox_dancing", source_class="net.minecraft.world.entity.animal.allay.Allay / net.minecraft.world.entity.animal.parrot.Parrot")
    add("equipment_repair", ["minecraft:armadillo_scute"], [mob("wolf")], "The owner can repair a sitting Wolf's damaged equipped Wolf Armor using an Armadillo Scute. Each scute restores 12.5% of the armor's maximum durability, clamped to zero damage.", "wolf_equipment_repair", source_class=mob_report["minecraft:wolf"]["class"], repairFraction=.125)
    add("mob_gifting", [mob("iron_golem"), "minecraft:poppy"], [mob("copper_golem")], "An Iron Golem's flower-offering AI can give a Poppy to a Copper Golem in bright-outside conditions. After the 400-tick offering completes, the recipient must intersect the Iron Golem's box inflated 6 blocks horizontally and 2 vertically and have its head slot empty. The Copper Golem wears the accepted Poppy on its head; this is an AI gift, not a direct player-equipping action.", "iron_copper_poppy_gift", source="vanilla_entity_type_tags_and_audited_interaction", source_class="net.minecraft.world.entity.ai.goal.OfferFlowerGoal", conditions=["Bright outside", "Flower-offering AI finishes its 400-tick offer", "Recipient accepts iron-golem gifts", "Recipient head slot is empty", "Recipient intersects the offering area"], requiredEquipment={"slot": "head", "empty": True})
    add("equipment_retrieval", ["minecraft:shears", mob("copper_golem")], ["minecraft:poppy"], "Shear an alive Copper Golem wearing a Poppy in its head slot to retrieve that Poppy. The Shearable From Copper Golem tag currently contains only Poppy; an empty-headed golem yields none.", "copper_golem_poppy_retrieval", source="vanilla_item_tag_and_audited_interaction", source_class=mob_report["minecraft:copper_golem"]["class"], requiredEquipment={"head": "minecraft:poppy"}, rawTag=game.tags["minecraft:shearable_from_copper_golem"])
    add("equipment_shearing", ["minecraft:shears"], [mob("copper_golem")], "Shears remove the Poppy from an alive Copper Golem when its head item is in the Shearable From Copper Golem tag; the item is returned and Shears lose durability.", "copper_golem_equipment_shearing", source_class=mob_report["minecraft:copper_golem"]["class"], requiredEquipmentTag="minecraft:shearable_from_copper_golem")
    for block_id in resolve("block", "minecraft:enderman_holdable"):
        target = block(block_id)
        if target:
            add("block_pickup", [mob("enderman")], [target], "With mob griefing enabled, an Enderman can pick up and later place this block from the Enderman Holdable block tag when its AI's position, visibility and support checks permit.", "enderman_holdable:" + block_id, source="vanilla_block_tag_and_audited_interaction", source_class="net.minecraft.world.entity.monster.Enderman$EndermanTakeBlockGoal", blockId=block_id)
    for entity in resolve("entity_type", "minecraft:frog_food"):
        add("predation", [mob(entity)], [mob("frog")], "Frogs can eat a small (size 1) Slime or Magma Cube when their attack target and tongue path permit. Eating a Slime drops a Slime Ball; eating a Magma Cube drops a Froglight selected by Frog variant.", "frog_food:" + entity, source="vanilla_entity_type_tag_and_audited_interaction", source_class="net.minecraft.world.entity.animal.frog.Frog")
    add("mob_summoning", ["minecraft:end_crystal"], [mob("ender_dragon")], "Place four End Crystals around the End exit portal after the dragon has been defeated to initiate the respawn sequence. End Crystals alone anywhere else do not summon a dragon.", "dragon_resummoning", category="spawning", source_class="net.minecraft.world.level.dimension.end.EnderDragonFight", count=4)
    add("healing", ["minecraft:end_crystal"], [mob("ender_dragon")], "An Ender Dragon can link to an existing nearby End Crystal and heal one health every ten ticks while it remains linked. Destroying the linked crystal hurts the dragon.", "dragon_crystal_healing", source_class="net.minecraft.world.entity.boss.enderdragon.EnderDragon", healing=1, intervalTicks=10)
    for item in game.resolve_tag("minecraft:arrows"):
        for weapon in ["bow", "crossbow"]:
            add("ranged_ammunition", [item], ["minecraft:" + weapon], "Load/fire an Arrow item with this ranged weapon. Arrow stack components select potion effects and projectile variants; enchantments can affect ammo consumption.", f"ammunition:{weapon}:{item}", source="vanilla_item_tag_and_audited_interaction", source_class="net.minecraft.world.item." + weapon.title() + "Item")
    add("ranged_ammunition", ["minecraft:firework_rocket"], ["minecraft:crossbow"], "Load a Firework Rocket into a Crossbow; flight and explosion behavior use the rocket's components. Crossbow rockets use the offhand selection path.", "crossbow_fireworks", source_class="net.minecraft.world.item.CrossbowItem")
    add("gliding_boost", ["minecraft:firework_rocket"], ["minecraft:elytra"], "Use a Firework Rocket while gliding with Elytra to accelerate. A rocket containing explosion stars can damage its rider when it detonates.", "elytra_rocket_boost", source_class="net.minecraft.world.item.FireworkRocketItem")
    for item, entity in [("carrot_on_a_stick", "pig"), ("warped_fungus_on_a_stick", "strider")]:
        add("riding_control", ["minecraft:" + item], [mob(entity)], "Holding this item controls a saddled ridden mob; using it starts a speed boost and costs durability. The saddle and mount state are required.", "riding_control:" + entity, source_class="net.minecraft.world.item.FoodOnAStickItem")
    for entity in ["donkey", "mule", "llama", "trader_llama"]:
        add("storage_equipment", ["minecraft:chest"], [mob(entity)], "Use a Chest on a tamed eligible adult to add its inventory storage. The mob must not already carry a chest; the chest is consumed.", "chested_mount:" + entity, source_class="net.minecraft.world.entity.animal.equine.AbstractChestedHorse")

    for item, block_id in sorted({**metadata["placedBlocks"], **metadata["placedFluids"]}.items()):
        target = block(block_id)
        if target and target != item:
            add("placing", [item], [target], "Use this block item or filled bucket to place its actual registered world block. Placement requires a valid location, support/survival and fluid/dimension checks; this is a world state, not a second inventory item.", "placing:" + item, source="vanilla_item_class_mapping", blockId=block_id)
    for plant_id, potted_id in sorted(metadata["flowerPots"].items()):
        plant, potted = block(plant_id), block(potted_id)
        if plant and potted:
            add("potting", [plant, "minecraft:flower_pot"], [potted], "Use the plant on an empty placed Flower Pot to consume one plant and produce the corresponding potted block. The plant can be removed by interacting with the filled pot.", "potting:" + plant_id, source="vanilla_block_mapping", source_class="net.minecraft.world.level.block.FlowerPotBlock")
            add("unpotting", [potted], [plant, "minecraft:flower_pot"], "Interact to remove the potted plant; the empty Flower Pot remains placed and the plant is returned. Breaking the potted block is represented separately by its loot table.", "unpotting:" + plant_id, source="vanilla_block_mapping", source_class="net.minecraft.world.level.block.FlowerPotBlock")
    signs = game.resolve_tag("minecraft:signs") + game.resolve_tag("minecraft:hanging_signs")
    for item in sorted(dye_items):
        add("sign_dyeing", [item], signs, "Use this dye to change text color on the targeted side of an unwaxed placed sign or hanging sign. The side must be editable and its color must change; one dye is consumed.", "sign_dyeing:" + item, source_class="net.minecraft.world.item.DyeItem", color=game.components[item]["minecraft:dye"])
    for tool, kind, note in [("glow_ink_sac", "sign_glowing", "Apply Glow Ink Sac to text on one side of an unwaxed sign to make its text glow; one sac is consumed when the state changes."),
                             ("ink_sac", "sign_unglowing", "Apply Ink Sac to glowing text on one side of an unwaxed sign to remove the glow; one sac is consumed when the state changes."),
                             ("honeycomb", "sign_waxing", "Apply Honeycomb to an unwaxed placed sign to lock editing of its text; one Honeycomb is consumed.")]:
        add(kind, ["minecraft:" + tool], signs, note, "sign_use:" + tool, source_class="net.minecraft.world.item." + {"glow_ink_sac": "GlowInkSacItem", "ink_sac": "InkSacItem", "honeycomb": "HoneycombItem"}[tool])
    for item in game.resolve_tag("minecraft:cauldron_can_remove_dye"):
        add("washing", [item, "minecraft:cauldron"], [item], "Use a dyed item on a water-filled Cauldron (level at least 1) to remove its dyed color component, consuming one water level. The item registry ID remains the same; this self-loop changes its components.", "washing_dye:" + item, source="vanilla_item_tag_and_audited_interaction", source_class="net.minecraft.core.cauldron.CauldronInteraction", requiredBlockState={"block": "minecraft:water_cauldron", "level": {"min": 1}}, removedComponent="minecraft:dyed_color")
    for item in game.resolve_tag("minecraft:banners"):
        add("washing", [item, "minecraft:cauldron"], [item], "Use a banner with at least one pattern on a water-filled Cauldron to remove its last pattern, consuming one water level. The base-color banner item remains; this self-loop changes its pattern component.", "washing_banner:" + item, source="vanilla_item_tag_and_audited_interaction", source_class="net.minecraft.core.cauldron.CauldronInteraction", requiredBlockState={"block": "minecraft:water_cauldron", "level": {"min": 1}}, requiredComponents={"minecraft:banner_patterns": "at least one layer"})
    for color in [game.components[item]["minecraft:dye"] for item in dye_items]:
        add("washing", ["minecraft:" + color + "_shulker_box", "minecraft:cauldron"], ["minecraft:shulker_box"], "Use a colored Shulker Box on a water-filled Cauldron to remove its color while preserving contents; consumes one water level.", "washing_shulker:" + color, source_class="net.minecraft.core.cauldron.CauldronInteraction", requiredBlockState={"block": "minecraft:water_cauldron", "level": {"min": 1}})
    for bucket, contents in [("water_bucket", "water"), ("lava_bucket", "lava"), ("powder_snow_bucket", "powder_snow")]:
        add("cauldron_filling", ["minecraft:" + bucket], ["minecraft:cauldron"], "Empty the filled bucket into an eligible Cauldron to fill it with " + contents.replace("_", " ") + ". Existing incompatible contents and full-state rules apply; the empty bucket is returned.", "cauldron_filling:" + bucket, source_class="net.minecraft.core.cauldron.CauldronInteraction", resultBlockState="minecraft:" + contents + "_cauldron")
        add("cauldron_emptying", ["minecraft:bucket", "minecraft:cauldron"], ["minecraft:" + bucket], "Use an empty bucket on a Cauldron filled with " + contents.replace("_", " ") + ". Water and Powder Snow require level 3; Lava Cauldrons have a single full state. The Cauldron becomes empty.", "cauldron_emptying:" + bucket, source_class="net.minecraft.core.cauldron.CauldronInteraction", requiredBlockState={"block": "minecraft:" + contents + "_cauldron", "level": 3 if contents != "lava" else None})
    water_components = {"minecraft:potion_contents": {"potion": "minecraft:water"}}
    add("cauldron_filling", ["minecraft:potion"], ["minecraft:cauldron"], "Pour a Water Bottle into an empty or partly water-filled Cauldron to add one water level; the glass bottle is returned. Only the drinkable Water potion works.", "cauldron_water_bottle_filling", source_class="net.minecraft.core.cauldron.CauldronInteraction", requiredComponents=water_components)
    add("cauldron_bottling", ["minecraft:glass_bottle", "minecraft:cauldron"], ["minecraft:potion"], "Use a Glass Bottle on a water-filled Cauldron with at least one water level to obtain one Water Bottle; one water level is consumed.", "cauldron_water_bottle_emptying", source_class="net.minecraft.core.cauldron.CauldronInteraction", requiredBlockState={"block": "minecraft:water_cauldron", "level": {"min": 1}}, results=[{"item": "minecraft:potion", "count": 1, "components": water_components}])
    for item in ["minecraft:splash_potion", "minecraft:lingering_potion"]:
        add("water_rehydrating", [item], [mob("axolotl")], "A thrown Water Potion rehydrates nearby Axolotls when it impacts, using the projectile's inflated bounding box. This only applies to Water Potion contents; it is not a status effect.", "water_rehydrating:" + item, source_class="net.minecraft.world.entity.projectile.throwableitemprojectile.AbstractThrownPotion", requiredComponents=water_components)
        add("water_harming", [item], [mob(entity) for entity in ["blaze", "enderman", "snow_golem", "strider"]], "A thrown Water Potion deals 1 health of indirect magic damage to a water-sensitive mob within squared distance less than 16 of impact. These four vanilla Mob classes return true from isSensitiveToWater; there is no water-sensitivity registry tag.", "water_harming:" + item, source_class="net.minecraft.world.entity.projectile.throwableitemprojectile.AbstractThrownPotion", requiredComponents=water_components, damage=1)
        fire_targets = [block(fire) for fire in resolve("block", "minecraft:fire")] + ["minecraft:campfire", "minecraft:soul_campfire"]
        for tag in ["minecraft:candles", "minecraft:candle_cakes"]:
            fire_targets += [node for block_id in resolve("block", tag) if (node := block(block_id))]
        add("extinguishing", [item], fire_targets, "Water Potion impacts douse Fire/Soul Fire and lit Candles, Candle Cakes and Campfires at the impact-adjacent positions checked by the projectile. Fire blocks are removed; candle/campfire blocks remain unlit.", "water_dousing:" + item, source_class="net.minecraft.world.entity.projectile.throwableitemprojectile.AbstractThrownPotion", requiredComponents=water_components)
    for tool in ["minecraft:flint_and_steel", "minecraft:fire_charge"]:
        add("igniting", [tool], [block("fire")], "Use the igniter at a valid empty position on ordinary supporting blocks to place Fire; Flint and Steel loses durability, Fire Charge is consumed. A Soul Fire support block instead produces Soul Fire.", "ordinary_fire:" + tool, source_class="net.minecraft.world.level.block.BaseFireBlock")
        supports = [block(value) for value in resolve("block", "minecraft:soul_fire_base_blocks")]
        add("igniting", [tool] + supports, [block("soul_fire")], "Use the igniter above a Soul Fire Base block (Soul Sand or Soul Soil) to place Soul Fire; the support is retained. The igniter takes durability or is consumed.", "soul_fire:" + tool, source="vanilla_block_tag_and_audited_interaction", source_class="net.minecraft.world.level.block.BaseFireBlock")
        add("portal_igniting", [tool, "minecraft:obsidian"], [block("nether_portal")], "Ignite the interior of a valid Obsidian rectangle to create a Nether Portal. The interior is 2–21 blocks wide and 3–21 high, with a complete valid Obsidian frame and eligible dimension/portal rules. Obsidian and an igniter alone do not suffice; Crying Obsidian cannot substitute.", "nether_portal:" + tool, source_class="net.minecraft.world.level.portal.PortalShape", conditions=["Valid Obsidian frame with eligible interior", "Portal-eligible dimension", "Ignition at a valid frame interior position"])
        add("igniting", [tool], ["minecraft:tnt"], "Use the igniter on a placed TNT block to prime it, when the TNT Explodes game rule permits. The igniter is damaged or consumed; a lit TNT entity replaces the block.", "tnt_igniting:" + tool, source_class="net.minecraft.world.level.block.TntBlock")
    for ice in ["minecraft:ice", "minecraft:frosted_ice"]:
        add("melting", [block(ice)], [block("water")], "Placed Ice melts when its brightness/neighbor checks permit; Frosted Ice also ages and melts after its tick delays. Melting produces Water in ordinary dimensions; in an ultrawarm dimension the ice disappears instead. Packed and Blue Ice do not melt this way.", "ice_melting:" + ice, source_class="net.minecraft.world.level.block.IceBlock / net.minecraft.world.level.block.FrostedIceBlock", conditions=["Applicable light, age and neighbor checks", "Dimension not ultrawarm"])
    frost_walker = read_json("data/minecraft/enchantment/frost_walker.json")
    walker_items = targets("item", frost_walker["supported_items"])
    add("frost_walking", walker_items + [block("water")], [block("frosted_ice")], "Frost Walker on supported boots worn in the feet slot replaces eligible Water blocks below the wearer with Frosted Ice. Requires being on ground, not riding, air above, matching water and an unobstructed position. Radius is 3 at level I and 4 at level II; the exact enchantment definition is preserved. Unenchanted boots do not freeze water.", "frost_walking", source="vanilla_enchantment_definition", source_class="net.minecraft.world.item.enchantment.effects.ReplaceDisk", requiredEnchantments={"minecraft:frost_walker": {"min": 1}}, raw=frost_walker)

    ids = [record["id"] for record in relationships]
    if len(ids) != len(set(ids)) or len(edges) != len({edge["id"] for edge in edges}):
        raise ValueError("Duplicate interaction IDs")
    return {"nodes": [], "relationships": relationships, "edges": edges,
            "coverage": {"source": "SHA1-verified Java 26.3 registry mappings, default item components, item/block/entity tags and all referenced block transformers, plus version-pinned Java interaction audits",
                         "spawnEggs": len(metadata["spawnEggs"]), "mobBuckets": len(metadata["mobBuckets"]), "eggItems": len(egg_items), "foodTags": sorted("minecraft:" + food + "_food" for food in food_mobs),
                         "blockTransformers": sorted(transformer_items), "transformRules": transform_rules, "waxMappings": len(metadata["waxables"]), "oxidationMappings": len(metadata["oxidation"]),
                         "infestationMappings": len(metadata["infestation"]), "flowerPotMappings": len(metadata["flowerPots"]), "constructionChestMappings": len(metadata["copperConstructionChests"]), "miningTargets": mining_targets, "omittedBlockNodes": sorted(omitted_blocks),
                         "relationshipTypes": dict(sorted(Counter(record["type"] for record in relationships).items())), "itemCapabilities": capabilities,
                         "limitations": ["No new structure, biome, action, player, dimension or chest-loot nodes.", "World interactions are finite audited triggers, not exhaustive world/AI simulation or arbitrary customized stacks.", "Mob equipment/pickup ability is not inferred for items lacking explicit allowed-entity restrictions.", "Natural spawning environments, arbitrary spawner/trial-spawner entity data, lightning and command spawning are excluded.", "Inventory-less block targets absent from the existing graph are omitted and listed explicitly."]}}
