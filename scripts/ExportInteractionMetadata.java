import com.google.gson.Gson;
import com.google.gson.JsonParser;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.TreeMap;
import net.minecraft.SharedConstants;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.BucketItem;
import net.minecraft.world.item.HoneycombItem;
import net.minecraft.world.item.MobBucketItem;
import net.minecraft.world.item.SpawnEggItem;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.InfestedBlock;
import net.minecraft.world.level.block.FlowerPotBlock;
import net.minecraft.world.level.block.WeatheringCopper;
import net.minecraft.world.level.block.WeatheringCopperCollection;

// Export registry mappings rather than infer mob, block or copper identities from names.
public class ExportInteractionMetadata {
    static Map<String, String> blocks(Map<Block, Block> values) {
        Map<String, String> result = new TreeMap<>();
        values.forEach((from, to) -> result.put(BuiltInRegistries.BLOCK.getKey(from).toString(), BuiltInRegistries.BLOCK.getKey(to).toString()));
        return result;
    }
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2) throw new IllegalArgumentException("Pass output JSON and optional client jar");
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        Map<String, String> spawnEggs = new TreeMap<>(), mobBuckets = new TreeMap<>(), placedBlocks = new TreeMap<>(), placedFluids = new TreeMap<>(), infestation = new TreeMap<>(), flowerPots = new TreeMap<>(), copperChests = new TreeMap<>();
        Field bucketType = MobBucketItem.class.getDeclaredField("type");
        bucketType.setAccessible(true);
        for (var item : BuiltInRegistries.ITEM) {
            String id = BuiltInRegistries.ITEM.getKey(item).toString();
            if (item instanceof SpawnEggItem) {
                var report = JsonParser.parseString(Files.readString(Path.of(".cache/generated/reports/minecraft/components/item/" + id.substring(id.indexOf(':') + 1) + ".json")));
                String entity = report.getAsJsonObject().getAsJsonObject("components").getAsJsonObject("minecraft:entity_data").get("id").getAsString();
                spawnEggs.put(id, entity);
            }
            if (item instanceof MobBucketItem) mobBuckets.put(id, EntityType.getKey((EntityType<?>) bucketType.get(item)).toString());
            if (item instanceof BlockItem blockItem) placedBlocks.put(id, BuiltInRegistries.BLOCK.getKey(blockItem.getBlock()).toString());
            if (item instanceof BucketItem bucket && !bucket.getContent().defaultFluidState().isEmpty()) placedFluids.put(id, BuiltInRegistries.BLOCK.getKey(bucket.getContent().defaultFluidState().createLegacyBlock().getBlock()).toString());
        }
        Path client = Path.of(args.length == 2 ? args[1] : ".cache/client.jar");
        for (var block : BuiltInRegistries.BLOCK) {
            if (block instanceof InfestedBlock infested) infestation.put(BuiltInRegistries.BLOCK.getKey(infested.getHostBlock()).toString(), BuiltInRegistries.BLOCK.getKey(block).toString());
            if (block instanceof FlowerPotBlock pot && !BuiltInRegistries.BLOCK.getKey(pot.getPotted()).toString().equals("minecraft:air")) flowerPots.put(BuiltInRegistries.BLOCK.getKey(pot.getPotted()).toString(), BuiltInRegistries.BLOCK.getKey(block).toString());
        }
        String clientSha1 = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(Files.readAllBytes(client)));
        if (spawnEggs.isEmpty() || mobBuckets.isEmpty() || placedBlocks.isEmpty()) throw new IllegalStateException("Empty registry mapping");
        Map<String, Object> result = new TreeMap<>();
        result.put("version", SharedConstants.getCurrentVersion().id());
        result.put("clientSha1", clientSha1);
        result.put("spawnEggs", spawnEggs);
        result.put("mobBuckets", mobBuckets);
        result.put("placedBlocks", placedBlocks);
        result.put("placedFluids", placedFluids);
        result.put("waxables", blocks(HoneycombItem.WAXABLES.get()));
        result.put("oxidation", blocks(WeatheringCopper.NEXT_BY_BLOCK.get()));
        result.put("infestation", infestation);
        result.put("flowerPots", flowerPots);
        WeatheringCopperCollection.zipApply(Blocks.COPPER_BLOCK, Blocks.COPPER_CHEST, (from, to) -> copperChests.put(BuiltInRegistries.BLOCK.getKey(from).toString(), BuiltInRegistries.BLOCK.getKey(to).toString()));
        result.put("copperConstructionChests", copperChests);
        Files.writeString(Path.of(args[0]), new Gson().toJson(result));
        System.out.println("Exported " + spawnEggs.size() + " spawn eggs, " + mobBuckets.size() + " mob buckets and " + placedBlocks.size() + " block items");
    }
}
