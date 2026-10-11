"""Bake crisp inventory icons from the official Java client, with no live 3D renderers.

Requires Pillow and NumPy. Special entity meshes come from ExportItemGeometry.java.
"""
import argparse
from collections import Counter
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import re
import zipfile

import numpy as np
from PIL import Image

SIZE = 64
DYE = {
    "white": 0xF9FFFE, "orange": 0xF9801D, "magenta": 0xC74EBD, "light_blue": 0x3AB3DA,
    "yellow": 0xFED83D, "lime": 0x80C71F, "pink": 0xF38BAA, "gray": 0x474F52,
    "light_gray": 0x9D9D97, "cyan": 0x169C9C, "purple": 0x8932B8, "blue": 0x3C44AA,
    "brown": 0x835432, "green": 0x5E7C16, "red": 0xB02E26, "black": 0x1D1D21,
}


def rgb(color):
    return np.array([(color >> 16) & 255, (color >> 8) & 255, color & 255]) / 255


def rotation(angles):
    x, y, z = np.radians(angles)
    sx, sy, sz = np.sin([x, y, z])
    cx, cy, cz = np.cos([x, y, z])
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rx @ ry @ rz


def quaternion(values):
    x, y, z, w = values
    return np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ])


def definition_transform(value):
    matrix = np.eye(4)
    matrix[:3, :3] = (quaternion(value.get("left_rotation", [0, 0, 0, 1]))
                       @ np.diag(value.get("scale", [1, 1, 1]))
                       @ quaternion(value.get("right_rotation", [0, 0, 0, 1])))
    matrix[:3, 3] = np.array(value.get("translation", [0, 0, 0])) * 16
    return matrix


def apply_transform(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def resource(value, directory, suffix):
    namespace, path = value.split(":", 1) if ":" in value else ("minecraft", value)
    return f"assets/{namespace}/{directory}/{path}{suffix}"


class Renderer:
    def __init__(self, jar, special):
        self.jar = zipfile.ZipFile(jar)
        self.special = json.loads(Path(special).read_text(encoding="utf-8"))
        self.used_textures = set()

    @lru_cache(maxsize=None)
    def load_json(self, path):
        return json.loads(self.jar.read(path))

    @lru_cache(maxsize=None)
    def model(self, name):
        source = self.load_json(resource(name, "models", ".json"))
        parent = source.get("parent")
        if parent in ("builtin/generated", "minecraft:builtin/generated"):
            result = {"generated": True}
        elif parent:
            result = dict(self.model(parent))
        else:
            result = {}
        for key, value in source.items():
            result[key] = {**result.get(key, {}), **value} if key in ("textures", "display") else value
        return result

    @lru_cache(maxsize=None)
    def texture(self, name):
        path = resource(name, "textures", ".png")
        self.used_textures.add(path)
        image = Image.open(BytesIO(self.jar.read(path))).convert("RGBA")
        metadata = path + ".mcmeta"
        if metadata in self.jar.namelist():
            animation = self.load_json(metadata).get("animation", {})
            width = animation.get("width", min(image.size))
            height = animation.get("height", min(image.size))
            frame = animation.get("frames", [0])[0]
            frame = frame.get("index", 0) if isinstance(frame, dict) else frame
            columns = image.width // width
            x, y = frame % columns * width, frame // columns * height
            image = image.crop((x, y, x + width, y + height))
        return np.array(image)

    def resolve_texture(self, model, name):
        visited = set()
        if isinstance(name, str) and name in model.get("textures", {}):
            name = "#" + name
        while isinstance(name, str) and name.startswith("#"):
            if name in visited:
                raise ValueError(f"Circular texture reference {name}")
            visited.add(name)
            name = model["textures"][name[1:]]
        return name["sprite"] if isinstance(name, dict) else name

    def tint(self, tint):
        if tint["type"] == "minecraft:grass":
            temperature = tint.get("temperature", 0.5)
            rainfall = tint.get("downfall", 1) * temperature
            colormap = self.texture("minecraft:colormap/grass")
            return colormap[int((1-rainfall)*255), int((1-temperature)*255), :3] / 255
        return rgb(tint.get("value", tint.get("default", 0xFFFFFF)))

    def select(self, value, inherited=None):
        transform = (inherited if inherited is not None else np.eye(4)) @ definition_transform(value.get("transformation", {}))
        kind = value["type"]
        if kind == "minecraft:condition":
            return self.select(value["on_false"], transform)
        if kind == "minecraft:select":
            if value["property"] == "minecraft:display_context":
                for case in value.get("cases", []):
                    when = case["when"] if isinstance(case["when"], list) else [case["when"]]
                    if "gui" in when:
                        return self.select(case["model"], transform)
            return self.select(value["fallback"], transform)
        if kind == "minecraft:range_dispatch":
            selected = value.get("fallback", value["entries"][0]["model"])
            for entry in value["entries"]:
                if entry["threshold"] <= 0:
                    selected = entry["model"]
            return self.select(selected, transform)
        if kind == "minecraft:composite":
            return [entry for child in value["models"] for entry in self.select(child, transform)]
        if kind in ("minecraft:model", "minecraft:special"):
            return [(value, transform)]
        if kind == "minecraft:empty":
            return []
        raise ValueError(f"Unsupported item definition {kind}")

    def special_faces(self, value):
        specification = value["model"]
        kind = specification["type"].split(":")[-1]
        tint = np.ones(3)
        if kind == "chest":
            parts = [("CHEST", "entity/chest/" + specification["texture"].split(":")[-1])]
        elif kind == "shulker_box":
            parts = [("SHULKER_BOX", "entity/shulker/" + specification["texture"].split(":")[-1])]
        elif kind == "banner":
            parts = [("STANDING_BANNER", "entity/banner/banner_base"),
                     ("STANDING_BANNER_FLAG", "entity/banner/base")]
            tint = rgb(DYE[specification["color"]])
        elif kind == "shield":
            parts = [("SHIELD", "entity/shield/shield_base_nopattern")]
        elif kind == "conduit":
            parts = [("CONDUIT_SHELL", "entity/conduit/base")]
        elif kind == "decorated_pot":
            parts = [("DECORATED_POT_BASE", "entity/decorated_pot/decorated_pot_base"),
                     ("DECORATED_POT_SIDES", "entity/decorated_pot/decorated_pot_side")]
        elif kind == "copper_golem_statue":
            pose = specification.get("pose", "standing")
            mesh = "COPPER_GOLEM" + ("_" + pose.upper() if pose != "standing" else "")
            parts = [(mesh, specification["texture"].removeprefix("minecraft:textures/").removesuffix(".png"))]
        elif kind in ("head", "player_head"):
            head = specification.get("kind", "player")
            mesh, texture = {
                "player": ("PLAYER_HEAD", "entity/player/wide/steve"),
                "zombie": ("ZOMBIE_HEAD", "entity/zombie/zombie"),
                "skeleton": ("SKELETON_SKULL", "entity/skeleton/skeleton"),
                "wither_skeleton": ("WITHER_SKELETON_SKULL", "entity/skeleton/wither_skeleton"),
                "creeper": ("CREEPER_HEAD", "entity/creeper/creeper"),
                "piglin": ("PIGLIN_HEAD", "entity/piglin/piglin"),
                "dragon": ("DRAGON_SKULL", "entity/enderdragon/dragon"),
            }[head]
            parts = [(mesh, texture)]
        else:
            raise ValueError(f"Unsupported GUI special renderer {kind}")
        for mesh, texture in parts:
            pixels = self.texture(texture)
            for face in self.special[mesh]:
                vertices = np.array(face["vertices"])
                color = tint if mesh == "STANDING_BANNER_FLAG" else np.ones(3)
                yield vertices[:, :3], vertices[:, 3:5], np.array(face["normal"]), pixels, color

    def block_faces(self, model, tints):
        for element in model.get("elements", []):
            x0, y0, z0 = element["from"]
            x1, y1, z1 = element["to"]
            corners = {
                "south": [[x0,y1,z1], [x1,y1,z1], [x1,y0,z1], [x0,y0,z1]],
                "north": [[x1,y1,z0], [x0,y1,z0], [x0,y0,z0], [x1,y0,z0]],
                "east": [[x1,y1,z1], [x1,y1,z0], [x1,y0,z0], [x1,y0,z1]],
                "west": [[x0,y1,z0], [x0,y1,z1], [x0,y0,z1], [x0,y0,z0]],
                "up": [[x0,y1,z0], [x1,y1,z0], [x1,y1,z1], [x0,y1,z1]],
                "down": [[x0,y0,z1], [x1,y0,z1], [x1,y0,z0], [x0,y0,z0]],
            }
            normals = {"east": [1,0,0], "west": [-1,0,0], "up": [0,1,0], "down": [0,-1,0], "south": [0,0,1], "north": [0,0,-1]}
            default_uv = {
                "down": [x0,16-z1,x1,16-z0], "up": [x0,z0,x1,z1],
                "north": [16-x1,16-y1,16-x0,16-y0], "south": [x0,16-y1,x1,16-y0],
                "west": [z0,16-y1,z1,16-y0], "east": [16-z1,16-y1,16-z0,16-y0],
            }
            for direction, face in element["faces"].items():
                points = np.array(corners[direction], dtype=float)
                normal = np.array(normals[direction], dtype=float)
                if "rotation" in element:
                    local = element["rotation"]
                    axis = "xyz".index(local["axis"])
                    angles = [0, 0, 0]
                    angles[axis] = local["angle"]
                    matrix = rotation(angles)
                    if local.get("rescale"):
                        scale = np.full(3, 1 / np.cos(np.radians(local["angle"])))
                        scale[axis] = 1
                        matrix = np.diag(scale) @ matrix
                    origin = np.array(local["origin"])
                    points = (points - origin) @ matrix.T + origin
                    normal = matrix @ normal
                u0, v0, u1, v1 = face.get("uv", default_uv[direction])
                uv = np.array([[u0,v0], [u1,v0], [u1,v1], [u0,v1]], dtype=float) / 16
                uv = np.roll(uv, -face.get("rotation", 0)//90, axis=0)
                tint_index = face.get("tintindex", -1)
                color = tints[tint_index] if 0 <= tint_index < len(tints) else np.ones(3)
                texture = self.texture(self.resolve_texture(model, face["texture"]))
                yield points, uv, normal, texture, color

    def generated(self, model, tints):
        image = Image.new("RGBA", (SIZE, SIZE))
        for i in range(5):
            key = f"layer{i}"
            if key not in model.get("textures", {}):
                continue
            pixels = self.texture(self.resolve_texture(model, model["textures"][key])).copy()
            if i < len(tints):
                pixels[:, :, :3] = np.rint(pixels[:, :, :3] * tints[i]).astype(np.uint8)
            layer = Image.fromarray(pixels).resize((SIZE, SIZE), Image.Resampling.NEAREST)
            image.alpha_composite(layer)
        translation = model.get("display", {}).get("gui", {}).get("translation", [0, 0, 0])
        if any(translation):
            shifted = Image.new("RGBA", (SIZE, SIZE))
            shifted.paste(image, (round(translation[0]*SIZE/16), -round(translation[1]*SIZE/16)))
            image = shifted
        return image

    def render(self, item):
        entries = self.select(self.load_json(resource(item, "items", ".json"))["model"])
        output = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
        depth = np.full((SIZE, SIZE), -np.inf)
        types = set()
        for value, definition_matrix in entries:
            model = self.model(value.get("base", value.get("model")))
            tints = [self.tint(tint) for tint in value.get("tints", [])]
            if model.get("generated"):
                types.add("texture")
                output = np.array(Image.alpha_composite(Image.fromarray(output), self.generated(model, tints)))
                continue
            if value["type"] == "minecraft:special":
                types.add("special_model")
                faces = self.special_faces(value)
            else:
                types.add("block_model")
                faces = self.block_faces(model, tints)
            gui = model.get("display", {}).get("gui", {})
            matrix = rotation(gui.get("rotation", [0, 0, 0])) @ np.diag(gui.get("scale", [1, 1, 1]))
            translation = np.array(gui.get("translation", [0, 0, 0]))
            for points, uv, normal, texture, color in faces:
                points = (apply_transform(points, definition_matrix) - 8) @ matrix.T + translation
                normal = matrix @ definition_matrix[:3, :3] @ normal
                normal /= np.linalg.norm(normal)
                if normal[2] < -1e-6:
                    continue
                shade = 1 if model.get("gui_light") == "front" else 0.6 + 0.4 * max(0, normal[1])
                projected = np.column_stack((SIZE/2 + points[:, 0]*SIZE/16, SIZE/2 - points[:, 1]*SIZE/16, points[:, 2]))
                for indices in ([0, 1, 2], [0, 2, 3]):
                    raster_triangle(output, depth, projected[indices], uv[indices], texture, color * shade)
        return Image.fromarray(output), "+".join(sorted(types)) or "empty"


def raster_triangle(output, depth, points, uv, texture, color):
    left, top = np.maximum(np.floor(points[:, :2].min(axis=0)).astype(int), 0)
    right, bottom = np.minimum(np.ceil(points[:, :2].max(axis=0)).astype(int), SIZE-1)
    if left > right or top > bottom:
        return
    a, b, c = points
    determinant = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
    if abs(determinant) < 1e-8:
        return
    x, y = np.meshgrid(np.arange(left, right+1)+0.5, np.arange(top, bottom+1)+0.5)
    w0 = ((b[1]-c[1])*(x-c[0]) + (c[0]-b[0])*(y-c[1]))/determinant
    w1 = ((c[1]-a[1])*(x-c[0]) + (a[0]-c[0])*(y-c[1]))/determinant
    weights = np.stack((w0, w1, 1-w0-w1), axis=-1)
    z = weights @ points[:, 2]
    coords = weights @ uv
    tx = np.clip(np.floor(coords[:, :, 0]*texture.shape[1]).astype(int), 0, texture.shape[1]-1)
    ty = np.clip(np.floor(coords[:, :, 1]*texture.shape[0]).astype(int), 0, texture.shape[0]-1)
    pixels = texture[ty, tx].copy()
    pixels[:, :, :3] = np.rint(pixels[:, :, :3]*color).astype(np.uint8)
    section = output[top:bottom+1, left:right+1]
    zsection = depth[top:bottom+1, left:right+1]
    visible = np.all(weights >= -1e-6, axis=-1) & (z >= zsection-1e-5) & (pixels[:, :, 3] > 0)
    alpha = pixels[:, :, 3:4]/255
    destination_alpha = section[:, :, 3:4]/255
    combined_alpha = alpha + destination_alpha*(1-alpha)
    blended = np.rint((pixels[:, :, :3]*alpha + section[:, :, :3]*destination_alpha*(1-alpha))
                       / np.maximum(combined_alpha, 1e-8)).astype(np.uint8)
    section[visible, :3] = blended[visible]
    section[visible, 3] = np.rint(combined_alpha[:, :, 0][visible]*255).astype(np.uint8)
    zsection[visible] = z[visible]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default=".cache/client.jar")
    parser.add_argument("--items", default=".cache/items.json")
    parser.add_argument("--special-models", default=".cache/special-models.json")
    parser.add_argument("--output", default="assets/icons")
    args = parser.parse_args()
    renderer = Renderer(args.client, args.special_models)
    ids = json.loads(Path(args.items).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    records = {}
    for item in ids:
        if not re.fullmatch(r"minecraft:[a-z0-9_]+", item):
            raise ValueError(f"Unsafe icon identifier: {item}")
        image, kind = renderer.render(item)
        if image.getbbox() is None and item != "minecraft:air":
            raise ValueError(f"Empty icon for visible item: {item}")
        image.save(output / (item.split(":")[1] + ".png"))
        records[item] = kind
        counts[kind] += 1
    report = {
        "version": json.loads(Path(".cache/version.json").read_text(encoding="utf-8"))["id"],
        "registeredItems": len(ids), "iconsWritten": len(records), "missingIcons": [],
        "renderMethods": dict(counts), "sourceTexturesUsed": len(renderer.used_textures),
        "approximations": [
            "Software rasterizer uses nearest texel sampling and simplified inventory lighting.",
            "Icons use default item components and static first animation frames; dynamic poses, enchantment glint, banner patterns, skins, and custom item components are not animated.",
            "Player head uses the bundled Steve skin; Air has a correctly transparent icon.",
        ],
        "items": records,
    }
    (output.parent / "icon-coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, indent=2))


if __name__ == "__main__":
    main()
