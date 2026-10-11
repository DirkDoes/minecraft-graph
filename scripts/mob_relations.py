"""Extract actual Mob subclasses and possible loot outputs from the verified client.

Named loot tables are recursively expanded. Every output retains all predicates,
selection context and modifiers rather than inventing a single drop probability.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_REPORT = ROOT / ".cache" / "mob-models.json"


def load_loot_table(game, table_id):
    namespace, path = table_id.split(":", 1)
    return json.loads(game.jar.read(f"data/{namespace}/loot_table/{path}.json"))


def _list(value):
    return value if isinstance(value, list) else [value]


def iter_loot_items(game, table_id):
    """Yield possible {item, conditions, modifiers, selection, rawEntry, ...} outputs.

    Conditions are [{path,value}], with version-26.3 singular condition syntax
    preserved. References and alternative ordering remain in selection context.
    Dynamic container contents cannot be statically enumerated and yield no item.
    """
    if not hasattr(game, "_loot_smelting"):
        game._loot_smelting = {}
        for path in game.jar.namelist():
            if path.startswith("data/minecraft/recipe/") and path.endswith(".json"):
                recipe = json.loads(game.jar.read(path))
                if recipe.get("type") == "minecraft:smelting":
                    output = recipe["result"]
                    output = output if isinstance(output, str) else output["id"]
                    for item in game.ingredient(recipe["ingredient"])["items"]:
                        game._loot_smelting[item] = output
    smelting = game._loot_smelting

    def scoped(obj, path, conditions, modifiers):
        conditions = list(conditions)
        modifiers = list(modifiers)
        for key in ("condition", "conditions"):
            if key in obj:
                conditions += [{"path": f"{path}/{key}/{i}", "value": value} for i, value in enumerate(_list(obj[key]))]
        for key in ("modifier", "functions"):
            if key in obj:
                modifiers = [{"path": f"{path}/{key}/{i}", "value": value} for i, value in enumerate(_list(obj[key]))] + modifiers
        return conditions, modifiers

    def transform(record):
        states = [(record["item"], record["conditions"])]
        for modifier in record["modifiers"]:
            function = modifier["value"]
            kind = function.get("type", function.get("function", ""))
            replacements = []
            for item, conditions in states:
                output = item
                if kind in ("minecraft:enchant_randomly", "minecraft:enchant_with_levels") and item == "minecraft:book":
                    output = "minecraft:enchanted_book"
                elif kind == "minecraft:furnace_smelt":
                    output = smelting.get(item, item)
                elif kind == "minecraft:exploration_map" and item == "minecraft:map":
                    output = "minecraft:filled_map"
                if output != item:
                    predicate = function.get("condition", function.get("conditions"))
                    if predicate is not None:
                        values = _list(predicate)
                        condition = values[0] if len(values) == 1 else {"type": "minecraft:all_of", "terms": values}
                        replacements.append((item, conditions + [{"path": modifier["path"] + "/condition_inverse", "value": {"type": "minecraft:inverted", "term": condition}}]))
                        replacements.append((output, conditions + [{"path": modifier["path"] + "/condition", "value": condition}]))
                    else:
                        replacements.append((output, conditions))
                else:
                    replacements.append((item, conditions))
            states = replacements
        for item, conditions in states:
            if item not in game.items:
                raise ValueError(f"Unregistered loot output {item} in {table_id}")
            yield record | {"item": item, "conditions": conditions, "conditional": True, "unmodifiedItem": record["item"]}

    def table(value, name, path, conditions, modifiers, selection, ancestors):
        if name in ancestors:
            raise ValueError(f"Cyclic loot reference: {' -> '.join(ancestors + (name,))}")
        conditions, modifiers = scoped(value, path, conditions, modifiers)
        for index, pool in enumerate(value.get("pools", [])):
            pool_path = f"{path}/pools/{index}"
            pool_conditions, pool_modifiers = scoped(pool, pool_path, conditions, modifiers)
            context = {"path": pool_path, "type": "pool", "rolls": pool.get("rolls", 1), "bonusRolls": pool.get("bonus_rolls", 0), "entries": [{key: entry[key] for key in ("type", "condition", "weight", "quality") if key in entry} for entry in pool.get("entries", [])]}
            for entry_index, value in enumerate(pool.get("entries", [])):
                yield from entry(value, name, f"{pool_path}/entries/{entry_index}", pool_conditions, pool_modifiers, selection + [context], ancestors + (name,))

    def entry(value, name, path, conditions, modifiers, selection, ancestors):
        conditions, modifiers = scoped(value, path, conditions, modifiers)
        kind = value["type"]
        selection = selection + [{"path": path, "type": kind, "weight": value.get("weight", 1), "quality": value.get("quality", 0)}]
        if kind == "minecraft:loot_table":
            reference = value.get("value", value.get("name"))
            if isinstance(reference, str):
                yield from table(load_loot_table(game, reference), reference, reference, conditions, modifiers, selection, ancestors)
            elif isinstance(reference, dict):
                yield from table(reference, path + "/inline", path + "/value", conditions, modifiers, selection, ancestors)
            else:
                raise ValueError(f"Missing loot table reference in {path}")
        elif kind in ("minecraft:alternatives", "minecraft:group", "minecraft:sequence"):
            previous = []
            for index, child in enumerate(value["children"]):
                extra = {"path": path, "type": kind, "childIndex": index, "previousChildren": previous} if kind != "minecraft:group" else {}
                yield from entry(child, name, f"{path}/children/{index}", conditions, modifiers, selection + ([extra] if extra else []), ancestors)
                previous = previous + [child]
        elif kind in ("minecraft:item", "minecraft:tag"):
            if kind == "minecraft:tag" and "items" in value:
                ids = game.ingredient(value["items"])["items"]
            else:
                resource = value.get("name", value.get("value"))
                if not isinstance(resource, str):
                    raise ValueError(f"Missing item/tag identifier in {path}: {value}")
                ids = game.resolve_tag(resource) if kind == "minecraft:tag" else [resource]
            for item in ids:
                record = {"item": item, "sourceLootTable": table_id, "resolvedLootTable": name, "entryPath": path, "conditions": conditions, "modifiers": modifiers, "selection": selection, "rawEntry": value}
                yield from transform(record)
        elif kind in ("minecraft:empty", "minecraft:dynamic"):
            return
        else:
            raise ValueError(f"Unsupported loot entry {kind} in {path}")

    yield from table(load_loot_table(game, table_id), table_id, table_id, [], [], [], ())


def build_mobs(game, version):
    report = json.loads(MODEL_REPORT.read_text(encoding="utf-8"))
    actual_hash = hashlib.sha1(Path(game.jar.filename).read_bytes()).hexdigest()
    if report.get("version") != version or report.get("clientSha1") != actual_hash:
        raise ValueError("Mob geometry cache version/client SHA1 mismatch; regenerate ExportMobGeometry.java")
    registry = json.loads((ROOT / ".cache/generated/reports/registries.json").read_text(encoding="utf-8"))["minecraft:entity_type"]["entries"]
    if set(report["entities"]) != set(registry):
        raise ValueError("Mob class report does not cover the complete entity registry; regenerate ExportMobGeometry.java")
    language = json.loads(game.jar.read("assets/minecraft/lang/en_us.json"))
    nodes, relationships, edges = [], [], []
    for entity, record in report["entities"].items():
        if not record["mob"]:
            continue
        slug = entity.split(":")[1]
        node_id = "mob:" + entity
        nodes.append({"id": node_id, "kind": "mob", "name": language["entity.minecraft." + slug], "icon": "assets/mobs/" + slug + ".png", "minVersion": version, "maxVersion": None, "entityType": entity, "sourceClass": record["class"], "sourceLootTable": record.get("lootTable")})
        if record.get("lootTable"):
            for index, drop in enumerate(iter_loot_items(game, record["lootTable"])):
                relation_id = f"loot:{entity}/{index}"
                relationships.append({"id": relation_id, "category": "loot", "type": "mob_drop", "minVersion": version, "maxVersion": None, "source": "vanilla_loot_table", "inputs": [node_id], "outputs": [drop["item"]], "note": "Possible death loot; conditions, weighted selections, counts and modifiers affect whether and how much drops.", **drop})
                edges.append({"id": "edge:" + relation_id, "source": node_id, "target": drop["item"], "category": "loot", "type": "mob_drop", "relationId": relation_id, "minVersion": version, "maxVersion": None})
    # shortcut: four witch drinking states are audited for26.3, audit runtime equipment again when adding another version.
    if version != "26.3":
        raise ValueError("Runtime witch potion drops must be audited for the selected version")
    if abs(report["defaultEquipmentDropChance"] - 0.085) > 1e-6:
        raise ValueError("Default equipment drop chance changed; audit witch potion drops")
    for potion in ("water_breathing", "fire_resistance", "healing", "swiftness"):
        relation_id = "loot:minecraft:witch/drinking_" + potion
        conditions = [
            {"path": "Witch.aiStep/mainhand", "value": {"type": "runtime_state", "drinking": True, "mainhandPotion": "minecraft:" + potion}},
            {"path": "Mob.dropCustomDeathLoot/player_hit", "value": {"type": "recent_player_damage"}},
            {"path": "Mob.dropCustomDeathLoot/chance", "value": {"type": "equipment_drop_chance", "base": 0.085, "enchantmentModified": True}},
        ]
        relationships.append({"id": relation_id, "category": "loot", "type": "mob_drop", "minVersion": version, "maxVersion": None, "source": "vanilla_game_code", "sourceClasses": ["net.minecraft.world.entity.monster.Witch.aiStep", "net.minecraft.world.entity.Mob.dropCustomDeathLoot", "net.minecraft.world.entity.DropChances.DEFAULT"], "inputs": ["mob:minecraft:witch"], "outputs": ["minecraft:potion"], "item": "minecraft:potion", "components": {"minecraft:potion_contents": {"potion": "minecraft:" + potion}}, "conditions": conditions, "conditional": True, "note": "While drinking this potion, a witch can drop its held bottle after recent player damage. Base equipment chance is 8.5%; enchantments may modify it."})
        edges.append({"id": "edge:" + relation_id, "source": "mob:minecraft:witch", "target": "minecraft:potion", "category": "loot", "type": "mob_drop", "relationId": relation_id, "minVersion": version, "maxVersion": None})
    for index, drop in enumerate(iter_loot_items(game, "minecraft:charged_creeper/root")):
        entity_ids = {condition["value"].get("predicate", {}).get("minecraft:entity_type") for condition in drop["conditions"]}
        entity_ids.discard(None)
        if len(entity_ids) != 1:
            raise ValueError("Unknown charged creeper victim predicate")
        victim = "mob:" + entity_ids.pop()
        if victim not in {node["id"] for node in nodes}:
            raise ValueError("Charged creeper head references a non-mob victim")
        relation_id = "loot:charged_creeper/" + str(index)
        drop = drop | {"conditions": drop["conditions"] + [{"path": "Creeper.killedEntity", "value": {"type": "runtime_state", "killer": "minecraft:creeper", "powered": True, "alreadyDroppedSkull": False, "mobLootEnabled": True}}]}
        relationships.append({"id": relation_id, "category": "loot", "type": "mob_drop", "minVersion": version, "maxVersion": None, "source": "vanilla_loot_table_and_game_code", "sourceClasses": ["net.minecraft.world.entity.monster.Creeper.killedEntity"], "inputs": [victim], "outputs": [drop["item"]], "supportNodes": ["mob:minecraft:creeper"], "note": "A charged creeper can cause this victim's head to drop; the creeper must not have already produced a skull and mob loot must be enabled.", **drop})
        edges.append({"id": "edge:" + relation_id, "source": victim, "target": drop["item"], "category": "loot", "type": "mob_drop", "relationId": relation_id, "minVersion": version, "maxVersion": None})
    return {"nodes": nodes, "relationships": relationships, "edges": edges, "coverage": {"registeredEntityTypes": len(registry), "mobClasses": len(nodes), "deathLootOutputs": len(edges), "runtimeWitchPotionStates": 4, "chargedCreeperHeads": 5, "classification": "EntityTypes generic class is assignable to the game's Mob base class", "limitations": ["Possible outputs, not guaranteed drops; full loot predicates and roll/count functions are retained.", "Apart from audited witch drinking potions, dynamically equipped or picked-up items are not enumerable from death loot tables.", "Dynamic container contents depend on runtime contents and cannot be statically enumerated."]}}
