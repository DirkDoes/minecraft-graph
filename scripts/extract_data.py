"""Build a versioned item graph directly from a SHA1-verified vanilla Java jar.

Requires Pillow and the Java version requested by Mojang.
Run from any directory; generated files stay inside this project.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def fetch(path, url, expected_hash=None, offline=False, local=None):
    if path.exists() and (offline or expected_hash):
        payload = path.read_bytes()
        if not expected_hash or hashlib.sha1(payload).hexdigest() == expected_hash:
            return payload
    if local and local.is_file():
        payload = local.read_bytes()
        if hashlib.sha1(payload).hexdigest() == expected_hash:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return payload
    if offline:
        raise RuntimeError(f"Missing or invalid cached file: {path}. Run online first.")
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read()
    if expected_hash and hashlib.sha1(payload).hexdigest() != expected_hash:
        raise RuntimeError(f"SHA1 mismatch for {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def load_game(args):
    manifest = json.loads(fetch(CACHE / "version_manifest_v2.json", MANIFEST_URL, offline=args.offline))
    entry = next(v for v in manifest["versions"] if v["id"] == manifest["latest"]["release"])
    version = json.loads(fetch(CACHE / "version.json", entry["url"], entry["sha1"], args.offline))
    download = version["downloads"]["client"]
    local_jar = args.minecraft_dir / "versions" / version["id"] / f"{version['id']}.jar"
    fetch(CACHE / "client.jar", download["url"], download["sha1"], args.offline, local_jar)
    return version, entry


def generate_reports(args, version):
    report = CACHE / "generated" / "reports"
    stamp = CACHE / "report-version.txt"
    jars = [CACHE / "client.jar"]
    for library in version["libraries"]:
        artifact = library.get("downloads", {}).get("artifact")
        # The data generator does not need platform-specific native renderer libraries.
        if not artifact or library["name"].count(":") > 2 or "java-objc-bridge" in library["name"]:
            continue
        local = args.minecraft_dir / "libraries" / artifact["path"]
        cached = CACHE / "libraries" / artifact["path"]
        if local.exists() and hashlib.sha1(local.read_bytes()).hexdigest() == artifact["sha1"]:
            jars.append(local)
        else:
            fetch(cached, artifact["url"], artifact["sha1"], args.offline, local)
            jars.append(cached)
    classpath = os.pathsep.join(map(str, jars))
    (CACHE / "classpath.txt").write_text(classpath, encoding="utf-8")
    if stamp.exists() and stamp.read_text() == version["downloads"]["client"]["sha1"] and (report / "registries.json").exists():
        return report
    java = args.java or shutil.which("java")
    if not java:
        raise RuntimeError(f"Install Java {version['javaVersion']['majorVersion']} or pass --java PATH.")
    subprocess.run([str(java), "-cp", classpath, "net.minecraft.data.Main", "--reports", "--output", str(CACHE / "generated")], check=True, cwd=ROOT)
    stamp.write_text(version["downloads"]["client"]["sha1"])
    return report


class GameData:
    def __init__(self, jar, reports):
        self.jar = jar
        self.items = set(json.loads((reports / "registries.json").read_text())["minecraft:item"]["entries"])
        self.components = {f"minecraft:{path.stem}": json.loads(path.read_text())["components"] for path in (reports / "minecraft" / "components" / "item").glob("*.json")}
        if set(self.components) != self.items:
            raise ValueError("Default components do not cover the full item registry")
        self.tags = {"minecraft:" + path.removeprefix("data/minecraft/tags/item/").removesuffix(".json"): json.loads(jar.read(path)) for path in jar.namelist() if path.startswith("data/minecraft/tags/item/") and path.endswith(".json")}
        self.resolved_tags = {}

    def resolve_tag(self, tag, ancestors=()):
        tag = tag.removeprefix("#")
        if tag in self.resolved_tags:
            return self.resolved_tags[tag]
        if tag in ancestors:
            raise ValueError(f"Cyclic item tag: {tag}")
        values = set()
        for value in self.tags[tag]["values"]:
            required = True
            if isinstance(value, dict):
                required = value.get("required", True)
                value = value["id"]
            if value.startswith("#"):
                if not required and value[1:] not in self.tags:
                    continue
                values.update(self.resolve_tag(value, ancestors + (tag,)))
            elif value in self.items:
                values.add(value)
            elif required:
                raise ValueError(f"Unknown item {value} in tag {tag}")
        self.resolved_tags[tag] = sorted(values)
        return self.resolved_tags[tag]

    def ingredient(self, value, count=1, **extra):
        if isinstance(value, str):
            group = {"items": self.resolve_tag(value) if value.startswith("#") else [value], "count": count}
            if value.startswith("#"):
                group["tag"] = value[1:]
        elif isinstance(value, list):
            group = {"items": sorted({item for option in value for item in self.ingredient(option)["items"]}), "count": count}
        elif isinstance(value, dict):
            if "tag" in value:
                group = self.ingredient("#" + value["tag"], count)
            elif "item" in value:
                group = self.ingredient(value["item"], count)
                predicates = {key: content for key, content in value.items() if key != "item"}
                if predicates:
                    group["predicates"] = predicates
            else:
                raise ValueError(f"Unknown ingredient format {value}")
        else:
            raise ValueError(f"Unknown ingredient format {value}")
        if not group["items"] or any(item not in self.items for item in group["items"]):
            raise ValueError(f"Empty or unregistered ingredient: {value}")
        return group | extra


def generate_extended_reports(args, version):
    classpath = (CACHE / 'classpath.txt').read_text(encoding='utf-8').strip()
    for script_name, report_name in [('ExportMobGeometry.java', 'mob-models.json'), ('ExportGatheringMetadata.java', 'gathering-metadata.json'),
                                     ('ExportEffectMetadata.java', 'effect-metadata.json'), ('ExportInteractionMetadata.java', 'interaction-metadata.json'),
                                     ('ExportPlantMetadata.java', 'plant-metadata.json')]:
        script = ROOT / 'scripts' / script_name
        report = CACHE / report_name
        stamp = CACHE / (report_name + '.source-sha1')
        checksum = hashlib.sha1(script.read_bytes() + version['downloads']['client']['sha1'].encode()).hexdigest()
        if report.exists() and stamp.exists() and stamp.read_text() == checksum:
            continue
        java = args.java or shutil.which('java')
        if not java:
            raise RuntimeError(f"Install Java {version['javaVersion']['majorVersion']} or pass --java PATH.")
        subprocess.run([str(java), '--class-path', classpath, str(script), str(report)], check=True, cwd=ROOT)
        stamp.write_text(checksum, encoding='utf-8')


def result(value):
    if isinstance(value, str):
        return {"item": value, "count": 1}
    return {"item": value["id"], "count": value.get("count", 1)} | ({"components": value["components"]} if "components" in value else {})


def normalize_recipe(recipe_id, raw, game, version):
    kind = raw["type"].removeprefix("minecraft:")
    recipe = {"id": recipe_id, "type": kind, "category": "recipe", "minVersion": version, "maxVersion": None, "ingredients": [], "results": [], "source": "vanilla_recipe_json", "raw": raw}
    groups = recipe["ingredients"]

    def add(field, count=1, **extra):
        groups.append(game.ingredient(raw[field], count, role=field, **extra))

    def identity(index):
        recipe["resultFromIngredient"] = index
        recipe["resultAlternatives"] = len(groups[index]["items"]) > 1
        recipe["results"] = [{"item": item, "count": 1} for item in groups[index]["items"]]

    output = raw.get("result")
    if isinstance(output, str) or isinstance(output, dict) and "id" in output:
        recipe["results"] = [result(output)]
    for field in ("group", "experience", "cookingtime", "show_notification"):
        if field in raw:
            recipe[field] = raw[field]
    if "category" in raw:
        recipe["bookCategory"] = raw["category"]

    if kind == "crafting_shaped":
        recipe["pattern"] = raw["pattern"]
        recipe["key"] = {symbol: game.ingredient(value) for symbol, value in raw["key"].items()}
        counts = Counter("".join(raw["pattern"]))
        groups.extend(group | {"count": counts[symbol]} for symbol, group in recipe["key"].items())
    elif kind == "crafting_shapeless":
        for value in raw["ingredients"]:
            group = game.ingredient(value)
            previous = next((g for g in groups if g["items"] == group["items"] and g.get("tag") == group.get("tag")), None)
            if previous:
                previous["count"] += 1
            else:
                groups.append(group)
    elif kind in ("smelting", "blasting", "smoking", "campfire_cooking", "stonecutting"):
        add("ingredient")
    elif kind in ("smithing_transform", "smithing_trim"):
        for field in ("template", "base", "addition"):
            add(field)
        if kind == "smithing_trim":
            identity(1)
            recipe["dynamic"] = True
            recipe["note"] = "Applies a trim to the selected base armor; the armor item stays the same. Components depend on the template and trim material."
    elif kind == "brewing":
        add("input")
        add("reagent")
        recipe["results"] = [result(raw["output"])]
        recipe["note"] = "Potion contents are required predicates, preserved in the recipe data. One reagent can brew up to three matching bottles; brewing fuel is a station cost."
    elif kind == "crafting_transmute":
        add("input")
        bounds = raw.get("material_count", {"min": 1, "max": 1})
        add("material", bounds.get("min", 1), maxCount=bounds.get("max", 8))
        if not recipe["results"]:
            identity(0)
        recipe["dynamic"] = True
        recipe["note"] = "Transforms the input while carrying its components."
        if raw.get("add_material_count_to_result"):
            for output in recipe["results"]:
                output["count"] += groups[1]["count"]
                output["maxCount"] = 1 + groups[1]["maxCount"]
            recipe["note"] = "Clones the input map; output count is the original plus the number of empty maps (1–8). Map contents are preserved."
    elif kind == "crafting_decorated_pot":
        for field in ("back", "front", "left", "right"):
            add(field)
        recipe["dynamic"] = True
        recipe["note"] = "Four ingredients form the pot; each ingredient controls one face's decoration."
    elif kind == "crafting_special_bannerduplicate":
        add("banner", 2)
        recipe["dynamic"] = True
        recipe["note"] = "One patterned banner (at most six patterns) and one blank banner of the same color. Produces a copy and returns the original."
    elif kind == "crafting_special_bookcloning":
        add("source", returned=True)
        add("material", 1, maxCount=8)
        recipe["results"][0]["maxCount"] = 8
        recipe["dynamic"] = True
        recipe["note"] = "One written book and 1–8 writable books produce that many copies, returning the original. Copies of copies cannot be cloned again."
    elif kind == "crafting_special_firework_rocket":
        add("shell")
        add("fuel", 1, maxCount=3)
        add("star", 0, maxCount=7, optional=True)
        recipe["dynamic"] = True
        recipe["note"] = "One paper, 1–3 gunpowder and optional firework stars. All inputs must fit the nine crafting slots; fuel controls flight duration and stars control explosions."
    elif kind == "crafting_special_firework_star":
        add("fuel")
        add("dye", 1, maxCount=8)
        groups.append(game.ingredient(list(raw["shapes"].values()), 0, maxCount=1, optional=True, role="shape"))
        add("trail", 0, maxCount=1, optional=True)
        add("twinkle", 0, maxCount=1, optional=True)
        recipe["dynamic"] = True
        recipe["note"] = "One gunpowder, one or more dyes, optional single shape modifier, diamond trail and glowstone twinkle. All inputs must fit nine slots."
    elif kind in ("crafting_dye", "crafting_special_firework_star_fade"):
        add("target")
        add("dye", 1, maxCount=8)
        recipe["dynamic"] = True
        recipe["note"] = "One target and one or more dyes; the result's colors depend on the supplied dyes."
    elif kind == "crafting_special_mapextending":
        add("map")
        add("material", 8)
        identity(0)
        recipe["pattern"] = ["PPP", "PMP", "PPP"]
        recipe["key"] = {"P": game.ingredient(raw["material"]), "M": game.ingredient(raw["map"])}
        recipe["dynamic"] = True
        recipe["note"] = "Eight paper around one filled map increase its scale. The map must be below maximum scale and must not be an exploration map."
    elif kind == "crafting_special_repairitem":
        damageable = sorted(item for item, c in game.components.items() if "minecraft:max_damage" in c and "minecraft:damage" in c)
        groups.append({"items": damageable, "count": 2, "role": "damaged_items", "sameItem": True})
        identity(0)
        recipe["dynamic"] = True
        recipe["note"] = "Combine two of the same damageable item. Restores their remaining durability plus a 5% bonus; removes ordinary enchantments but keeps curses. Each output matches its input item."
    elif kind == "crafting_special_shielddecoration":
        add("target")
        add("banner")
        recipe["dynamic"] = True
        recipe["note"] = "Applies the banner's color and pattern to a shield without an existing banner pattern."
    elif kind == "crafting_imbue":
        add("source")
        add("material", 8)
        recipe["pattern"] = ["AAA", "ASA", "AAA"]
        recipe["key"] = {"A": game.ingredient(raw["material"]), "S": game.ingredient(raw["source"])}
        recipe["dynamic"] = True
        recipe["note"] = "Eight arrows around one lingering potion produce eight tipped arrows carrying its potion contents."
    else:
        raise ValueError(f"Unhandled recipe serializer: {kind} ({recipe_id})")
    if not groups or not recipe["results"]:
        raise ValueError(f"Unmapped recipe: {recipe_id}")
    return recipe


def build_edges(recipes, items):
    edges = []
    for recipe in recipes:
        for output in recipe["results"]:
            if output["item"] not in items:
                raise ValueError(f"Unknown recipe output: {output}")
        for index, ingredient in enumerate(recipe["ingredients"]):
            if not ingredient["items"] or any(item not in items for item in ingredient["items"]):
                raise ValueError(f"Invalid ingredient in {recipe['id']}")
            for source in ingredient["items"]:
                for output in recipe["results"]:
                    if recipe.get("resultFromIngredient") == index and source != output["item"]:
                        continue
                    target = output["item"]
                    edges.append({"id": f"{recipe['id']}:{index}:{source}>{target}", "source": source, "target": target, "category": "recipe", "type": recipe["type"], "recipeId": recipe["id"], "ingredientIndex": index, "minVersion": recipe["minVersion"], "maxVersion": recipe["maxVersion"], "optional": ingredient.get("optional", False)})
    return edges


def build_graph(version, reports):
    with zipfile.ZipFile(CACHE / "client.jar") as jar:
        game = GameData(jar, reports)
        write_json(CACHE / "items.json", sorted(game.items))
        language = json.loads(jar.read("assets/minecraft/lang/en_us.json"))
        nodes = []
        for item in sorted(game.items):
            slug = item.split(":", 1)[1]
            name_component = game.components[item].get("minecraft:item_name", {})
            key = name_component.get("translate") if isinstance(name_component, dict) else None
            name = language.get(key, name_component.get("text", slug.replace("_", " ").title()) if isinstance(name_component, dict) else str(name_component))
            nodes.append({"id": item, "name": name, "kind": "item", "minVersion": version, "maxVersion": None, "icon": f"assets/icons/{slug}.png"})
        paths = sorted(path for path in jar.namelist() if path.startswith("data/minecraft/recipe/") and path.endswith(".json"))
        recipes = [normalize_recipe("minecraft:" + path.removeprefix("data/minecraft/recipe/").removesuffix(".json"), json.loads(jar.read(path)), game, version) for path in paths]
        from supplemental_recipes import build_supplemental
        recipes.extend(build_supplemental(game.items, game.components, game.resolve_tag, version))
        from category_relations import build_categories
        from mob_relations import build_mobs
        from gathering_relations import build_gathering
        from effect_relations import build_effects
        from interaction_relations import build_interactions
        from plant_relations import build_plants
        from mob_behavior_relations import build_mob_behaviors
        categories = build_categories(game, recipes, version)
        mobs = build_mobs(game, version)
        gathering = build_gathering(game, version, mobs["nodes"])
        effects = build_effects(game, version, mobs["nodes"])
        existing_nodes = nodes + categories["nodes"] + mobs["nodes"] + gathering["nodes"] + effects["nodes"]
        interactions = build_interactions(game, version, existing_nodes)
        plants = build_plants(game, version, existing_nodes)
        mob_behaviors = build_mob_behaviors(game, version, existing_nodes)
        item_edges = build_edges(recipes, game.items)
        additions = [categories, mobs, gathering, effects, interactions, plants, mob_behaviors]
        for node in nodes:
            capabilities = {}
            for part in (effects, interactions):
                capabilities.update(part["coverage"].get("itemCapabilities", {}).get(node["id"], {}))
            if capabilities:
                node["capabilities"] = capabilities
        for part in (effects, interactions):
            part["coverage"]["itemCapabilityCount"] = len(part["coverage"].pop("itemCapabilities", {}))
        graph = {"schemaVersion": 1, "version": version, "versions": [version], "nodes": nodes + [node for part in additions for node in part["nodes"]],
                 "recipes": recipes, "relationships": [record for part in additions for record in part["relationships"]],
                 "edges": item_edges + [edge for part in additions for edge in part["edges"]],
                 "coverage": {"categories": categories["coverage"], "mobs": mobs["coverage"], "gathering": gathering["coverage"],
                              "effects": effects["coverage"], "interactions": interactions["coverage"], "plants": plants["coverage"],
                              "mobBehaviors": mob_behaviors["coverage"]}}
        artwork_sources = b"".join((ROOT / "scripts" / name).read_bytes() for name in ("render_icons.py", "render_blocks.py", "render_mobs.py", "effect_relations.py", "ExportItemGeometry.java", "ExportMobGeometry.java"))
        graph["assetRevision"] = hashlib.sha1(artwork_sources + version.encode()).hexdigest()[:12]
        node_ids = {node["id"] for node in graph["nodes"]}
        record_ids = {record["id"] for record in graph["recipes"] + graph["relationships"]}
        if len(node_ids) != len(graph["nodes"]) or len(record_ids) != len(graph["recipes"]) + len(graph["relationships"]):
            raise ValueError("Duplicate graph node or record IDs")
        edge_ids = set()
        for edge in graph["edges"]:
            if edge["source"] not in node_ids or edge["target"] not in node_ids or edge.get("recipeId", edge.get("relationId")) not in record_ids or edge["id"] in edge_ids:
                raise ValueError(f"Invalid graph edge: {edge['id']}")
            edge_ids.add(edge["id"])
        graph["counts"] = {"items": len(nodes), "nodes": len(graph["nodes"]), "categories": len(categories["nodes"]), "mobs": len(mobs["nodes"]),
                           "blocks": len(gathering["nodes"]), "effects": len(effects["nodes"]), "vanillaRecipeFiles": len(paths), "supplementalRecipes": len(recipes) - len(paths),
                           "recipes": len(recipes), "relationships": len(graph["relationships"]), "itemRecipeEdges": len(item_edges), "edges": len(graph["edges"])}
        return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Rebuild from previously verified cached metadata and jar")
    parser.add_argument("--java", type=Path, help="Java executable matching Mojang's required major version")
    parser.add_argument("--minecraft-dir", type=Path, default=Path(os.environ.get("APPDATA", Path.home())) / ".minecraft")
    args = parser.parse_args()
    version, entry = load_game(args)
    reports = generate_reports(args, version)
    generate_extended_reports(args, version)
    graph = build_graph(version["id"], reports)
    provenance = {"edition": "Java Edition", "version": version["id"], "releaseTime": entry["releaseTime"], "manifestUrl": MANIFEST_URL, "versionMetadataUrl": entry["url"], "clientUrl": version["downloads"]["client"]["url"], "clientSha1": version["downloads"]["client"]["sha1"], "extractedAt": datetime.now(timezone.utc).isoformat(), "itemInventory": "Official net.minecraft.data.Main --reports; minecraft:item registry including air and unobtainable items", "recipeInventory": "Every data/minecraft/recipe/**/*.json in the verified official client jar, plus explicitly labeled workstation transformations", "counts": graph["counts"], "recipeTypes": dict(sorted(Counter(recipe["type"] for recipe in graph["recipes"]).items())), "versionSemantics": "minVersion is the start of this dataset's coverage, not each item's historical introduction. maxVersion is inclusive, null means no known end. Only this release is loaded.", "limitations": ["Item nodes represent registered item ids; potion contents, damage, banner patterns, enchantments and other components are recipe predicates or notes, not separate item nodes.", "A directed edge is an ingredient's participation in the complete recipe, not an assertion that this ingredient alone crafts the output.", "Workstation transformations involving arbitrary components and experience have conditional notes rather than enumerating every possible item stack.", "Fuel, renaming, enchanting-table rolls, loot, drops, trades and world interactions are outside the item-production recipe graph.", "Vanilla only; installed mods and user datapacks are not included."], "sources": [{"title": "Mojang version manifest", "url": MANIFEST_URL}, {"title": "Minecraft Java Edition 26.3 release notes", "url": "https://www.minecraft.net/en-us/article/minecraft-java-edition-26-3"}, {"title": "Data-driven brewing recipes", "url": "https://www.minecraft.net/en-us/article/minecraft-26-3-snapshot-3"}]}
    provenance["coverage"] = graph["coverage"]
    provenance["nodeTypes"] = dict(sorted(Counter(node["kind"] for node in graph["nodes"]).items()))
    provenance["relationshipTypes"] = dict(sorted(Counter(record["type"] for record in graph["relationships"]).items()))
    provenance["limitations"][3] = "Renaming, enchanting-table rolls, villager trading, structures, biomes, chest loot and a complete world simulation are not included. Game-derived loot, gathering, status effects and documented item/mob interactions are included."
    write_json(ROOT / "data" / "graph.json", graph)
    write_json(ROOT / "data" / "provenance.json", provenance)
    print(json.dumps(graph["counts"]))


if __name__ == "__main__":
    main()
