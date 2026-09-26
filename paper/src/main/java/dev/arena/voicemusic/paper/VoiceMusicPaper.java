package dev.arena.voicemusic.paper;

import de.maxhenkel.voicechat.api.BukkitVoicechatService;
import dev.arena.voicemusic.audio.MusicRuntime;
import dev.arena.voicemusic.core.MusicConfig;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.event.ClickEvent;
import org.bukkit.Bukkit;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabExecutor;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.IOException;
import java.util.List;

public final class VoiceMusicPaper extends JavaPlugin implements TabExecutor {
    private MusicRuntime runtime;
    private PaperVoicePlugin voicePlugin;

    @Override public void onEnable() {
        try {
            MusicConfig config = MusicConfig.load(getDataFolder().toPath().resolve("voice-music.properties"));
            var configFile = getDataFolder().toPath().resolve("voice-music.properties");
            runtime = new MusicRuntime(config, () -> Bukkit.getOnlinePlayers().stream().map(Player::getUniqueId).toList(),
                    message -> getLogger().info(message), token -> { try { MusicConfig.saveYoutubeRefreshToken(configFile, token); } catch (IOException ex) { throw new java.io.UncheckedIOException(ex); } });
        } catch (IOException | RuntimeException ex) {
            getLogger().severe("Could not load Voice Music configuration/audio engine: " + ex.getMessage());
            getServer().getPluginManager().disablePlugin(this);
            return;
        }
        BukkitVoicechatService service = getServer().getServicesManager().load(BukkitVoicechatService.class);
        if (service == null) {
            getLogger().severe("Simple Voice Chat API service not found; disabling Voice Music.");
            runtime.close();
            getServer().getPluginManager().disablePlugin(this);
            return;
        }
        voicePlugin = new PaperVoicePlugin(runtime);
        service.registerPlugin(voicePlugin);
        var command = getCommand("music");
        if (command == null) throw new IllegalStateException("plugin.yml is missing the music command");
        command.setExecutor(this);
        command.setTabCompleter(this);
        getLogger().info("Voice Music (Paper) enabled.");
    }

    @Override public void onDisable() {
        if (runtime != null) runtime.close();
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player player)) { sender.sendMessage("Only players can use music commands."); return true; }
        if (args.length == 0 || args[0].equalsIgnoreCase("help")) { help(player); return true; }
        String sub = args[0].toLowerCase(java.util.Locale.ROOT);
        if (sub.equals("play") || sub.equals("search")) {
            if (args.length < 2) { player.sendMessage(Component.text("Usage: /music play <song, SoundCloud URL, Spotify URL, or audio URL>")); return true; }
            String query = String.join(" ", java.util.Arrays.copyOfRange(args, 1, args.length));
            runtime.play(player.getUniqueId(), query, message -> Bukkit.getScheduler().runTask(this, () -> {
                if (player.isOnline()) player.sendMessage(Component.text(message));
            }));
            return true;
        }
        String answer = switch (sub) {
            case "skip" -> runtime.skip(player.getUniqueId());
            case "pause" -> runtime.pause(player.getUniqueId());
            case "resume" -> runtime.resume(player.getUniqueId());
            case "stop" -> runtime.stop(player.getUniqueId());
            case "now", "now-playing" -> runtime.now(player.getUniqueId());
            case "queue" -> runtime.queue(player.getUniqueId());
            case "gui" -> { controls(player); yield null; }
            default -> "Unknown subcommand. Use /music help.";
        };
        if (answer != null) player.sendMessage(Component.text(answer));
        return true;
    }

    @Override public List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args) {
        if (args.length == 1) return List.of("play", "search", "queue", "skip", "pause", "resume", "stop", "now", "gui", "help").stream()
                .filter(s -> s.startsWith(args[0].toLowerCase(java.util.Locale.ROOT))).toList();
        return List.of();
    }

    private void help(Player player) {
        player.sendMessage(Component.text("Use /music play <query|URL>, then /music gui for controls. Everyone hearing music must be in your current Simple Voice Chat group."));
    }

    private void controls(Player player) {
        player.sendMessage(Component.text("[⏸ Pause] ").clickEvent(ClickEvent.runCommand("/music pause"))
                .append(Component.text("[▶ Resume] ").clickEvent(ClickEvent.runCommand("/music resume")))
                .append(Component.text("[⏭ Skip] ").clickEvent(ClickEvent.runCommand("/music skip")))
                .append(Component.text("[⏹ Stop] ").clickEvent(ClickEvent.runCommand("/music stop")))
                .append(Component.text("[♫ Queue]").clickEvent(ClickEvent.runCommand("/music queue"))));
    }
}
