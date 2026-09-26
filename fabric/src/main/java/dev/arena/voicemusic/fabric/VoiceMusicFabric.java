package dev.arena.voicemusic.fabric;

import com.mojang.brigadier.arguments.StringArgumentType;
import dev.arena.voicemusic.audio.MusicRuntime;
import dev.arena.voicemusic.core.MusicConfig;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

public final class VoiceMusicFabric implements ModInitializer {
    static final Logger LOGGER = LoggerFactory.getLogger("voice_music");
    static final AtomicReference<MinecraftServer> SERVER = new AtomicReference<>();
    static volatile MusicRuntime RUNTIME;

    @Override public void onInitialize() {
        try {
            MusicConfig config = MusicConfig.load(FabricLoader.getInstance().getConfigDir().resolve("voice-music.properties"));
            var configFile = FabricLoader.getInstance().getConfigDir().resolve("voice-music.properties");
            RUNTIME = new MusicRuntime(config, () -> {
                MinecraftServer server = SERVER.get();
                return server == null ? List.of() : server.getPlayerList().getPlayers().stream().map(ServerPlayer::getUUID).toList();
            }, LOGGER::info, token -> { try { MusicConfig.saveYoutubeRefreshToken(configFile, token); } catch (IOException ex) { throw new java.io.UncheckedIOException(ex); } });
        } catch (IOException | RuntimeException ex) {
            throw new IllegalStateException("Voice Music could not load config or initialize audio sources", ex);
        }
        ServerLifecycleEvents.SERVER_STARTED.register(SERVER::set);
        ServerLifecycleEvents.SERVER_STOPPING.register(server -> {
            SERVER.compareAndSet(server, null);
            MusicRuntime runtime = RUNTIME;
            if (runtime != null) runtime.close();
        });
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> {
            dispatcher.register(Commands.literal("music")
                    .executes(ctx -> { help(ctx.getSource()); return 1; })
                    .then(Commands.literal("play").then(Commands.argument("query", StringArgumentType.greedyString())
                            .executes(ctx -> play(ctx.getSource(), StringArgumentType.getString(ctx, "query")))))
                    .then(Commands.literal("search").then(Commands.argument("query", StringArgumentType.greedyString())
                            .executes(ctx -> play(ctx.getSource(), StringArgumentType.getString(ctx, "query")))))
                    .then(Commands.literal("skip").executes(ctx -> action(ctx.getSource(), "skip")))
                    .then(Commands.literal("pause").executes(ctx -> action(ctx.getSource(), "pause")))
                    .then(Commands.literal("resume").executes(ctx -> action(ctx.getSource(), "resume")))
                    .then(Commands.literal("stop").executes(ctx -> action(ctx.getSource(), "stop")))
                    .then(Commands.literal("now").executes(ctx -> action(ctx.getSource(), "now")))
                    .then(Commands.literal("queue").executes(ctx -> action(ctx.getSource(), "queue")))
                    .then(Commands.literal("gui").executes(ctx -> { controls(ctx.getSource()); return 1; }))
                    .then(Commands.literal("help").executes(ctx -> { help(ctx.getSource()); return 1; })));
        });
        LOGGER.info("Voice Music (Fabric server) initialized.");
    }

    private static int play(net.minecraft.commands.CommandSourceStack source, String query) throws com.mojang.brigadier.exceptions.CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        MusicRuntime runtime = RUNTIME;
        if (runtime == null) { player.sendSystemMessage(Component.literal("Music is not ready.")); return 0; }
        runtime.play(player.getUUID(), query, message -> source.getServer().execute(() -> player.sendSystemMessage(Component.literal(message))));
        return 1;
    }

    private static int action(net.minecraft.commands.CommandSourceStack source, String action) throws com.mojang.brigadier.exceptions.CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        MusicRuntime runtime = RUNTIME;
        String result = runtime == null ? "Music is not ready." : switch (action) {
            case "skip" -> runtime.skip(player.getUUID());
            case "pause" -> runtime.pause(player.getUUID());
            case "resume" -> runtime.resume(player.getUUID());
            case "stop" -> runtime.stop(player.getUUID());
            case "now" -> runtime.now(player.getUUID());
            case "queue" -> runtime.queue(player.getUUID());
            default -> "Unknown music command.";
        };
        player.sendSystemMessage(Component.literal(result));
        return 1;
    }

    private static void help(net.minecraft.commands.CommandSourceStack source) {
        source.sendSystemMessage(Component.literal("Music: /music play <query|URL>, /music queue, skip, pause, resume, stop, now, gui"));
    }

    private static void controls(net.minecraft.commands.CommandSourceStack source) {
        Component line = button("⏸ Pause", "pause").append(Component.literal("  "))
                .append(button("▶ Resume", "resume")).append(Component.literal("  "))
                .append(button("⏭ Skip", "skip")).append(Component.literal("  "))
                .append(button("⏹ Stop", "stop")).append(Component.literal("  "))
                .append(button("♫ Queue", "queue"));
        source.sendSystemMessage(line);
    }

    private static MutableComponent button(String label, String action) {
        return Component.literal("[" + label + "]").withStyle(Style.EMPTY.withClickEvent(new ClickEvent.RunCommand("/music " + action)));
    }
}
