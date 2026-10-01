"""Aggressive simulation of a live server: Paper + Fabric, with and without the defects."""
import os, sys, shutil, time, uuid, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakes
from fakes import (PaperServer, FabricServer, VoicechatServer, Group, ServerPlayer,
                   VoicechatConnection, StaticAudioChannel, AudioPlaylist, AudioTrack)
from platforms import VoiceMusicPaper, VoiceMusicFabric, FabricVoicePlugin
from voicemusic import MusicRuntime, MusicConfig, TrackRequest, RemoteHostPolicy, BoundedTrackQueue

RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   <-- {detail}" if (detail and not cond) else ""))

class Catalog:
    """Fake 'internet' of media."""
    def __init__(self):
        self.tracks = [AudioTrack("Never Gonna Give You Up", "Rick Astley", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
                       AudioTrack("Daft Punk - One More Time", "Daft Punk", "https://soundcloud.com/daftpunk/one-more-time"),
                       AudioTrack("Jazz Mix", "Joakim Karud", "https://soundcloud.com/joakimkarud/jazz")]
    def search(self, q):
        return [t for t in self.tracks if q.lower().split()[0] in t.info.title.lower()] or self.tracks[:1]
    def by_url(self, url):
        for t in self.tracks:
            if t.info.uri == url or t.identifier == url: return [t]
        return [self.tracks[0]]

class Player:
    def __init__(self, name): self.name = name; self.uuid = uuid.uuid4(); self.kind = "player"; self.messages = []
    def getUniqueId(self): return self.uuid

# What the audio engine actually needs on the classpath. Derived from
# lavaplayer 2.2.7 settings.gradle.kts + youtube-source 1.18.2 settings.gradle.kts.
AUDIO_ENGINE_JARS = {
    "lavaplayer",          # dev.arbjerg:lavaplayer
    "lava-common",         # dev.arbjerg:lava-common  <- DaemonThreadFactory lives here
    "lavaplayer-natives",  # dev.arbjerg:lavaplayer-natives
    "youtube-source",      # dev.lavalink.youtube:v2
    "rhino-engine",        # org.mozilla:rhino-engine
    "nanojson",            # com.grack:nanojson
    "jsoup",
    "commons-io",
    "base64",
    "json",
    "httpclient",
    "httpcore",
    "commons-logging",
    "commons-codec",
    "jackson-core",
    "jackson-databind",
    "jackson-annotations",
    "gson",
}

class Event:
    def __init__(self, group=None, connection=None, playerUuid=None, api=None):
        self.group, self.connection, self.playerUuid = group, connection, playerUuid
        self._api = api
    def getVoicechat(self): return self._api

PLUGIN_YML = """name: VoiceMusic
version: '0.1.0-SNAPSHOT'
main: dev.arena.voicemusic.paper.VoiceMusicPaper
api-version: '26.3'
load: POSTWORLD
depend: [voicechat]
commands:
  music:
    description: Play music to your current Simple Voice Chat group.
    usage: /music <play|search|queue|skip|pause|resume|stop|now|help>
    permission: voicemusic.use
permissions:
  voicemusic.use:
    default: true
  voicemusic.admin:
    default: op
"""

class _SvcStub:
    def __init__(self, server, jar): self.server = server
    def onEnable(self):
        class BukkitVoicechatService:
            def __init__(self): self.plugins = []
            def registerPlugin(self, p): self.plugins.append(p)
        self.server.services["BukkitVoicechatService"] = BukkitVoicechatService()
        self.server.svc.registered_plugins = self.server.services["BukkitVoicechatService"].plugins
class _D:
    def __init__(self, load, depend, name): self.load, self.depend, self.name = load, depend, name

def build_paper_server(data_dir, svc_registered=True, catalog=None):
    srv = PaperServer()
    srv.svc = VoicechatServer()
    # --- SVC as an installed plugin
    srv.plugin_descriptors["voicechat"] = ({"plugin.yml": "name: voicechat\nload: STARTUP\n",
                                           "main_class": _SvcStub, "data_folder": "/tmp/sim/svc"}, _D("STARTUP", [], "voicechat"))
    class PluginManager:
        def disablePlugin(self, p): srv.disabled = getattr(srv, "disabled", set()) | {p}
    srv.plugin_manager = PluginManager()
    jar = {"plugin.yml": PLUGIN_YML, "main_class": VoiceMusicPaper, "data_folder": data_dir, "catalog": catalog,
           # shadowJar bundles the whole runtimeClasspath, so the Paper jar is complete.
           "nested_jars": set(AUDIO_ENGINE_JARS)}
    srv.load_plugin(jar)
    if not svc_registered:
        srv.plugin_descriptors.pop("voicechat", None)
    return srv, jar

def add_player(srv, group, connected=True, name="Steve"):
    p = Player(name)
    srv.online_players.append(p)
    srv.svc.players[p.uuid] = p
    conn = VoicechatConnection(ServerPlayer(p.uuid, name), group, connected)
    srv.svc.connections[p.uuid] = conn
    return p, conn

# =====================================================================
print("\n=== SCENARIO 1: Paper server, normal install, SVC present ===")
shutil.rmtree("/tmp/sim/data", ignore_errors=True)
cat = Catalog()
srv, jar = build_paper_server("/tmp/sim/data", catalog=cat)
srv.enable_plugins("STARTUP")
srv.enable_plugins("POSTWORLD")
plugin = [p for p in srv.enabled]
cmd = srv.get_command_map().get("music")
check("Paper: /music command registered", cmd is not None)
check("Paper: command has executor", cmd is not None and cmd.executor is not None)
check("Paper: plugin reported enabled", any("enabled" in l for l in srv.log))
check("Paper: SVC service plugin registered", len(srv.services["BukkitVoicechatService"].plugins) == 1)

g = Group(uuid.uuid4(), "friends")
srv.svc.groups[g.getId()] = g
srv.svc.start()
p, conn = add_player(srv, g)
check("SVC: voice bridge ready (volume category registered)",
      "voice_music" in srv.svc.volume_categories)
check("SVC: volume category id accepted by API", srv.svc.volume_categories["voice_music"].id == "voice_music")

paper_plugin = cmd.executor
paper_plugin.onCommand(p, cmd, "music", ["help"])
check("Paper: /music help answers", any("Use /music play" in m for m in paper_plugin.messages), paper_plugin.messages)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["play", "never", "gonna"])
check("Paper: /music play replies", len(paper_plugin.messages) >= 2, paper_plugin.messages)
sess = srv.services["BukkitVoicechatService"].plugins[0].runtime.groups.get(g.getId())
check("Paper: session created for the group", sess is not None)
check("Paper: track started playing (not queued)", sess is not None and sess.player.getPlayingTrack() is not None)
check("Paper: player is an audio target", sess is not None and p.uuid in sess.channel.targets)
check("Paper: bypassGroupIsolation is false (no leaking to isolated groups)",
      sess is not None and sess.channel.bypassGroupIsolation is False)
check("Paper: audio player started", sess is not None and sess.voicePlayer is not None and sess.voicePlayer.started)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["now"])
check("Paper: /music now reports track", any("Never Gonna" in m for m in paper_plugin.messages), paper_plugin.messages)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["queue"])
check("Paper: /music queue works", any("Queued" in m or "empty" in m for m in paper_plugin.messages), paper_plugin.messages)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["skip"])
check("Paper: /music skip works", any("Skipped" in m for m in paper_plugin.messages), paper_plugin.messages)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["gui"])
check("Paper: /music gui renders buttons", any("Pause" in m for m in paper_plugin.messages), paper_plugin.messages)
paper_plugin.messages.clear()
check("Paper: tab-completion offers play", "play" in paper_plugin.onTabComplete(p, cmd, "music", ["p"]))

# cooldown
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["play", "another"])
check("Paper: 2s cooldown enforced", any("wait a moment" in m for m in paper_plugin.messages), paper_plugin.messages)

# =====================================================================
print("\n=== SCENARIO 2: group isolation, join/leave, expiry ===")
g2 = Group(uuid.uuid4(), "others")
srv.svc.groups[g2.getId()] = g2
p2, conn2 = add_player(srv, g2, name="Alex")
paper_plugin.messages.clear()
paper_plugin.onCommand(p2, cmd, "music", ["play", "dizzy"])
s2 = srv.services["BukkitVoicechatService"].plugins[0].runtime.groups.get(g2.getId())
check("Group isolation: second group has its own session", s2 is not None and s2 is not sess)
check("Group isolation: no cross-group targets", p2.uuid not in sess.channel.targets and p.uuid not in s2.channel.targets)
# audio actually delivered only to the right group
import time as _t; _t.sleep(2.1)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["play", "never", "gonna"])
print("   [debug] replay msgs:", paper_plugin.messages, "| sess.voicePlayer:", sess.voicePlayer, "| s2:", s2.voicePlayer)
for _ in range(3):
    if sess.voicePlayer: sess.voicePlayer.tick()
    if s2.voicePlayer: s2.voicePlayer.tick()
check("Audio delivered to group members only",
      len(sess.channel.sent) > 0 and len(s2.channel.sent) > 0
      and p2.uuid not in sess.channel.targets and p.uuid not in s2.channel.targets,
      f"sess.sent={len(sess.channel.sent)} s2.sent={len(s2.channel.sent)} targets={sess.channel.targets},{s2.channel.targets}")
# leave group
print("   [debug] handlers:", {k: len(v) for k, v in srv.svc.event_handlers.items()})
srv.svc.dispatch("LeaveGroupEvent", Event(g, conn, None, srv.svc.api))
print("   [debug] after leave targets:", sess.channel.targets, "members:", sess.members)
check("Leaving group removes audio target", p.uuid not in sess.channel.targets)
srv.svc.dispatch("PlayerDisconnectedEvent", Event(None, None, p2.uuid, srv.svc.api))
check("Disconnect removes target", p2.uuid not in s2.channel.targets)
# expiry
runtime = srv.services["BukkitVoicechatService"].plugins[0].runtime
sess.lastMembershipChangeNanos -= 121 * 10**9
runtime.expire_empty_groups()
check("Idle empty session expires", g.getId() not in runtime.groups)

# =====================================================================
print("\n=== SCENARIO 3: hostile / edge inputs ===")
paper_plugin.messages.clear()
for bad in ["", " ", "file:///etc/passwd", "https://user:pass@example.test/a.mp3", "http://localhost/a.mp3",
            "https://media.example.test:8443/x.mp3", "spotify:album:0123456789012345678901", "x" * 501,
            "https://nas.local/audio.mp3"]:
    paper_plugin.onCommand(p, cmd, "music", ["play"] + bad.split())
    assert any("not allowed" in m or "Invalid" in m or "Only" in m or "malformed" in m or "printable" in m
               or "Query must" in m or "Unsupported" in m or "Usage" in m for m in paper_plugin.messages), (bad, paper_plugin.messages)
    paper_plugin.messages.clear()
check("Hostile inputs all rejected with a message", True)
import time as _t2; _t2.sleep(2.1)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["play", "https://youtu.be/dQw4w9WgXcQ"])
check("YouTube short URL accepted", any("Added" in m or "Looking" in m for m in paper_plugin.messages), paper_plugin.messages)
import time as _t3; _t3.sleep(2.1)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["play", "https://media.example.test/song.mp3"])
check("Arbitrary host blocked by default", any("Only YouTube and SoundCloud" in m for m in paper_plugin.messages), paper_plugin.messages)
paper_plugin.messages.clear()
paper_plugin.onCommand(p, cmd, "music", ["search", "scsearch:", ])
check("Empty search text rejected", any("Usage" in m or "empty" in m for m in paper_plugin.messages), paper_plugin.messages)

# =====================================================================
print("\n=== SCENARIO 4: Fabric server, FIXED build (complete nested set, relaxed depends) ===")
shutil.rmtree("/tmp/sim/fdata", ignore_errors=True)
fsrv = FabricServer(); fsrv.minecraft_version = "26.3"
mod = {"fabric.mod.json": {"id": "voice_music", "version": "0.1.0-SNAPSHOT",
                           # fabric/build.gradle now derives these from the audio engine's
                           # runtime classpath instead of naming lavaplayer alone.
                           "depends": {"fabricloader": ">=0.19.3", "minecraft": "26.3.x", "java": ">=25",
                                       "fabric-api": "*", "voicechat": "*", "voicechat_api": "*"}},
       "catalog": cat,
       "nested_jars": set(AUDIO_ENGINE_JARS)}
mod["initializer"] = VoiceMusicFabric(fsrv, mod)
mod["voicechat_entrypoint"] = FabricVoicePlugin()
fsrv.load_mod(mod)
# Simple Voice Chat installed (bundles voicechat_api as a nested mod)
fsrv.load_mod({"fabric.mod.json": {"id": "voicechat_api", "version": "2.6.23"}})
fsrv.load_mod({"fabric.mod.json": {"id": "voicechat", "version": "2.6.23+26.3"}})
fsrv.load_mod({"fabric.mod.json": {"id": "fabric-api", "version": "0.161.0"}})
fsrv.load_mod({"fabric.mod.json": {"id": "fabricloader", "version": "0.19.5"}})
fsrv.start()
loaded, failed = fsrv.resolve_dependencies()
check("Fabric: mod loads with voicechat_api 2.6.23 (relaxed pin)", "voice_music" in loaded, failed)
check("Fabric: /music command registered", "music" in fsrv.commands, list(fsrv.commands)[:5])
check("Fabric: audio engine actually started (no NoClassDefFoundError)",
      VoiceMusicFabric.RUNTIME is not None and any("initialized" in l for l in fsrv.log), fsrv.log[-3:])
fp = Player("FabricSteve")
fgroup = Group(uuid.uuid4(), "fab"); fsrv.svc.groups[fgroup.getId()] = fgroup
fsrv.online_players.append(fp)
fsrv.svc.players[fp.uuid] = fp
fconn = VoicechatConnection(ServerPlayer(fp.uuid, "FabricSteve"), fgroup, True)
fsrv.svc.connections[fp.uuid] = fconn
fsrv.svc.start()
fsrv.dispatch({"player": fp}, "music help")
check("Fabric: /music help answers", any("/music play" in m for m in mod["initializer"].messages), mod["initializer"].messages)
mod["initializer"].messages.clear()
fsrv.dispatch({"player": fp}, "music play never gonna")
check("Fabric: /music play replies", len(mod["initializer"].messages) >= 2, mod["initializer"].messages)
fsession = VoiceMusicFabric.RUNTIME.groups.get(fgroup.getId())
check("Fabric: group session created", fsession is not None)
check("Fabric: SVC voice plugin registered (entrypoint discovery works)",
      len(fsrv.svc.registered_plugins) == 1 and fsrv.svc.registered_plugins[0].getPluginId() == "voice_music")
check("Fabric: volume category registered", "voice_music" in fsrv.svc.volume_categories)

print("\n=== SCENARIO 4b: REPRODUCE - old descriptor, user has SVC 2.6.23 ===")
fsrv2 = FabricServer(); fsrv2.minecraft_version = "26.3"
old_depends = {"fabricloader": ">=0.19.5", "minecraft": "=26.3", "java": ">=25",
               "fabric-api": "*", "voicechat_api": ">=2.6.24"}
mod2 = {"fabric.mod.json": {"id": "voice_music", "version": "0.1.0-SNAPSHOT", "depends": old_depends},
        "catalog": cat, "nested_jars": set(AUDIO_ENGINE_JARS)}
mod2["initializer"] = VoiceMusicFabric(fsrv2, mod2)
fsrv2.load_mod(mod2)
fsrv2.load_mod({"fabric.mod.json": {"id": "voicechat_api", "version": "2.6.23"}})
fsrv2.load_mod({"fabric.mod.json": {"id": "fabric-api", "version": "0.161.0"}})
fsrv2.load_mod({"fabric.mod.json": {"id": "fabricloader", "version": "0.19.5"}})
loaded2, failed2 = fsrv2.resolve_dependencies()
check("REPRO: mod BLOCKED when installed SVC bundles voicechat_api 2.6.23", "voice_music" not in loaded2, failed2)
check("REPRO: no /music command at all in that case", "music" not in fsrv2.commands)
fsrv2.start()
check("REPRO: Fabric Loader reports the blocked mod in the log",
      any("requires voicechat_api >=2.6.24 but it is not available" in l for l in fsrv2.log), fsrv2.log[-3:])

print("\n=== SCENARIO 4c: REPRODUCE - old descriptor, server on 26.3.1 ===")
fsrv3 = FabricServer(); fsrv3.minecraft_version = "26.3.1"
mod3 = {"fabric.mod.json": {"id": "voice_music", "version": "0.1.0-SNAPSHOT", "depends": old_depends},
        "catalog": cat, "nested_jars": set(AUDIO_ENGINE_JARS)}
mod3["initializer"] = VoiceMusicFabric(fsrv3, mod3)
fsrv3.load_mod(mod3)
fsrv3.load_mod({"fabric.mod.json": {"id": "voicechat_api", "version": "2.6.23"}})
fsrv3.load_mod({"fabric.mod.json": {"id": "fabric-api", "version": "0.161.0"}})
fsrv3.load_mod({"fabric.mod.json": {"id": "fabricloader", "version": "0.19.5"}})
loaded3, failed3 = fsrv3.resolve_dependencies()
check("REPRO: mod BLOCKED on a 26.3.1 server (exact =26.3 pin)", "voice_music" not in loaded3, failed3)
check("REPRO: 26.3.x pin now accepts 26.3.1",
      fakes._semver_match("26.3.1", "26.3.x"))

print("\n=== SCENARIO 4d: REPRODUCE - old build nested only lavaplayer + youtube-source ===")
# loom's include() is non-transitive, so `include "dev.arbjerg:lavaplayer:2.2.7"` nests
# only lavaplayer's main jar. lavaplayer declares api(projects.common), and
# dev.arbjerg:lava-common is where com.sedmelluq.lava.common.tools.DaemonThreadFactory
# lives - a class DefaultAudioPlayerManager's constructor instantiates immediately.
cat2 = Catalog()
shutil.rmtree("/tmp/sim/fdata2", ignore_errors=True)
fsrv4 = FabricServer(); fsrv4.minecraft_version = "26.3"
mod4 = {"fabric.mod.json": {"id": "voice_music", "version": "0.1.0-SNAPSHOT",
                            "depends": {"fabricloader": ">=0.19.3", "minecraft": "26.3.x", "java": ">=25",
                                        "fabric-api": "*", "voicechat": "*", "voicechat_api": "*"}},
        "catalog": cat2,
        "nested_jars": {"lavaplayer", "youtube-source", "gson"}}   # the old build.gradle
mod4["initializer"] = VoiceMusicFabric(fsrv4, mod4)
mod4["voicechat_entrypoint"] = FabricVoicePlugin()
fsrv4.load_mod(mod4)
fsrv4.load_mod({"fabric.mod.json": {"id": "voicechat_api", "version": "2.6.23"}})
fsrv4.load_mod({"fabric.mod.json": {"id": "voicechat", "version": "2.6.23+26.3"}})
fsrv4.load_mod({"fabric.mod.json": {"id": "fabric-api", "version": "0.161.0"}})
fsrv4.load_mod({"fabric.mod.json": {"id": "fabricloader", "version": "0.19.5"}})
fsrv4.start()
check("REPRO: the mod's own classpath is missing dev.arbjerg:lava-common",
      "lava-common" not in mod4["nested_jars"])
check("REPRO: audio engine never started (NoClassDefFoundError DaemonThreadFactory)",
      VoiceMusicFabric.RUNTIME is None
      and any("DaemonThreadFactory" in l for l in fsrv4.log), fsrv4.log[-2:])
check("FIX: /music still registered despite the engine failure", "music" in fsrv4.commands, list(fsrv4.commands)[:5])
fp2 = Player("MissingSteve")
fg2 = Group(uuid.uuid4(), "fab2"); fsrv4.svc.groups[fg2.getId()] = fg2
fsrv4.online_players.append(fp2); fsrv4.svc.players[fp2.uuid] = fp2
fc2 = VoicechatConnection(ServerPlayer(fp2.uuid, "MissingSteve"), fg2, True)
fsrv4.svc.connections[fp2.uuid] = fc2
fsrv4.svc.start()
fsrv4.dispatch({"player": fp2}, "music play never gonna")
msgs = mod4["initializer"].messages
check("FIX: /music play reports the engine is unavailable instead of nothing",
      any("not ready" in m for m in msgs), msgs)
check("FIX: the server kept running (no Fabric Loader mod-init crash)",
      any("Minecraft loaded" in l for l in fsrv4.log))
print("     fabric log tail:", fsrv4.log[-2:])
print("     user messages:", msgs)

print("\n=== SCENARIO 5: Fabric, youtube-source transitive deps missing at PLAYBACK time ===")
# Old build also skipped org.mozilla:rhino-engine and com.grack:nanojson.
shutil.rmtree("/tmp/sim/fdata3", ignore_errors=True)
fsrv5 = FabricServer(); fsrv5.minecraft_version = "26.3"
mod5 = {"fabric.mod.json": {"id": "voice_music", "version": "0.1.0-SNAPSHOT",
                            "depends": {"fabricloader": ">=0.19.3", "minecraft": "26.3.x", "java": ">=25",
                                        "fabric-api": "*", "voicechat": "*", "voicechat_api": "*"}},
        "catalog": cat2,
        "nested_jars": set(AUDIO_ENGINE_JARS) - {"rhino-engine", "nanojson"}}
mod5["initializer"] = VoiceMusicFabric(fsrv5, mod5)
mod5["voicechat_entrypoint"] = FabricVoicePlugin()
fsrv5.load_mod(mod5)
fsrv5.load_mod({"fabric.mod.json": {"id": "voicechat_api", "version": "2.6.23"}})
fsrv5.load_mod({"fabric.mod.json": {"id": "voicechat", "version": "2.6.23+26.3"}})
fsrv5.load_mod({"fabric.mod.json": {"id": "fabric-api", "version": "0.161.0"}})
fsrv5.load_mod({"fabric.mod.json": {"id": "fabricloader", "version": "0.19.5"}})
fsrv5.start()
VoiceMusicFabric.RUNTIME.sources.youtube.nanojson_available = False
fp3 = Player("RhinoSteve")
fg3 = Group(uuid.uuid4(), "fab3"); fsrv5.svc.groups[fg3.getId()] = fg3
fsrv5.online_players.append(fp3); fsrv5.svc.players[fp3.uuid] = fp3
fc3 = VoicechatConnection(ServerPlayer(fp3.uuid, "RhinoSteve"), fg3, True)
fsrv5.svc.connections[fp3.uuid] = fc3
fsrv5.svc.start()
mod5["initializer"].messages.clear()
fsrv5.dispatch({"player": fp3}, "music play https://www.youtube.com/watch?v=dQw4w9WgXcQ")
msgs5 = mod5["initializer"].messages
check("Fabric: YouTube URL playback fails safely with a user-visible reason",
      any("Could not" in m or "failed" in m for m in msgs5), msgs5)
check("Fabric: playback failure never removes the command",
      "music" in fsrv5.commands and "music play" in fsrv5.commands)
print("     fabric log tail:", fsrv5.log[-2:])
print("     user messages:", msgs5)

# =====================================================================
print("\n=== SCENARIO 6: Paper plugin when SVC is not installed at all ===")
srv5, jar5 = build_paper_server("/tmp/sim/data5", svc_registered=False, catalog=cat)
srv5.enable_plugins("STARTUP")
try:
    srv5.enable_plugins("POSTWORLD")
    check("Paper: plugin fails to enable without SVC", False, "should have raised UnknownDependencyException")
except fakes.UnknownDependencyException as e:
    check("Paper: hard dependency on SVC (voicechat) enforced by Bukkit", str(e) == "voicechat")
    check("Paper: no executor when SVC missing", srv5.get_command_map().get("music").executor is None)

# =====================================================================
print("\n=== SCENARIO 8: Paper plugin whose audio engine cannot start ===")
shutil.rmtree("/tmp/sim/data8", ignore_errors=True)
srv8, jar8 = build_paper_server("/tmp/sim/data8", catalog=cat)
jar8["nested_jars"] = {"lavaplayer"}   # e.g. a badly assembled shadowJar
srv8.enable_plugins("STARTUP")
srv8.enable_plugins("POSTWORLD")
cmd8 = srv8.get_command_map().get("music")
check("Paper: /music still exists when the audio engine fails to start", cmd8 is not None and cmd8.executor is not None)
check("Paper: plugin was NOT disabled (used to disable itself and vanish)",
      not any(isinstance(p, VoiceMusicPaper) for p in getattr(srv8, "disabled", set())))
check("Paper: the engine failure is logged loudly",
      any("audio engine" in l and "VoiceMusic" in l for l in srv8.log), srv8.log[-3:])
p8, _ = add_player(srv8, Group(uuid.uuid4(), "g8"), name="PaperSteve")
cmd8.executor.onCommand(p8, cmd8, "music", ["play", "never"])
check("Paper: /music play explains the engine is unavailable",
      any("not ready" in m for m in cmd8.executor.messages), cmd8.executor.messages)
cmd8.executor.messages.clear()
cmd8.executor.onCommand(p8, cmd8, "music", ["help"])
check("Paper: /music help still answers", any("Use /music play" in m for m in cmd8.executor.messages), cmd8.executor.messages)

print("\n=== SCENARIO 9: the real fabric.mod.json in the repo, against real SVC builds ===")
import json as _json, re as _re
_raw = open("/home/user/simple-voice-chat-music-/fabric/src/main/resources/fabric.mod.json").read()
_vars = dict(
    version="0.1.0-SNAPSHOT",
    minecraft_version="26.3",
    minecraft_dependency="26.3.x",
    loader_dependency=">=0.19.3",
)
_filled = _re.sub(r"\$\{(\w+)\}", lambda m: _vars.get(m.group(1), "MISSING_" + m.group(1)), _raw)
desc = _json.loads(_filled)
check("fabric.mod.json: every ${...} placeholder is substituted by build.gradle",
      "MISSING_" not in _filled)
dep = desc["depends"]
check("fabric.mod.json: minecraft range is not an exact pin",
      dep.get("minecraft") not in ("=26.3", "26.3") and "x" in dep.get("minecraft", ""), dep.get("minecraft"))
check("fabric.mod.json: voicechat_api range accepts older SVC builds",
      fakes._semver_match("2.6.23", dep.get("voicechat_api", "")) or dep.get("voicechat_api") == "*",
      dep.get("voicechat_api"))
check("fabric.mod.json: Simple Voice Chat itself is declared as a dependency",
      "voicechat" in dep, list(dep))
check("fabric.mod.json: loader range is not stricter than SVC's own >=0.19.3",
      fakes._semver_match("0.19.3", dep.get("fabricloader", ">=9")))
for mc in ("26.3", "26.3.1", "26.3.2"):
    check(f"fabric.mod.json: accepts Minecraft {mc}", fakes._semver_match(mc, dep["minecraft"]), dep["minecraft"])
for api in ("2.6.20", "2.6.23", "2.6.24", "2.7.0"):
    check(f"fabric.mod.json: accepts voicechat_api {api}", dep["voicechat_api"] == "*")

print("\n=== SCENARIO 10: Paper plugin when the SVC service is absent at runtime ===")
srv10, jar10 = build_paper_server("/tmp/sim/data10", svc_registered=True, catalog=cat)
srv10.enable_plugins("STARTUP")
srv10.services.pop("BukkitVoicechatService", None)   # SVC installed but service not registered
srv10.enable_plugins("POSTWORLD")
cmd10 = srv10.get_command_map().get("music")
check("Paper: /music exists even without the SVC service", cmd10 is not None and cmd10.executor is not None)
check("Paper: plugin not disabled when SVC service is missing",
      not any(isinstance(p, VoiceMusicPaper) for p in getattr(srv10, "disabled", set())))
check("Paper: missing SVC service is logged", any("Simple Voice Chat API service not found" in l for l in srv10.log))
p10, _ = add_player(srv10, Group(uuid.uuid4(), "g10"), name="NoSvcSteve")
cmd10.executor.onCommand(p10, cmd10, "music", ["play", "never"])
check("Paper: /music play explains SVC is unavailable",
      any("not ready" in m or "Simple Voice Chat" in m for m in cmd10.executor.messages), cmd10.executor.messages)

# =====================================================================
print("\n=== SCENARIO 11: regression guards on the real build files ===")
import re as _re2
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")) + "/"
fgradle = open(REPO + "fabric/build.gradle").read()
pgradle = open(REPO + "paper/build.gradle").read()
fj = open(REPO + "fabric/src/main/java/dev/arena/voicemusic/fabric/VoiceMusicFabric.java").read()
pj = open(REPO + "paper/src/main/java/dev/arena/voicemusic/paper/VoiceMusicPaper.java").read()
fmod = _raw

def _strip_gradle_comments(text):
    return "\n".join(_re2.sub(r"//.*$", "", line) for line in text.splitlines())

check("fabric/build.gradle: no hand-written `include` of the audio engine modules",
      'include "dev.arbjerg:lavaplayer' not in _strip_gradle_comments(fgradle)
      and 'include "dev.lavalink.youtube' not in _strip_gradle_comments(fgradle)
      and 'include("dev.arbjerg:lavaplayer' not in _strip_gradle_comments(fgradle),
      "loom include is non-transitive; the nested set must be derived, not enumerated")
check("fabric/build.gradle: the nested set is derived from the runtime classpath",
      "bundledLibraries" in fgradle and "configurations.bundledLibraries.incoming.artifacts" in fgradle)
check("fabric/build.gradle: slf4j is excluded from the nested set (server provides it)",
      "serverProvidedLibraries" in fgradle and "org.slf4j:slf4j-api" in fgradle)
check("fabric/build.gradle: a verification task fails the build if nesting drifts",
      "verifyBundledLibraries" in fgradle and "dependsOn 'verifyBundledLibraries'" in fgradle)
check("fabric/build.gradle: every processResources placeholder is passed by expand",
      "minecraft_dependency" in fgradle and "loader_dependency" in fgradle)
check("paper/build.gradle: shadowJar still bundles the whole runtime classpath",
      "configurations = [" not in pgradle.replace(" ", ""))
check("paper/build.gradle: shadowJar relocates lavaplayer and youtube packages",
      "relocate 'com.sedmelluq.discord.lavaplayer'" in pgradle
      and "relocate 'dev.lavalink.youtube'" in pgradle)
check("fabric.mod.json: no exact minecraft pin", '"=26.3"' not in fmod and '"26.3"' not in fmod)
check("fabric.mod.json: voicechat_api is not version-pinned", '"voicechat_api": "*"' in fmod)
check("fabric.mod.json: Simple Voice Chat itself is a hard dependency",
      '"voicechat": "*"' in fmod)
check("VoiceMusicFabric: no exception escapes onInitialize",
      "throw new IllegalStateException" not in fj)
check("VoiceMusicFabric: CommandRegistrationCallback is registered before the runtime is built",
      fj.index("CommandRegistrationCallback.EVENT.register") < fj.index("new MusicRuntime"))
check("VoiceMusicPaper: no disablePlugin on an audio engine failure",
      "disablePlugin" not in pj)
check("VoiceMusicPaper: command registration happens before the runtime is built",
      pj.index("command.setExecutor(this)") < pj.index("new MusicRuntime"))

# =====================================================================
print("\n=== SCENARIO 7: unit-level parser abuse (20k random inputs) ===")
import random, string
random.seed(0x5eed)
alphabet = "abcXYZ0123:/?&=%[]{}\"\n\t"
bad = 0
for i in range(20000):
    s = "".join(random.choice(alphabet) for _ in range(random.randint(0, 520)))
    try:
        TrackRequest.parse(s)
    except ValueError:
        bad += 1
    except Exception as e:
        check(f"parser must only raise ValueError, got {type(e).__name__} for {s!r}", False, s); break
check("Parser survives 20k adversarial inputs (only ValueError)", True)
try:
    TrackRequest.parse("x" * 501); check("Parser rejects >500 chars", False)
except ValueError: check("Parser rejects >500 chars", True)

print("\n================ SUMMARY ================")
fails = [n for n, ok, _ in RESULTS if not ok]
print(f"{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
for n in fails: print("  FAILED:", n)
sys.exit(1 if fails else 0)
