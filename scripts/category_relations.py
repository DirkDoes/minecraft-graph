"""Expose official item tags as categories without replacing item recipe edges."""


def build_categories(game, recipes, version):
    bounds = {"minVersion": version, "maxVersion": None}
    resolved = {tag: game.resolve_tag(tag) for tag in sorted(game.tags)}
    resolved = {tag: members for tag, members in resolved.items() if members}
    nodes, relationships, edges = [], [], []

    for tag, members in resolved.items():
        node_id = f"tag:{tag}"
        label = tag.split(":", 1)[1].replace("_", " ").replace("/", " / ").title()
        direct_items = [value if isinstance(value, str) else value["id"] for value in game.tags[tag]["values"]]
        representative = next((item for item in direct_items if item in members), members[0])
        nodes.append({"id": node_id, "name": label, "kind": "category", "subkind": "item_tag", "tag": tag,
                      "memberCount": len(members), "icon": f"assets/icons/{representative.split(':', 1)[1]}.png",
                      "source": "vanilla_item_tag", **bounds})
        relation_id = f"membership:{tag}"
        relationships.append({"id": relation_id, "name": f"Belongs to {label}", "category": "membership", "type": "belongs_to",
                              "inputs": [{"nodeId": member} for member in members], "outputs": [{"nodeId": node_id}],
                              "tag": tag, "raw": game.tags[tag], "source": "vanilla_item_tag",
                              "note": f"Membership in the official item tag #{tag}; nested tags are resolved by the game data.", **bounds})
        for member in members:
            edges.append({"id": f"{relation_id}:{member}", "source": member, "target": node_id,
                          "category": "membership", "type": "belongs_to", "relationId": relation_id, **bounds})

        nested = set()
        for value in game.tags[tag]["values"]:
            value = value if isinstance(value, str) else value["id"]
            if value.startswith("#") and value[1:] in resolved:
                nested.add(value[1:])
        if nested:
            relation_id = f"tag_contains:{tag}"
            relationships.append({"id": relation_id, "name": f"Included in {label}", "category": "membership", "type": "tag_contains",
                                  "inputs": [{"nodeId": f"tag:{child}"} for child in sorted(nested)], "outputs": [{"nodeId": node_id}],
                                  "tag": tag, "source": "vanilla_item_tag",
                                  "note": "Direct nested item-tag references; each child tag is included in this parent tag.", **bounds})
            for child in sorted(nested):
                edges.append({"id": f"{relation_id}:{child}", "source": f"tag:{child}", "target": node_id,
                              "category": "membership", "type": "tag_contains", "relationId": relation_id, **bounds})

    ingredient_count = 0
    for recipe in recipes:
        for index, ingredient in enumerate(recipe["ingredients"]):
            tag = ingredient.get("tag")
            if not tag:
                continue
            if tag not in resolved or not set(ingredient["items"]).issubset(resolved[tag]):
                raise ValueError(f"Invalid tagged ingredient {tag} in {recipe['id']}")
            ingredient_count += 1
            for output in recipe["results"]:
                identity = recipe.get("resultFromIngredient") == index
                if identity and output["item"] not in ingredient["items"]:
                    continue
                edge = {"id": f"{recipe['id']}:{index}:tag:{tag}>{output['item']}", "source": f"tag:{tag}", "target": output["item"],
                        "category": "recipe", "type": recipe["type"], "recipeId": recipe["id"], "ingredientIndex": index,
                        "optional": ingredient.get("optional", False), "minVersion": recipe["minVersion"], "maxVersion": recipe["maxVersion"]}
                if identity:
                    # The chosen member stays the same item; the category is not interchangeable after selection.
                    edge["requiredInputItem"] = output["item"]
                edges.append(edge)

    return {"nodes": nodes, "relationships": relationships, "edges": edges,
            "coverage": {"source": "Every nonempty official data/minecraft/tags/item JSON, with recursively resolved members and direct nested tag references",
                         "officialItemTags": len(game.tags), "categoryNodes": len(nodes),
                         "membershipEdges": sum(edge["type"] == "belongs_to" for edge in edges),
                         "nestedTagEdges": sum(edge["type"] == "tag_contains" for edge in edges),
                         "taggedRecipeIngredients": ingredient_count,
                         "categoryRecipeEdges": sum(edge["category"] == "recipe" for edge in edges)}}
