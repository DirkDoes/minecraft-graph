import com.google.gson.Gson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.lang.reflect.ParameterizedType;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import net.minecraft.SharedConstants;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.effect.MobEffectInstance;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityTypes;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.level.block.entity.BeaconBlockEntity;

// Export registry values through the game rather than maintaining a potion/effect list.
public class ExportEffectMetadata {
    private static Map<String, Object> instance(MobEffectInstance effect) {
        return Map.of("id", BuiltInRegistries.MOB_EFFECT.getKey(effect.getEffect().value()).toString(),
                      "duration", effect.getDuration(), "amplifier", effect.getAmplifier(),
                      "ambient", effect.isAmbient(), "showParticles", effect.isVisible(), "showIcon", effect.showIcon());
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass the output JSON path");
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        Map<String, Object> effects = new TreeMap<>();
        for (var effect : BuiltInRegistries.MOB_EFFECT) {
            List<Object> attributes = new ArrayList<>();
            effect.createModifiers(0, (attribute, modifier) -> attributes.add(Map.of(
                "attribute", BuiltInRegistries.ATTRIBUTE.getKey(attribute.value()).toString(),
                "amount", modifier.amount(), "operation", modifier.operation().name())));
            effects.put(BuiltInRegistries.MOB_EFFECT.getKey(effect).toString(), Map.of(
                "descriptionId", effect.getDescriptionId(), "category", effect.getCategory().name(),
                "color", effect.getColor(), "instantaneous", effect.isInstantaneous(),
                "class", effect.getClass().getName(), "attributesAtLevelOne", attributes));
        }
        Map<String, Object> potions = new TreeMap<>();
        for (var potion : BuiltInRegistries.POTION) {
            potions.put(BuiltInRegistries.POTION.getKey(potion).toString(), potion.getEffects().stream().map(ExportEffectMetadata::instance).toList());
        }
        List<Object> beacon = new ArrayList<>();
        for (var tier : BeaconBlockEntity.BEACON_EFFECTS) {
            beacon.add(tier.stream().map(effect -> BuiltInRegistries.MOB_EFFECT.getKey(effect.value()).toString()).toList());
        }
        List<String> fireImmuneEntities = new ArrayList<>();
        for (var entity : BuiltInRegistries.ENTITY_TYPE) {
            if (entity.fireImmune()) fireImmuneEntities.add(BuiltInRegistries.ENTITY_TYPE.getKey(entity).toString());
        }
        Map<String, Object> entityEffectMethods = new TreeMap<>();
        for (var field : EntityTypes.class.getFields()) {
            if (field.getGenericType() instanceof ParameterizedType type && type.getRawType() == net.minecraft.world.entity.EntityType.class) {
                Class<?> entityClass = (Class<?>) type.getActualTypeArguments()[0];
                if (Mob.class.isAssignableFrom(entityClass)) {
                    String id = BuiltInRegistries.ENTITY_TYPE.getKey((net.minecraft.world.entity.EntityType<?>) field.get(null)).toString();
                    entityEffectMethods.put(id, Map.of(
                        "canBeAffected", entityClass.getMethod("canBeAffected", MobEffectInstance.class).getDeclaringClass().getName(),
                        "addEffect", entityClass.getMethod("addEffect", MobEffectInstance.class, Entity.class).getDeclaringClass().getName()));
                }
            }
        }
        Path jar = Path.of(BuiltInRegistries.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        Map<String, Object> result = Map.of("version", SharedConstants.getCurrentVersion().name(),
            "clientSha1", HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(Files.readAllBytes(jar))),
            "effects", effects, "potions", potions, "beaconTiers", beacon, "fireImmuneEntities", fireImmuneEntities,
            "entityEffectMethods", entityEffectMethods);
        if (effects.isEmpty() || potions.isEmpty()) throw new IllegalStateException("Empty registry export");
        Files.writeString(Path.of(args[0]), new Gson().toJson(result));
        System.out.println("Exported " + effects.size() + " effects and " + potions.size() + " potion definitions");
    }
}
