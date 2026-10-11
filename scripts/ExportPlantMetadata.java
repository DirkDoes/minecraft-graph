import com.google.gson.Gson;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.TreeMap;
import net.minecraft.SharedConstants;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.level.ItemLike;
import net.minecraft.world.level.block.BonemealableBlock;
import net.minecraft.world.level.block.CropBlock;
import net.minecraft.world.level.block.StemBlock;
import net.minecraft.world.level.block.PitcherCropBlock;

public class ExportPlantMetadata {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass the output JSON path");
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        Map<String, Object> bonemealable = new TreeMap<>(), crops = new TreeMap<>(), stems = new TreeMap<>();
        Method seedMethod = CropBlock.class.getDeclaredMethod("getBaseSeedId");
        seedMethod.setAccessible(true);
        Field stemSeed = StemBlock.class.getDeclaredField("seed"), stemFruit = StemBlock.class.getDeclaredField("fruit");
        stemSeed.setAccessible(true); stemFruit.setAccessible(true);
        for (var block : BuiltInRegistries.BLOCK) {
            String id = BuiltInRegistries.BLOCK.getKey(block).toString();
            if (block instanceof BonemealableBlock) bonemealable.put(id, block.getClass().getName());
            if (block instanceof CropBlock crop) crops.put(id, Map.of("seed", BuiltInRegistries.ITEM.getKey(((ItemLike) seedMethod.invoke(crop)).asItem()).toString(), "maxAge", crop.getMaxAge(),
                                                                       "matureBlock", BuiltInRegistries.BLOCK.getKey(crop.getStateForAge(crop.getMaxAge()).getBlock()).toString()));
            if (block instanceof PitcherCropBlock) crops.put(id, Map.of("seed", BuiltInRegistries.ITEM.getKey(block.asItem()).toString(), "maxAge", PitcherCropBlock.MAX_AGE, "matureBlock", id));
            if (block instanceof StemBlock stem) stems.put(id, Map.of("seed", ((ResourceKey<?>) stemSeed.get(stem)).identifier().toString(), "fruit", ((ResourceKey<?>) stemFruit.get(stem)).identifier().toString()));
        }
        if (bonemealable.isEmpty() || crops.isEmpty() || stems.size() != 2) throw new IllegalStateException("Incomplete plant registry metadata");
        String sha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(Files.readAllBytes(Path.of(".cache/client.jar"))));
        Files.writeString(Path.of(args[0]), new Gson().toJson(Map.of("version", SharedConstants.getCurrentVersion().id(), "clientSha1", sha, "bonemealable", bonemealable, "crops", crops, "stems", stems)));
        System.out.println("Exported " + bonemealable.size() + " bonemealable blocks, " + crops.size() + " crops and " + stems.size() + " stems");
    }
}
