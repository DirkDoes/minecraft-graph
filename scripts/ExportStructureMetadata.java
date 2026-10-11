import com.google.gson.Gson;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import net.minecraft.SharedConstants;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.trialspawner.TrialSpawnerConfig;
import net.minecraft.world.level.storage.loot.BuiltInLootTables;
import net.minecraft.world.level.levelgen.structure.templatesystem.BlackstoneReplaceProcessor;

public class ExportStructureMetadata {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass the output JSON path");
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        Map<String, String> blocks = new TreeMap<>(), loot = new TreeMap<>();
        for (Field field : Blocks.class.getDeclaredFields()) {
            if (Modifier.isStatic(field.getModifiers()) && Block.class.isAssignableFrom(field.getType())) {
                field.setAccessible(true);
                blocks.put(field.getName(), BuiltInRegistries.BLOCK.getKey((Block) field.get(null)).toString());
            }
        }
        for (Field field : BuiltInLootTables.class.getDeclaredFields()) {
            if (Modifier.isStatic(field.getModifiers()) && ResourceKey.class.isAssignableFrom(field.getType())) {
                field.setAccessible(true);
                loot.put(field.getName(), ((ResourceKey<?>) field.get(null)).identifier().toString());
            }
        }
        Map<String, Object> templates = new TreeMap<>();
        for (String name : List.of("ShipwreckPieces", "IglooPieces", "OceanRuinPieces", "NetherFossilPieces")) {
            Class<?> type = Class.forName("net.minecraft.world.level.levelgen.structure.structures." + name);
            Map<String, Object> fields = new TreeMap<>();
            for (Field field : type.getDeclaredFields()) {
                if (!Modifier.isStatic(field.getModifiers())) continue;
                field.setAccessible(true);
                Object value = field.get(null);
                if (value instanceof Identifier id) fields.put(field.getName(), id.toString());
                if (value instanceof Identifier[] ids) {
                    List<String> output = new ArrayList<>();
                    for (Identifier id : ids) output.add(id.toString());
                    fields.put(field.getName(), output);
                }
            }
            templates.put(name, fields);
        }
        String sha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(Files.readAllBytes(Path.of(".cache/client.jar"))));
        List<Object> trialLoot = new ArrayList<>();
        for (var entry : TrialSpawnerConfig.DEFAULT.lootTablesToEject().unwrap()) {
            trialLoot.add(Map.of("data", entry.value().identifier().toString(), "weight", entry.weight()));
        }
        Field replacements = BlackstoneReplaceProcessor.class.getDeclaredField("replacements");
        replacements.setAccessible(true);
        Map<String, String> blackstone = new TreeMap<>();
        for (var entry : ((Map<Block, Block>) replacements.get(BlackstoneReplaceProcessor.INSTANCE)).entrySet()) {
            blackstone.put(BuiltInRegistries.BLOCK.getKey(entry.getKey()).toString(), BuiltInRegistries.BLOCK.getKey(entry.getValue()).toString());
        }
        Files.writeString(Path.of(args[0]), new Gson().toJson(Map.of("version", SharedConstants.getCurrentVersion().id(), "clientSha1", sha,
                "blockFields", blocks, "lootFields", loot, "templateFields", templates,
                "blackstoneReplacements", blackstone,
                "trialSpawnerDefaults", Map.of("loot_tables_to_eject", trialLoot,
                    "items_to_drop_when_ominous", TrialSpawnerConfig.DEFAULT.itemsToDropWhenOminous().identifier().toString()))));
        System.out.println("Exported structure block/loot constants and procedural template selections");
    }
}
