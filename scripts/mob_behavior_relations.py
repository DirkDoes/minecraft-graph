"""Finite mob conversions and environmental behaviors from the audited 26.3 client.

Links describe conditional interactions, not unconditional crafting. Runtime
state (age, variant, difficulty, dimensions, AI and block state) stays on each
relationship. This adds no entities and deliberately excludes world locations.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

from mob_relations import iter_loot_items

ROOT = Path(__file__).resolve().parents[1]
AUDITED_CLIENT_SHA1 = "e877b6a07acd633fb3bb475002175cec036e7b87"


def build_mob_behaviors(game, version, existing_nodes):
    if version != "26.3":
        raise ValueError("Mob behavior rules require a new game-version audit")
    client_hash = hashlib.sha1(Path(game.jar.filename).read_bytes()).hexdigest()
    if client_hash != AUDITED_CLIENT_SHA1:
        raise ValueError("Mob behavior rules require the exact audited 26.3 client")
    block_items = json.loads((ROOT / ".cache/gathering-metadata.json").read_text(encoding="utf-8"))["blockItems"]
    ids = {node["id"] for node in existing_nodes}
    records, edges, raw_tags, omitted = [], [], {}, set()
    bounds = {"minVersion": version, "maxVersion": None}
    cache = {}

    def item(slug):
        return slug if ":" in slug else "minecraft:" + slug

    def mob(slug):
        return "mob:" + item(slug)

    def block(slug):
        block_id = item(slug)
        output = block_items[block_id]
        output = output if output != "minecraft:air" else "block:" + block_id
        if output in ids:
            return output
        omitted.add(block_id)
        return None

    def tag(domain, name, ancestors=()):
        name = item(name.removeprefix("#"))
        key = domain + ":" + name
        if key in cache:
            return cache[key]
        if key in ancestors:
            raise ValueError("Cyclic mob behavior tag " + key)
        namespace, slug = name.split(":", 1)
        data = json.loads(game.jar.read(f"data/{namespace}/tags/{domain}/{slug}.json"))
        raw_tags[key] = data
        values = set()
        for entry in data["values"]:
            entry = entry["id"] if isinstance(entry, dict) else entry
            values.update(tag(domain, entry, ancestors + (key,))) if entry.startswith("#") else values.add(item(entry))
        cache[key] = sorted(values)
        return cache[key]

    def add(kind, inputs, outputs, key, note, source_class, *, category="uses", **metadata):
        inputs, outputs = list(dict.fromkeys(inputs)), list(dict.fromkeys(outputs))
        if not inputs or not outputs or any(endpoint not in ids for endpoint in inputs + outputs):
            raise ValueError(f"Unknown or empty mob behavior endpoints in {key}: {inputs} -> {outputs}")
        record_id = "interaction:behavior/" + key
        record = {"id": record_id, "category": category, "type": kind,
                  "name": kind.replace("_", " ").capitalize(), "note": note,
                  "inputs": [{"nodeId": value} for value in inputs], "outputs": [{"nodeId": value} for value in outputs],
                  "source": "audited_game_behavior", "sourceClass": source_class, **bounds, **metadata}
        records.append(record)
        for start in inputs:
            for end in outputs:
                edges.append({"id": f"{record_id}:{start}>{end}", "source": start, "target": end,
                              "category": category, "type": kind, "relationId": record_id, **bounds})

    # Entity conversion IDs are taken from the actual convertTo calls. No new
    # nodes are fabricated for alternate ages, colors, professions or AI states.
    for start, end in (("zombie", "drowned"), ("husk", "zombie")):
        add("mob_conversion", [mob(start), block("water")], [mob(end)], "water/" + start,
            "The mob's eyes must remain submerged in water throughout the drowning conversion. The configured exposure counter is 600 ticks and conversion counter 300 ticks; leaving water resets the process. A Husk first becomes a Zombie, which can later become a Drowned. AI and tracker checks apply.",
            "Zombie.convertsToWhenDrowning / Husk.convertsToWhenDrowning; ConversionTracker",
            conditions=["Eyes submerged in water", "AI enabled", "600-tick exposure followed by 300-tick conversion"],
            trigger="water", exposureTicks=600, conversionTicks=300)
    add("mob_conversion", [mob("skeleton"), block("powder_snow")], [mob("stray")], "freezing/skeleton",
        "A Skeleton continuously inside Powder Snow converts into a Stray. The configured freezing counter is 140 ticks and conversion counter 300 ticks; leaving Powder Snow resets the process. Living/AI checks apply. This rule belongs to Skeleton, not every AbstractSkeleton subclass.",
        "Skeleton constructor / tick; ConversionTracker.tick", trigger="powder_snow", exposureTicks=140, conversionTicks=300,
        conditions=["Continuously inside Powder Snow", "AI enabled", "140-tick freezing counter followed by 300-tick conversion counter"])
    for start, end in (("piglin", "zombified_piglin"), ("piglin_brute", "zombified_piglin"), ("hoglin", "zoglin")):
        add("mob_conversion", [mob(start)], [mob(end)], "zombification/" + start,
            "Converts after more than 300 consecutive AI ticks where the local piglins_zombify environment attribute is true. A mob with zombification immunity or disabled AI does not convert; the attribute normally applies outside the Nether.",
            "AbstractPiglin.customServerAiStep / Hoglin.customServerAiStep",
            conditions=["Local minecraft:piglins_zombify environment attribute", "No zombification immunity", "AI enabled", "More than 300 consecutive ticks"],
            trigger="minecraft:piglins_zombify", conversionTicks=301)
    for killer in ("zombie", "husk", "zombie_villager", "drowned", "zombified_piglin"):
        add("infection", [mob(killer), mob("villager")], [mob("zombie_villager")], "infection/" + killer,
            "When this Zombie subclass kills a Villager, the Villager can convert into a Zombie Villager. The chance is 50% on Normal and 100% on Hard; Easy and Peaceful do not use this conversion. The attack must kill the Villager.",
            "Zombie.killedEntity / Zombie.convertVillagerToZombieVillager",
            conditions=["Killing blow on a Villager", "Normal: 50%; Hard: 100%", "No infection on Easy or Peaceful"],
            probabilityByDifficulty={"easy": 0, "normal": 0.5, "hard": 1, "peaceful": 0})
    add("mob_conversion", [mob("mooshroom"), item("shears")], [mob("cow")], "shearing/mooshroom",
        "Shearing a living adult Mooshroom converts it into a Cow and separately drops its mushrooms. Shears are a tool, not a consumed ingredient; babies cannot be sheared.",
        "MushroomCow.readyForShearing / MushroomCow.shear", conditions=["Living adult Mooshroom", "Use Shears"])
    add("mob_conversion", [mob("tadpole")], [mob("frog")], "growth/tadpole",
        "A Tadpole grows into a Frog when its age reaches 24000 ticks (20 minutes at the normal tick rate). Food can accelerate growth. Age-locked Tadpoles do not age naturally; the resulting Frog variant is chosen by the game's location rules.",
        "Tadpole.setAge / Tadpole.ageUp", conditions=["Age reaches 24000 ticks", "Natural aging requires age not locked"],
        growthTicks=24000)
    for start, end in (("pig", "zombified_piglin"), ("villager", "witch")):
        add("mob_conversion", [mob(start)], [mob(end)], "lightning/" + start,
            "A lightning strike converts this mob when difficulty is not Peaceful. Lightning is a required world trigger, not an additional node or an unconditional transformation.",
            ("Pig" if start == "pig" else "Villager") + ".thunderHit",
            conditions=["Struck by lightning", "Difficulty is not Peaceful"], trigger="lightning")

    # These are separate conditional outputs of the mob loot tables, preserving
    # the exact damage-source/variant predicates. Frog predation itself is owned
    # by interaction_relations; here the extra actor→loot connection is explicit.
    for prey in ("slime", "magma_cube"):
        for index, loot in enumerate(iter_loot_items(game, "minecraft:entities/" + prey)):
            condition = loot["rawEntry"].get("condition", {})
            if condition.get("type") != "minecraft:damage_source_properties":
                continue
            source_entity = condition.get("predicate", {}).get("source_entity", {})
            if source_entity.get("minecraft:entity_type") != "minecraft:frog":
                continue
            variant = source_entity.get("minecraft:components", {}).get("minecraft:frog/variant")
            note = "A Frog swallowing a small (size 1) " + ("Slime" if prey == "slime" else "Magma Cube") + " produces one of this item when mob loot is enabled. "
            note += "Slime Balls are independent of Frog color." if not variant else "This output requires the Frog variant " + variant.split(":")[1] + "; other variants produce different Froglights."
            add("predation_drop", [mob("frog"), mob(prey)], [loot["item"]], f"frog_loot/{prey}/{index}", note,
                "ShootTongue.eatEntity; " + loot["sourceLootTable"], category="gathering",
                conditions=["Frog swallowing a size-1 prey", "Mob loot enabled"] + (["Frog variant: " + variant] if variant else []),
                loot=loot, preySize=1, quantity=1, **({"frogVariant": variant} if variant else {}))

    for tag_name, kind in (("axolotl_hunt_targets", "hunting"), ("axolotl_always_hostiles", "hostile_targeting")):
        for prey in tag("entity_type", tag_name):
            add(kind, [mob("axolotl")], [mob(prey)], "axolotl/" + tag_name + "/" + prey,
                "An Axolotl targets this nearby attackable entity when the target is in water and within 8 blocks. Ordinary prey require no hunting cooldown; hostile targets bypass that cooldown. Targeting, visibility and AI checks still apply.",
                "AxolotlAttackablesSensor.isMatchingEntity / isHuntTarget / isHostileTarget",
                conditions=["Target in water", "Within 8 blocks", "Attackable target"] + (["No hunting cooldown"] if kind == "hunting" else []),
                entityTypeTag=item(tag_name), maximumRange=8)

    prey_groups = [("wolf", ("sheep", "rabbit", "fox"), "Untamed Wolf", "Wolf.PREY_SELECTOR / NonTameRandomTargetGoal"),
                   ("fox", ("chicken", "rabbit", "cod", "salmon", "tropical_fish"), "Fox hunting goals; fish must be AbstractSchoolingFish", "Fox.registerGoals / setTargetGoals"),
                   ("cat", ("rabbit",), "Untamed Cat", "Cat.registerGoals / NonTameRandomTargetGoal"),
                   ("ocelot", ("chicken",), "Ocelot", "Ocelot.registerGoals"),
                   ("polar_bear", ("fox",), "Adult Polar Bear", "PolarBear.registerGoals")]
    for hunter, prey_set, state, source_class in prey_groups:
        for prey in prey_set:
            add("hunting", [mob(hunter)], [mob(prey)], "hunting/" + hunter + "/" + prey,
                state + " can select this mob with its prey/attack-target goal. This records an AI target relationship, not a guaranteed kill, tameable-food item or drop. Normal target selection and visibility checks apply.",
                source_class, conditions=[state, "AI target selection succeeds"])
    for hunter in ("wolf", "fox", "cat", "ocelot"):
        add("hunting", [mob(hunter)], [mob("turtle")], "hunting/" + hunter + "/baby_turtle",
            "This mob's attack goal targets baby Turtles on land. Adult Turtles and Turtles in water do not satisfy BABY_ON_LAND_SELECTOR. Wolf and Cat use this goal only while untamed.",
            hunter.title() + ".registerGoals; Turtle.BABY_ON_LAND_SELECTOR",
            conditions=["Baby Turtle", "Turtle on land", "Untamed hunter" if hunter in ("wolf", "cat") else "AI target selection succeeds"])
    for skeleton in ("skeleton", "stray", "bogged", "parched", "wither_skeleton"):
        add("hostile_targeting", [mob("wolf")], [mob(skeleton)], "wolf_skeleton/" + skeleton,
            "Wolves have an attack-target goal for AbstractSkeleton subclasses, including this entity type. This is separate from their untamed animal-prey goal and remains conditional on normal targeting checks.",
            "Wolf.registerGoals / NearestAttackableTargetGoal<AbstractSkeleton>", conditions=["Attackable AbstractSkeleton", "AI target selection succeeds"])

    # Direction is repellent→affected mob, matching tool/food→affected mob links.
    for source, target, condition, source_class in (
            ("cat", "creeper", "Within 6 blocks", "Creeper.registerGoals"),
            ("ocelot", "creeper", "Within 6 blocks", "Creeper.registerGoals"),
            ("cat", "phantom", "Living Cat within 16-block inflated search box during a dive; checked every 20 ticks", "PhantomSweepAttackGoal.canContinueToUse"),
            ("llama", "wolf", "Untamed Wolf; random 0–4 strength check succeeds; within 24 blocks", "WolfAvoidEntityGoal.canUse / avoidLlama"),
            ("trader_llama", "wolf", "Untamed Wolf; random 0–4 strength check succeeds; within 24 blocks", "WolfAvoidEntityGoal.canUse / avoidLlama"),
            ("wolf", "fox", "Untamed Wolf; Fox not defending; within 8 blocks", "Fox.registerGoals"),
            ("polar_bear", "fox", "Fox not defending; within 8 blocks", "Fox.registerGoals")):
        add("repelling", [mob(source)], [mob(target)], "repelling/" + source + "/" + target,
            "The affected mob avoids this entity or aborts its attack under the stated AI conditions. This is an avoidance behavior, not damage or an unconditional immunity.",
            source_class, conditions=[condition, "AI behavior can run"])
    for target, tag_name, source_class in (("hoglin", "hoglin_repellents", "HoglinSpecificSensor.findNearestRepellent / HoglinAi"),
                                           ("piglin", "piglin_repellents", "PiglinSpecificSensor.isValidRepellent / PiglinAi")):
        for value in tag("block", tag_name):
            start = block(value)
            if start:
                conditions = ["Placed block", "Nearby valid repellent detected by AI"]
                if value == "minecraft:soul_campfire":
                    conditions.append("Soul Campfire must be lit")
                add("repelling", [start], [mob(target)], "repellent_block/" + target + "/" + value,
                    "The mob's AI sensor recognizes this placed block as a repellent. A Soul Campfire is valid only when lit. This does not apply the same behavior to Piglin Brutes or undead variants.",
                    source_class, conditions=conditions, targetBlock=value, blockTag=item(tag_name))

    for value in tag("block", "bee_attractive"):
        start = block(value)
        if start:
            add("pollination", [start], [mob("bee")], "pollination/" + value,
                "Bees can visit this placed flower/block and collect nectar. The block must not be waterlogged; Sunflowers require the upper half. Reachability, existing nectar, weather and pollination goal conditions still apply. This is separate from breeding food.",
                "Bee.attractsBees / BeePollinateGoal", targetBlock=value, blockTag="minecraft:bee_attractive",
                conditions=["Placed, reachable block", "Not waterlogged"] + (["Upper Sunflower half"] if value == "minecraft:sunflower" else []))
    for value in tag("block", "beehives"):
        hive = block(value)
        if hive:
            add("mob_shelter", [hive], [mob("bee")], "shelter/" + value,
                "A Bee can enter this hive block when it has capacity and the Bee's hive-entry/AI conditions permit. Weather, nectar, anger, smoke and hive safety affect behavior; the inventory item must be placed.",
                "BeeEnterHiveGoal / BeeLocateHiveGoal", targetBlock=value, conditions=["Placed hive with free capacity", "Bee hive-entry checks succeed"])
            add("honey_production", [mob("bee")], [hive], "nectar/" + value,
                "A Bee returning with nectar can increase the hive's honey level after staying inside it. This affects the placed block's state; it does not directly grant a Honey Bottle or Honeycomb. Their harvesting tools are separate relationships.",
                "BeehiveBlockEntity.releaseOccupant", targetBlock=value, conditions=["Bee enters with nectar", "Hive processing time", "Honey level below maximum"])
    for value in tag("block", "bee_growables"):
        # BeeGrowCropGoal only implements these classes/states; membership in the
        # tag alone is insufficient (e.g. PitcherCropBlock is a DoublePlant).
        active = ("wheat", "carrots", "potatoes", "beetroots", "torchflower_crop", "melon_stem", "pumpkin_stem", "sweet_berry_bush", "cave_vines", "cave_vines_plant")
        if value.split(":", 1)[1] not in active:
            continue
        target = block(value)
        if target:
            add("crop_pollination", [mob("bee")], [target], "bee_growing/" + value,
                "A nectar-carrying Bee with a valid hive can advance a supported immature crop below it. Growth is random, limited per nectar trip and gated by the crop's state. This is a placed-block growth effect, not an immediate harvest.",
                "BeeGrowCropGoal.canBeeUse / tick", targetBlock=value, blockTag="minecraft:bee_growables",
                conditions=["Bee carries nectar and has a valid hive", "Immature supported crop below Bee", "Random AI growth check", "At most ten growths since pollination"])

    for tag_name, target_mobs, source_class in (
            ("horse_tempt_items", ("horse", "donkey", "mule"), "AbstractHorse.addBehaviourGoals"),
            ("zombie_horse_food", ("zombie_horse",), "ZombieHorse.addBehaviourGoals"),
            ("llama_tempt_items", ("llama", "trader_llama"), "Llama.registerGoals"),
            ("strider_tempt_items", ("strider",), "Strider.registerGoals"),
            ("happy_ghast_tempt_items", ("happy_ghast",), "HappyGhast.registerGoals / lambda$registerGoals$0")):
        sources = tag("item", tag_name)
        category_id = "tag:" + item(tag_name)
        if category_id in ids:
            sources = sources + [category_id]
        for source in sources:
            for target in target_mobs:
                conditions = ["Item held by nearby player", "TemptGoal conditions succeed"]
                if target == "happy_ghast" and source not in tag("item", "happy_ghast_food"):
                    conditions.append("Adult Happy Ghast without body armor for harness temptation")
                add("attraction", [source], [mob(target)], "tempt/" + tag_name + "/" + source + "/" + target,
                    "Holding an item matching this tempt-item tag can lead this mob through its TemptGoal. AI, proximity and goal conditions apply. A tempting item is not necessarily edible by this mob. Baby or already harnessed Happy Ghasts only follow food; harnesses tempt unharnessed adults.",
                    source_class, conditions=conditions, itemTag=item(tag_name))
    for kind, tag_name, source_class in (("resting", "cats_can_lie_on", "CatLieOnBlockGoal"), ("sitting", "cats_can_sit_on", "CatSitOnBlockGoal")):
        for value in tag("block", tag_name):
            start = block(value)
            if start:
                conditions = ["Tamed Cat, not ordered to sit", "Empty block above target"]
                if kind == "sitting":
                    if value == "minecraft:chest": conditions.append("Chest has no opener")
                    elif value == "minecraft:furnace": conditions.append("Furnace is lit")
                    elif value.endswith("_bed"): conditions.append("Foot of bed")
                add(kind, [start], [mob("cat")], "cat_" + kind + "/" + value,
                    "A tamed Cat can choose this placed block for its " + kind + " goal when the state and space checks pass. This is an AI use of the block, not a spawning location or biome connection.",
                    source_class + ".canUse / isValidTarget", conditions=conditions, targetBlock=value, blockTag=item(tag_name))
    for value in tag("block", "sniffer_egg_hatch_boost"):
        start = block(value)
        if start:
            add("incubation", [start], [item("sniffer_egg")], "sniffer_incubation/" + value,
                "A placed Sniffer Egg above this hatch-boost substrate advances its hatching stages more quickly. The egg must be directly above the block; this link supports incubation and does not create another egg.",
                "SnifferEggBlock.hatchBoost / scheduleHatch", conditions=["Placed Sniffer Egg directly above block"], targetBlock=value, blockTag="minecraft:sniffer_egg_hatch_boost")

    golem = mob("copper_golem")
    add("mob_waxing", [item("honeycomb")], [golem], "copper_golem/wax",
        "Using Honeycomb on an unwaxed Copper Golem stops its weathering by setting its next weathering tick to the waxed sentinel. Honeycomb is consumed outside creative mode. The entity remains a Copper Golem node.",
        "CopperGolem.mobInteract", conditions=["Copper Golem is not already waxed"])
    axe_sources = tag("item", "axes")
    if "tag:minecraft:axes" in ids:
        axe_sources = axe_sources + ["tag:minecraft:axes"]
    for axe in axe_sources:
        for kind, condition, note in (("mob_unwaxing", "Waxed Copper Golem", "Using an axe removes wax from a Copper Golem and resumes weathering; the first use does not also lower oxidation."),
                                     ("mob_scraping", "Unwaxed Copper Golem with oxidation above Unaffected", "Using an axe lowers an unwaxed Copper Golem's oxidation by one stage and resets its next weathering tick.")):
            add(kind, [axe], [golem], "copper_golem/" + kind + "/" + axe, note,
                "CopperGolem.mobInteract", conditions=[condition, "Use an item in minecraft:axes"], itemTag="minecraft:axes")
        add("statue_activation", [axe, item("copper_golem_statue")], [golem], "copper_golem/activate/" + axe,
            "An axe activates a placed, unwaxed, fully scraped (Unaffected) Copper Golem Statue, removes the statue block and restores the Copper Golem. Exposed/Weathered/Oxidized or waxed statues must first be scraped/unwaxed by their separate block transformations.",
            "WeatheringCopperGolemStatueBlock.useItemOn / CopperGolemStatueBlockEntity.removeStatue",
            conditions=["Placed unwaxed Copper Golem Statue", "Unaffected oxidation stage", "Valid statue block entity"], itemTag="minecraft:axes")
    add("mob_statue_conversion", [golem], [item("oxidized_copper_golem_statue")], "copper_golem/statue",
        "An unwaxed Copper Golem that reaches Oxidized can turn into an Oxidized Copper Golem Statue. The game checks for an air block at its position and applies a 0.0058 random chance during weathering checks. This is not a conversion to the Unaffected statue item.",
        "CopperGolem.tickWeathering / canTurnToStatue / turnToStatue",
        conditions=["Unwaxed, Oxidized Copper Golem", "Air block at entity block position", "Random statue check succeeds"], chancePerCheck=0.0058)

    if len({r["id"] for r in records}) != len(records) or len({e["id"] for e in edges}) != len(edges):
        raise ValueError("Duplicate mob behavior IDs")
    return {"nodes": [], "relationships": records, "edges": edges,
            "coverage": {"version": version, "clientSha1": client_hash, "relationshipCount": len(records), "edgeCount": len(edges),
                         "types": dict(sorted(Counter(record["type"] for record in records).items())),
                         "rawTags": raw_tags, "omittedUnrepresentedBlocks": sorted(omitted),
                         "scope": "Finite audited mob conversions, predators, repellents, pollination, incubation, temptation, Cat resting and Copper Golem behavior. Runtime states are predicates; no new nodes."}}
