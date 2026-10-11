import com.google.gson.Gson;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import net.minecraft.SharedConstants;
import net.minecraft.client.model.geom.*;
import net.minecraft.client.model.geom.builders.LayerDefinition;
import net.minecraft.client.model.object.statue.CopperGolemStatueModel;
import net.minecraft.server.Bootstrap;
import net.minecraft.util.Unit;
import org.joml.*;

// Exports the game's own baked entity geometry; no graphics context is needed.
public class ExportItemGeometry {
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
        for (var child : ((Map<String, ModelPart>) field(part, "children")).entrySet()) {
            visit(child.getValue(), matrix, path + "/" + child.getKey(), faces);
        }
    }

    public static void main(String[] args) throws Exception {
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        Map<ModelLayerLocation, LayerDefinition> roots = LayerDefinitions.createRoots();
        Map<String, Object> result = new TreeMap<>();
        for (String name : List.of("CHEST", "STANDING_BANNER", "STANDING_BANNER_FLAG", "SHIELD",
                "SHULKER_BOX", "CONDUIT_SHELL", "DECORATED_POT_BASE", "DECORATED_POT_SIDES",
                "CREEPER_HEAD", "DRAGON_SKULL", "PIGLIN_HEAD", "PLAYER_HEAD", "SKELETON_SKULL",
                "WITHER_SKELETON_SKULL", "ZOMBIE_HEAD", "COPPER_GOLEM", "COPPER_GOLEM_RUNNING",
                "COPPER_GOLEM_SITTING", "COPPER_GOLEM_STAR")) {
            ModelLayerLocation location = (ModelLayerLocation) ModelLayers.class.getField(name).get(null);
            List<Object> faces = new ArrayList<>();
            ModelPart root = roots.get(location).bakeRoot();
            if (name.startsWith("COPPER_GOLEM")) {
                new CopperGolemStatueModel(root).setupAnim(Unit.INSTANCE);
            }
            visit(root, new Matrix4f(), "", faces);
            result.put(name, faces);
        }
        Files.writeString(Path.of(args[0]), new Gson().toJson(result));
        System.out.println("Exported " + result.size() + " official special model meshes");
    }
}
