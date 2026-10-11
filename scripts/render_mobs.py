"""Render every real Mob mesh with official entity textures; no spawn-egg proxies."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
from render_icons import SIZE, raster_triangle, rotation

ROOT = Path(__file__).resolve().parents[1]
# Explicit representative skins only where the game has variants or shared folders.
SKINS = {
    "axolotl": "axolotl/axolotl_lucy", "bogged": "skeleton/bogged", "camel_husk": "camel/camel_husk",
    "cat": "cat/cat_tabby", "cave_spider": "spider/cave_spider", "chicken": "chicken/chicken_temperate",
    "cod": "fish/cod", "cow": "cow/cow_temperate", "donkey": "horse/donkey", "drowned": "zombie/drowned",
    "elder_guardian": "guardian/guardian_elder", "ender_dragon": "enderdragon/dragon", "evoker": "illager/evoker",
    "frog": "frog/frog_temperate", "giant": "zombie/zombie", "glow_squid": "squid/glow_squid",
    "happy_ghast": "ghast/happy_ghast", "horse": "horse/horse_brown", "husk": "zombie/husk",
    "illusioner": "illager/illusioner", "llama": "llama/llama_creamy", "magma_cube": "slime/magmacube",
    "mooshroom": "cow/mooshroom_red", "mule": "horse/mule", "ocelot": "cat/ocelot",
    "parched": "skeleton/parched", "parrot": "parrot/parrot_red_blue", "pig": "pig/pig_temperate",
    "piglin_brute": "piglin/piglin_brute", "pillager": "illager/pillager", "polar_bear": "bear/polarbear",
    "pufferfish": "fish/pufferfish", "rabbit": "rabbit/rabbit_brown", "ravager": "illager/ravager",
    "salmon": "fish/salmon", "skeleton_horse": "horse/horse_skeleton", "stray": "skeleton/stray",
    "sulfur_cube": "sulfur_cube/sulfur_cube_outer", "trader_llama": "llama/llama_creamy",
    "tropical_fish": "fish/tropical_a", "vex": "illager/vex", "vindicator": "illager/vindicator",
    "wither_skeleton": "skeleton/wither_skeleton", "zoglin": "hoglin/zoglin",
    "zombie_horse": "horse/horse_zombie", "zombie_nautilus": "nautilus/zombie_nautilus",
    "zombified_piglin": "piglin/zombified_piglin",
}
OVERLAYS = {
    "sheep": ("SHEEP_WOOL", "sheep/sheep_wool"), "bogged": ("BOGGED_OUTER_LAYER", "skeleton/bogged_overlay"),
    "stray": ("STRAY_OUTER_LAYER", "skeleton/stray_overlay"), "drowned": ("DROWNED_OUTER_LAYER", "zombie/drowned_outer_layer"),
    "slime": ("SLIME_OUTER", "slime/slime"), "sulfur_cube": ("SULFUR_CUBE_INNER", "sulfur_cube/sulfur_cube_inner"),
    "breeze": ("BREEZE_WIND", "breeze/breeze_wind"), "trader_llama": ("LLAMA_DECOR", "equipment/llama_body/trader_llama"),
}


def render_mob(jar, report, entity):
    slug = entity.split(":")[1]
    texture_name = SKINS.get(slug, slug + "/" + slug)
    surfaces = [(report["meshes"][entity], texture_name)]
    if slug in OVERLAYS:
        layer, texture = OVERLAYS[slug]
        surfaces.append((report["overlays"][layer], texture))
    faces = []
    # Minecraft entity geometry points down; convert to the icon renderer's up axis.
    matrix = rotation([8, 152, 0]) @ np.diag([1, -1, 1])
    for mesh, texture in surfaces:
        texture = np.array(Image.open(BytesIO(jar.read("assets/minecraft/textures/entity/" + texture + ".png"))).convert("RGBA"))
        for face in mesh:
            vertices = np.array(face["vertices"], dtype=float)
            points = vertices[:, :3] @ matrix.T
            normal = matrix @ np.array(face["normal"])
            faces.append((points, vertices[:, 3:], normal, texture))
    bounds = np.concatenate([face[0] for face in faces])
    center = (bounds.min(axis=0) + bounds.max(axis=0)) / 2
    scale = (SIZE - 8) / max(np.ptp(bounds[:, 0]), np.ptp(bounds[:, 1]))
    output = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    depth = np.full((SIZE, SIZE), -np.inf)
    for points, uv, normal, texture in sorted(faces, key=lambda face: face[0][:, 2].mean()):
        if normal[2] < -1e-6:
            continue
        points = (points - center) * scale
        projected = np.column_stack((SIZE / 2 + points[:, 0], SIZE / 2 - points[:, 1], points[:, 2]))
        shade = 0.72 + 0.28 * max(0, normal[1])
        for indices in ([0, 1, 2], [0, 2, 3]):
            raster_triangle(output, depth, projected[indices], uv[indices], texture, np.full(3, shade))
    image = Image.fromarray(output)
    if image.getbbox() is None:
        raise ValueError("Empty real mob model " + entity)
    return image, texture_name


def main():
    report = json.loads((ROOT / ".cache/mob-models.json").read_text(encoding="utf-8"))
    client = ROOT / ".cache/client.jar"
    version = json.loads((ROOT / ".cache/version.json").read_text(encoding="utf-8"))["id"]
    if report.get("version") != version or report.get("clientSha1") != hashlib.sha1(client.read_bytes()).hexdigest():
        raise ValueError("Mob geometry cache version/client SHA1 mismatch; regenerate ExportMobGeometry.java")
    output = ROOT / "assets/mobs"
    output.mkdir(parents=True, exist_ok=True)
    icons = {}
    with zipfile.ZipFile(ROOT / ".cache/client.jar") as jar:
        for entity in report["meshes"]:
            image, texture = render_mob(jar, report, entity)
            image.save(output / (entity.split(":")[1] + ".png"))
            icons[entity] = {"method": "official_mob_model", "layer": report["entities"][entity]["layer"], "texture": "assets/minecraft/textures/entity/" + texture + ".png", "viewRotation": [8, 152, 0]}
    (output / "coverage.json").write_text(json.dumps({"version": version, "clientSha1": report["clientSha1"], "icons": icons, "count": len(icons), "limitations": ["Static default baked pose, representative adult skin and simplified lighting; equipment, animation, every variant and some extra render layers are omitted."]}, indent=2) + "\n", encoding="utf-8")
    print(f"Rendered {len(icons)} real mob icons from game meshes and textures")


if __name__ == "__main__":
    main()
