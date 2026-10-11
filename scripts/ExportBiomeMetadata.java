import com.google.gson.Gson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.TreeMap;
import net.minecraft.SharedConstants;
import net.minecraft.core.registries.Registries;
import net.minecraft.data.registries.VanillaRegistries;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.level.biome.MultiNoiseBiomeSourceParameterList;
import net.minecraft.world.level.biome.TheEndBiomeSource;

public class ExportBiomeMetadata {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass the output JSON path");
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        Map<String, Object> presets = new TreeMap<>();
        for (var preset : MultiNoiseBiomeSourceParameterList.knownPresets().keySet()) {
            presets.put(preset.id().toString(), preset.usedBiomes().map(key -> key.identifier().toString()).distinct().sorted().toList());
        }
        var registry = VanillaRegistries.createWorldLookup().lookupOrThrow(Registries.BIOME);
        var end = TheEndBiomeSource.create(registry).possibleBiomes().stream()
            .map(holder -> holder.unwrapKey().orElseThrow().identifier().toString()).sorted().toList();
        var biomes = registry.listElementIds().map(key -> key.identifier().toString()).sorted().toList();
        if (presets.size() != 2 || end.size() != 5 || biomes.isEmpty()) throw new IllegalStateException("Unexpected biome registry coverage: " + presets.size() + "/" + end.size() + "/" + biomes.size());
        String sha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(Files.readAllBytes(Path.of(".cache/client.jar"))));
        Files.writeString(Path.of(args[0]), new Gson().toJson(Map.of("version", SharedConstants.getCurrentVersion().id(),
            "clientSha1", sha, "presets", presets, "endBiomes", end, "biomes", biomes)));
        System.out.println("Exported " + biomes.size() + " biomes and exact biome-source memberships");
    }
}
