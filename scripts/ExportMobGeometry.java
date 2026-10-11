import com.google.gson.Gson;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import net.minecraft.SharedConstants;
import net.minecraft.client.model.geom.*;
import net.minecraft.client.model.geom.builders.LayerDefinition;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.entity.*;
import org.joml.*;

// Classify every registered entity from the game's generic class, then bake its real mesh.
public class ExportMobGeometry {
    static Object field(Object object, String name) throws Exception {
        Field field = object.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(object);
    }
    @SuppressWarnings("unchecked")
    static void visit(ModelPart part, Matrix4f parent, String path, List<Object> faces) throws Exception {
        Matrix4f matrix = new Matrix4f(parent).translate(part.x, part.y, part.z)
            .rotateZ(part.zRot).rotateY(part.yRot).rotateX(part.xRot)
            .scale(part.xScale, part.yScale, part.zScale);
        if (part.visible && !part.skipDraw) {
            for (ModelPart.Cube cube : (List<ModelPart.Cube>) field(part, "cubes")) {
                for (ModelPart.Polygon face : cube.polygons) {
                    List<Object> vertices = new ArrayList<>();
                    for (ModelPart.Vertex vertex : face.vertices()) {
                        Vector3f position = matrix.transformPosition(new Vector3f(vertex.x(), vertex.y(), vertex.z()));
                        vertices.add(new float[]{position.x, position.y, position.z, vertex.u(), vertex.v()});
                    }
                    Vector3f normal = matrix.transformDirection(new Vector3f(face.normal())).normalize();
                    faces.add(Map.of("vertices", vertices, "normal", new float[]{normal.x, normal.y, normal.z}, "part", path));
                }
            }
        }
        for (var child : ((Map<String, ModelPart>) field(part, "children")).entrySet()) {
            visit(child.getValue(), matrix, path + "/" + child.getKey(), faces);
        }
    }
    public static void main(String[] args) throws Exception {
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        var roots = LayerDefinitions.createRoots();
        Map<EntityType<?>,Class<?>> classes = new IdentityHashMap<>();
        for (Field field : EntityTypes.class.getFields()) {
            if (field.getGenericType() instanceof ParameterizedType type && type.getRawType() == EntityType.class) {
                classes.put((EntityType<?>) field.get(null), (Class<?>) type.getActualTypeArguments()[0]);
            }
        }
        Map<String,String> aliases = Map.of("camel_husk", "CAMEL", "pufferfish", "PUFFERFISH_SMALL", "tropical_fish", "TROPICAL_FISH_SMALL");
        Map<String,Object> entities = new TreeMap<>();
        Map<String,Object> meshes = new TreeMap<>();
        Map<String,Object> overlays = new TreeMap<>();
        for (String layer : List.of("SHEEP_WOOL", "BOGGED_OUTER_LAYER", "STRAY_OUTER_LAYER", "DROWNED_OUTER_LAYER", "SLIME_OUTER", "SULFUR_CUBE_INNER", "BREEZE_WIND", "LLAMA_DECOR")) {
            ModelLayerLocation location = (ModelLayerLocation) ModelLayers.class.getField(layer).get(null);
            List<Object> faces = new ArrayList<>();
            visit(roots.get(location).bakeRoot(), new Matrix4f(), "", faces);
            overlays.put(layer, faces);
        }
        for (var type : BuiltInRegistries.ENTITY_TYPE) {
            Class<?> cls = classes.get(type);
            if (cls == null) throw new IllegalStateException("Unclassified registry entity " + EntityType.getKey(type));
            String id = EntityType.getKey(type).toString();
            Map<String,Object> entry = new LinkedHashMap<>();
            boolean mob = Mob.class.isAssignableFrom(cls);
            entry.put("class", cls.getName());
            entry.put("mob", mob);
            entry.put("lootTable", type.getDefaultLootTable().map(key -> key.identifier().toString()).orElse(null));
            if (mob) {
                String name = id.substring(id.indexOf(':') + 1);
                String layer = aliases.getOrDefault(name, name.toUpperCase(Locale.ROOT));
                ModelLayerLocation location = (ModelLayerLocation) ModelLayers.class.getField(layer).get(null);
                List<Object> faces = new ArrayList<>();
                visit(roots.get(location).bakeRoot(), new Matrix4f(), "", faces);
                entry.put("layer", layer);
                meshes.put(id, faces);
            }
            entities.put(id, entry);
        }
        Path client = Path.of(args.length > 1 ? args[1] : ".cache/client.jar");
        String clientSha1 = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(Files.readAllBytes(client)));
        Files.writeString(Path.of(args[0]), new Gson().toJson(Map.of("version", SharedConstants.getCurrentVersion().id(), "clientSha1", clientSha1, "entities", entities, "meshes", meshes, "overlays", overlays, "defaultEquipmentDropChance", DropChances.DEFAULT.byEquipment(EquipmentSlot.MAINHAND))));
        System.out.println("Classified " + entities.size() + " registry entities and baked " + meshes.size() + " real mob meshes");
    }
}
