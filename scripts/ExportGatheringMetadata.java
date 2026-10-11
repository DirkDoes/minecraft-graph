import com.google.gson.Gson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import net.minecraft.SharedConstants;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.level.block.SuspiciousEffectHolder;

// Use the game's item mapping, including blocks that have no item and map to air.
public class ExportGatheringMetadata {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass the output JSON path");
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        Map<String, String> blockItems = new TreeMap<>();
        Map<String, List<Object>> stewIngredients = new TreeMap<>();
        for (var block : BuiltInRegistries.BLOCK) {
            String blockId = BuiltInRegistries.BLOCK.getKey(block).toString();
            String itemId = BuiltInRegistries.ITEM.getKey(block.asItem()).toString();
            blockItems.put(blockId, itemId);
            if (block instanceof SuspiciousEffectHolder holder && !itemId.equals("minecraft:air")) {
                List<Object> effects = new ArrayList<>();
                for (var effect : holder.getSuspiciousEffects().effects()) {
                    effects.add(Map.of("id", BuiltInRegistries.MOB_EFFECT.getKey(effect.effect().value()).toString(),
                                       "duration", effect.duration()));
                }
                stewIngredients.put(itemId, effects);
            }
        }
        if (blockItems.size() != BuiltInRegistries.BLOCK.keySet().size() || stewIngredients.isEmpty()) {
            throw new IllegalStateException("Incomplete gathering metadata export");
        }
        Map<String, Object> result = Map.of("version", SharedConstants.getCurrentVersion().name(),
                                            "blockItems", blockItems, "suspiciousStewIngredients", stewIngredients);
        Files.writeString(Path.of(args[0]), new Gson().toJson(result));
        System.out.println("Exported " + blockItems.size() + " block mappings and " + stewIngredients.size() + " suspicious stew ingredients");
    }
}
