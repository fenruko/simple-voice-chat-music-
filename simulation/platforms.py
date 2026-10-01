"""Python ports of VoiceMusicPaper (Bukkit) and VoiceMusicFabric (Brigadier)."""
import os
from voicemusic import MusicRuntime, MusicConfig

class PaperVoicePlugin:
    def __init__(self, runtime): self.runtime = runtime
    def getPluginId(self): return "voice_music"
    def initialize(self, api): pass
    def registerEvents(self, registration): self.runtime.registerEvents(registration)

class VoiceMusicPaper:
    """dev.arena.voicemusic.paper.VoiceMusicPaper"""
    def __init__(self, server, jar):
        self.server, self.jar = server, jar
        self.runtime, self.voicePlugin = None, None
        self.messages = []
    def onEnable(self):
        # Command registration comes FIRST: disabling the plugin on an audio engine
        # failure removes /music entirely, which looks like "nothing was installed".
        command = self.server.get_command_map().get("music")
        if command is None: raise RuntimeError("plugin.yml is missing the music command")
        command.setExecutor(self); command.setTabCompleter(self)
        try:
            config = MusicConfig.load(os.path.join(self.jar["data_folder"], "voice-music.properties"))
            configFile = os.path.join(self.jar["data_folder"], "voice-music.properties")
            self.runtime = MusicRuntime(config, lambda: [p.getUniqueId() for p in self.server.get_online_players()],
                                        lambda m: self.server.log.append(f"[VoiceMusic] {m}"),
                                        lambda t: MusicConfig.save_youtube_refresh_token(configFile, t),
                                        catalog=self.jar["catalog"], classpath=self.jar.get("nested_jars"))
        except Exception as ex:
            self.server.log.append(f"[VoiceMusic] Could not load Voice Music configuration/audio engine: {type(ex).__name__}: {ex}. "
                                   f"/music stays registered but will report that the audio engine is unavailable.")
            return
        service = self.server.get_services_manager().load("BukkitVoicechatService")
        if service is None:
            self.server.log.append("[VoiceMusic] Simple Voice Chat API service not found; /music stays registered but cannot play.")
            engine, self.runtime = self.runtime, None
            if engine: engine.close()
            return
        self.voicePlugin = PaperVoicePlugin(self.runtime)
        service.registerPlugin(self.voicePlugin)
        self.server.log.append("[VoiceMusic] Voice Music (Paper) enabled.")
    def onDisable(self):
        if self.runtime: self.runtime.close()
    def onCommand(self, sender, command, label, args):
        if sender.kind != "player":
            self.messages.append("Only players can use music commands."); return True
        # /music and /music help must answer even when the engine is down: that is the
        # only way a user can tell "broken" from "not installed".
        if len(args) == 0 or args[0].lower() == "help":
            self.help(sender); return True
        if self.runtime is None:
            self.messages.append("Music is not ready: the audio engine failed to start. Check the server log for a Voice Music error.")
            return True
        sub = args[0].lower()
        if sub in ("play", "search"):
            if len(args) < 2:
                self.messages.append("Usage: /music play <song, SoundCloud URL, Spotify URL, or audio URL>"); return True
            query = " ".join(args[1:])
            def reply(m): self.messages.append(m)
            self.runtime.play(sender.getUniqueId(), query, reply)
            return True
        answer = {"skip": lambda: self.runtime.skip(sender.getUniqueId()),
                  "pause": lambda: self.runtime.pause(sender.getUniqueId()),
                  "resume": lambda: self.runtime.resume(sender.getUniqueId()),
                  "stop": lambda: self.runtime.stop(sender.getUniqueId()),
                  "now": lambda: self.runtime.now(sender.getUniqueId()),
                  "queue": lambda: self.runtime.queue(sender.getUniqueId())}.get(sub)
        if answer is None:
            if sub == "gui": self.controls(sender); return True
            self.messages.append("Unknown subcommand. Use /music help.")
            return True
        self.messages.append(answer()); return True
    def onTabComplete(self, sender, command, alias, args):
        if len(args) == 1:
            return [s for s in ("play", "search", "queue", "skip", "pause", "resume", "stop", "now", "gui", "help") if s.startswith(args[0].lower())]
        return []
    def help(self, player):
        self.messages.append("Use /music play <query|URL>, then /music gui for controls. Everyone hearing music must be in your current Simple Voice Chat group.")
    def controls(self, player):
        self.messages.append("[⏸ Pause] [▶ Resume] [⏭ Skip] [⏹ Stop] [♫ Queue]")

class FabricVoicePlugin:
    """dev.arena.voicemusic.fabric.FabricVoicePlugin - reads VoiceMusicFabric.RUNTIME"""
    def getPluginId(self): return "voice_music"
    def initialize(self, api): pass
    def registerEvents(self, registration):
        runtime = VoiceMusicFabric.RUNTIME
        if runtime is not None: runtime.registerEvents(registration)

class VoiceMusicFabric:
    """dev.arena.voicemusic.fabric.VoiceMusicFabric"""
    def __init__(self, server, mod):
        self.server, self.mod = server, mod
        self.messages = []
    def onInitialize(self):
        # CommandRegistrationCallback and the lifecycle hooks are registered BEFORE the
        # audio engine is built. An exception escaping onInitialize() aborts Fabric
        # Loader's mod init stage and takes the server down, so nothing may throw here.
        def play(source, query):
            player = source["player"]
            runtime = VoiceMusicFabric.RUNTIME
            if runtime is None:
                self.messages.append("Music is not ready."); return 0
            def reply(m):
                self.messages.append(m)
            runtime.play(player.getUniqueId(), query, reply); return 1
        def action(source, what):
            player = source["player"]
            runtime = VoiceMusicFabric.RUNTIME
            result = "Music is not ready." if runtime is None else {
                "skip": lambda: runtime.skip(player.getUniqueId()),
                "pause": lambda: runtime.pause(player.getUniqueId()),
                "resume": lambda: runtime.resume(player.getUniqueId()),
                "stop": lambda: runtime.stop(player.getUniqueId()),
                "now": lambda: runtime.now(player.getUniqueId()),
                "queue": lambda: runtime.queue(player.getUniqueId())}[what]()
            self.messages.append(result); return 1
        def register(dispatcher, registry, environment):
            for sub in ("skip", "pause", "resume", "stop", "now", "queue"):
                self.server.register_command(f"music {sub}", lambda s, a, w=sub: action(s, w))
            for sub in ("play", "search"):
                self.server.register_command(f"music {sub}", lambda s, a: play(s, " ".join(a)))
            self.server.register_command("music gui", lambda s, a: (self.controls(s), 1)[1])
            self.server.register_command("music help", lambda s, a: (self.help(s), 1)[1])
            self.server.register_command("music", lambda s, a: (self.help(s), 1)[1])
        self._register = register
        # Fabric API fires CommandRegistrationCallback when the server builds its dispatcher
        self.server.command_registration_callbacks.append(register)
        try:
            config = MusicConfig.load(os.path.join(self.server.config_dir, "voice-music.properties"))
            configFile = os.path.join(self.server.config_dir, "voice-music.properties")
            VoiceMusicFabric.RUNTIME = MusicRuntime(config, lambda: [p.getUniqueId() for p in self.server.online_players],
                                                    lambda m: self.server.log.append(f"[voice_music] {m}"),
                                                    lambda t: MusicConfig.save_youtube_refresh_token(configFile, t),
                                                    catalog=self.mod["catalog"], classpath=self.mod.get("nested_jars"))
            self.server.log.append("[voice_music] Voice Music (Fabric server) initialized.")
        except Exception as ex:
            VoiceMusicFabric.RUNTIME = None
            self.server.log.append(f"[voice_music] Voice Music could not load its configuration or initialize the audio "
                                   f"engine ({type(ex).__name__}: {ex}). /music is registered but reports "
                                   f"\"Music is not ready.\" until this is fixed.")
    def help(self, source):
        self.messages.append("Music: /music play <query|URL>, /music queue, skip, pause, resume, stop, now, gui")
    def controls(self, source):
        self.messages.append("[⏸ Pause] [▶ Resume] [⏭ Skip] [⏹ Stop] [♫ Queue]")
VoiceMusicFabric.RUNTIME = None
