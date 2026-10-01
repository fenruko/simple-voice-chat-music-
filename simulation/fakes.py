"""Simulated platform: Bukkit/Paper, Simple Voice Chat API, Lavaplayer, Fabric Loader.
Semantics mirror the real upstream implementations (verified against upstream source)."""
import re, uuid, time, threading, queue
from enum import Enum

# ---------------------------------------------------------------- lavaplayer
class NoClassDefFoundError(Exception):
    """java.lang.NoClassDefFoundError, the JVM's signature for 'this jar was not shipped'."""
    def __init__(self, cls): super().__init__(cls); self.missing_class = cls

class FriendlyException(Exception):
    def __init__(self, msg, severity="COMMON"):
        super().__init__(msg); self.severity = severity

class AudioDataFormat:
    def __init__(self, channels, rate, chunk, big_endian):
        self.channelCount, self.sampleRate, self.chunkSampleCount, self.bigEndian = channels, rate, chunk, big_endian

class AudioFrame:
    def __init__(self, data, fmt, nano=None): self.data, self.format, self.timecode = data, fmt, nano

class AudioTrack:
    def __init__(self, title, author, uri, duration_ms=180000):
        self.identifier = uri
        self.info = type("Info", (), {"title": title, "author": author, "uri": uri, "length": duration_ms})()
    def __repr__(self): return f"<Track {self.info.title}>"

class AudioPlaylist:
    def __init__(self, name, tracks): self.name, self.tracks = name, tracks

class AudioItem: pass
NO_TRACK = "NO_TRACK"

class AudioLoadResultHandler:
    def trackLoaded(self, t): pass
    def playlistLoaded(self, p): pass
    def noMatches(self): pass
    def loadFailed(self, e): pass

class AudioEventAdapter:
    def onTrackStart(self, player, track): pass
    def onTrackEnd(self, player, track, reason): pass
    def onTrackException(self, player, track, err): pass
    def onTrackStuck(self, player, track, threshold): pass

class AudioTrackEndReason(Enum):
    FINISHED = "FINISHED"; LOAD_FAILED = "LOAD_FAILED"; STOPPED = "STOPPED"; REPLACED = "REPLACED"; CLEANUP = "CLEANUP"
    @property
    def mayStartNext(self): return self in (AudioTrackEndReason.FINISHED, AudioTrackEndReason.LOAD_FAILED)

class AudioPlayer:
    def __init__(self, manager):
        self._manager, self._track, self._paused, self._volume = manager, None, False, 100
        self._listeners, self._destroyed = [], False
    def setVolume(self, v): self._volume = v
    def getVolume(self): return self._volume
    def addListener(self, l): self._listeners.append(l)
    def setPaused(self, p): self._paused = p
    def isPaused(self): return self._paused
    def startTrack(self, track, interrupt=True):
        self._track = track; self._paused = False
        for l in self._listeners: l.onTrackStart(self, track)
        return True
    def playTrack(self, track): return self.startTrack(track)
    def stopTrack(self):
        if self._track is not None:
            t, self._track = self._track, None
            for l in self._listeners: l.onTrackEnd(self, t, AudioTrackEndReason.STOPPED)
    def getPlayingTrack(self): return self._track
    def provide(self):
        if self._track is None or self._paused or self._destroyed: return None
        return AudioFrame(b"\0" * 1920, self._manager.output_format)
    def destroy(self): self._destroyed = True

class SourceManager:
    def getSourceName(self): return self.__class__.__name__
    def loadItem(self, manager, reference): return None

class YoutubeSourceManager(SourceManager):
    """dev.lavalink.youtube.YoutubeAudioSourceManager (1.18.2)."""
    def __init__(self, allow_search=True, allow_direct_video_ids=True, allow_direct_playlist_ids=True):
        self.allowSearch = allow_search
        self.allowDirectVideoIds, self.allowDirectPlaylistIds = allow_direct_video_ids, allow_direct_playlist_ids
        self._oauth_token, self._oauth_enabled = None, False
        self.rhino_available = True    # toggled by the Fabric scenario (rhino not JiJ'd)
        self.nanojson_available = True  # toggled by the Fabric scenario (nanojson not JiJ'd)
    def getSourceName(self): return "youtube"
    def useOauth2(self, refresh_token, skip_initialization):
        self._oauth_token, self._oauth_enabled = refresh_token, True
    def getOauth2RefreshToken(self): return self._oauth_token
    def loadItem(self, manager, reference):
        ident = reference.identifier
        if ident.startswith("ytsearch:") or ident.startswith("ytmsearch:"):
            if not self.allowSearch: return None
            q = ident.split(":", 1)[1]
            return AudioPlaylist(f"Search results for {q}", manager.catalog.search(q))
        if re.match(r"^(https?://)?(www\.|m\.|music\.)?youtube\.com/", ident) or re.match(r"^(https?://)?(www\.)?youtu\.be/", ident):
            # youtube-source parses player responses with com.grack.nanojson and evaluates the
            # signature cipher with org.mozilla:rhino-engine. Neither is an `include`d module of
            # its own, so a build that nests only `dev.lavalink.youtube` ships neither.
            if not self.nanojson_available:
                raise NoClassDefFoundError("com/grack/nanojson/JsonParser")
            if not self.rhino_available:
                raise NoClassDefFoundError("org/mozilla/javascript/Script")
            return AudioPlaylist("YouTube playlist", manager.catalog.by_url(ident))
        return None

class SoundCloudSourceManager(SourceManager):
    def getSourceName(self): return "soundcloud"
    def loadItem(self, manager, reference):
        ident = reference.identifier
        if ident.startswith("scsearch:"):
            q = ident.split(":", 1)[1]
            return AudioPlaylist(f"SC search: {q}", manager.catalog.search(q))
        if re.match(r"^(https?://)?(www\.|on\.)?soundcloud\.com/", ident):
            return AudioPlaylist("SoundCloud", manager.catalog.by_url(ident))
        return None

class HttpAudioSourceManager(SourceManager):
    def getSourceName(self): return "http"
    def loadItem(self, manager, reference):
        if reference.identifier.startswith("http"):
            return manager.catalog.by_url(reference.identifier)
        return None

class LavaplayerYoutubeSourceManager(SourceManager):
    """Deprecated built-in lavaplayer youtube source (excluded by the repo)."""
    def getSourceName(self): return "youtube(lavaplayer)"

class AudioPlayerManager:
    """dev.arbjerg:lavaplayer DefaultAudioPlayerManager.

    `classpath` is the set of jar names actually shipped with the mod. It defaults to
    None meaning "assume complete" so unrelated tests stay focused.

    lavaplayer's main module declares `api(projects.common)`; dev.arbjerg:lava-common is
    what holds com.sedmelluq.lava.common.tools.DaemonThreadFactory, and the constructor
    instantiates it immediately. Loom's `include` nests only the module you name, so a
    Fabric build that nests just `dev.arbjerg:lavaplayer` dies here on the first line.
    """
    def __init__(self, classpath=None):
        if classpath is not None and "lava-common" not in classpath:
            raise NoClassDefFoundError("com/sedmelluq/lava/common/tools/DaemonThreadFactory")
        self.source_managers, self.config = [], {}
        self.output_format, self.frame_buffer_duration = AudioDataFormat(2, 48000, 960, True), None
        self.catalog = None
    def registerSourceManager(self, sm): self.source_managers.append(sm)
    def createPlayer(self): return AudioPlayer(self)
    def setFrameBufferDuration(self, ms): self.frame_buffer_duration = ms
    def getConfiguration(self): return self
    def setFilterHotSwapEnabled(self, b): self.config["filterHotSwap"] = b
    def setOutputFormat(self, fmt): self.output_format = fmt
    def shutdown(self): self.source_managers = []
    def loadItemOrdered(self, ordering, identifier, handler):
        """Real lavaplayer executes on a manager-internal executor; the handler is
        invoked asynchronously (or synchronously for 'no match')."""
        results = []
        def run():
            try:
                for sm in self.source_managers:
                    item = sm.loadItem(self, type("Ref", (), {"identifier": identifier})())
                    if item is NO_TRACK:
                        results.append(("nomatch", None)); return
                    if item is None: continue
                    if isinstance(item, AudioPlaylist):
                        if item.tracks: results.append(("playlist", item))
                        else: results.append(("nomatch", None))
                    else: results.append(("track", item))
                    return
                results.append(("nomatch", None))
            except FriendlyException as e:
                results.append(("failed", e))
            except Exception as e:  # e.g. NoClassDefFoundError in real life
                results.append(("error", e))
        t = threading.Thread(target=run, daemon=True); t.start(); t.join(5)
        kind, payload = (results or [("error", TimeoutError("load timed out"))])[0]
        if kind == "track": handler.trackLoaded(payload)
        elif kind == "playlist": handler.playlistLoaded(payload)
        elif kind == "nomatch": handler.noMatches()
        elif kind == "failed": handler.loadFailed(payload)
        else:
            # lavaplayer would propagate; the repo catches Throwable
            raise payload

# ---------------------------------------------------------------- SVC API
class VolumeCategory:
    def __init__(self, id, name, description): self.id, self.name, self.description = id, name, description

class Group:
    def __init__(self, id, name, isolated=False):
        self.id, self.name, self.isolated = id, name, isolated
    def getId(self): return self.id
    def getName(self): return self.name

class ServerPlayer:
    def __init__(self, uuid, name): self.uuid, self.name = uuid, name
    def getUuid(self): return self.uuid

class VoicechatConnection:
    def __init__(self, player, group, connected=True):
        self._player, self._group, self._connected = player, group, connected
    def getPlayer(self): return self._player
    def getGroup(self): return self._group
    def isConnected(self): return self._connected
    def __repr__(self): return f"<Conn {self._player.name}>"

class StaticAudioChannel:
    def __init__(self, channel_id, server):
        self.channelId, self.server = channel_id, server
        self.targets, self.bypassGroupIsolation, self.category = set(), True, None
        self.sent, self.closed, self.flushed = [], False, False
    def getId(self): return self.channelId
    def setBypassGroupIsolation(self, b): self.bypassGroupIsolation = b
    def bypassesGroupIsolation(self): return self.bypassGroupIsolation
    def addTarget(self, c): self.targets.add(c.getPlayer().getUuid())
    def removeTarget(self, c): self.targets.discard(c.getPlayer().getUuid())
    def removeTarget_by_uuid(self, pid): self.targets.discard(pid)
    def clearTargets(self): self.targets = set()
    def setCategory(self, c): self.category = c
    def getCategory(self): return self.category
    def flush(self): self.flushed = True
    def send(self, opus): self.sent.append(opus)

class ApiAudioPlayer:
    """de.maxhenkel.voicechat.api.audiochannel.AudioPlayer"""
    def __init__(self, channel, encoder, supplier):
        self.channel, self.supplier, self.started = channel, supplier, False
        self.frames_pushed = 0
    def startPlaying(self): self.started = True
    def stopPlaying(self): self.started = False
    def tick(self):
        if not self.started: return
        frame = self.supplier()
        if frame is not None:
            self.channel.send(frame); self.frames_pushed += 1

class VoicechatServerApi:
    def __init__(self, server): self.server = server
    def createStaticAudioChannel(self, channel_id): return StaticAudioChannel(channel_id, self.server)
    def createAudioPlayer(self, channel, encoder, supplier): return ApiAudioPlayer(channel, encoder, supplier)
    def createEncoder(self): return "opus-encoder"
    def volumeCategoryBuilder(self):
        api = self
        class B:
            def __init__(self): self._id = self._name = self._desc = None
            def setId(self, i):
                self._id = i; return self
            def setName(self, n): self._name = n; return self
            def setDescription(self, d): self._desc = d; return self
            def build(self):
                if not self._id or not re.fullmatch(r"[a-z_]{1,16}", self._id or ""):
                    raise ValueError(f"Invalid volume category id: {self._id!r}")
                return VolumeCategory(self._id, self._name, self._desc)
        return B()
    def registerVolumeCategory(self, c): self.server.volume_categories[c.id] = c
    def getConnectionOf(self, player_uuid): return self.server.connections.get(player_uuid)
    def getGroups(self): return list(self.server.groups.values())
    def getGroup(self, gid): return self.server.groups.get(gid)

class VoicechatServer:
    """de.maxhenkel.voicechat.voice.server.Server + PluginManager"""
    def __init__(self):
        self.players, self.connections, self.groups = {}, {}, {}
        self.volume_categories, self.registered_plugins, self.event_handlers = {}, [], {}
        self.started, self.log = False, []
        self.api = VoicechatServerApi(self)
    def start(self):
        self.started = True
        self.log.append("Loading plugins")
        for p in self.registered_plugins: self.log.append(f"Loaded plugin {p.getPluginId()}")
        for p in self.registered_plugins:
            p.initialize(self.api)
        self.log.append("Initialized plugins")
        for p in self.registered_plugins:
            self.log.append(f"Registering events for {p.getPluginId()}")
            p.registerEvents(_EventRegistration(self))
        self.log.append("Registered events")
        self.dispatch("VoicechatServerStartedEvent", _StartedEvent(self.api))
    def dispatch(self, name, *args):
        for h in self.event_handlers.get(name, []):
            try: h(*args)
            except Exception as e: self.log.append(f"Failed to dispatch event '{name}': {e}")

class _StartedEvent:
    def __init__(self, api): self._api = api
    def getVoicechat(self): return self._api

class _EventRegistration:
    def __init__(self, server): self.server = server
    def registerEvent(self, event_class, handler, priority=0):
        self.server.event_handlers.setdefault(event_class, []).append(handler)

# ---------------------------------------------------------------- Bukkit/Paper
class PluginCommand:
    def __init__(self, name, description, usage, permission):
        self.name, self.description, self.usage, self.permission = name, description, usage, permission
        self.executor = self.tab_completer = None
    def setExecutor(self, e): self.executor = e
    def setTabCompleter(self, t): self.tab_completer = t

def _parse_plugin_yml(raw):
    """Minimal YAML subset parser: scalars, `[a, b]` inline lists and one level of
    nested mappings. Enough for a Bukkit plugin.yml, and it keeps this simulation
    dependency-free so it runs anywhere (including CI) without pyyaml."""
    root = {}
    doc, stack = root, [(-1, root)]
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        value = value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            child = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        if value.startswith("[") and value.endswith("]"):
            parent[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            parent[key] = value.strip("'\"")
    return doc

class PluginDescriptionFile:
    def __init__(self, raw):
        self.doc = _parse_plugin_yml(raw)
        self.name = self.doc["name"]; self.main = self.doc["main"]
        self.depend = self.doc.get("depend", []); self.load = self.doc.get("load", "POSTWORLD")
        self.commands = self.doc.get("commands", {})
    def getDepend(self): return self.depend

class UnknownDependencyException(Exception): pass

class PaperServer:
    """Mirrors CraftServer/SimplePluginManager/JavaPluginLoader ordering."""
    def __init__(self):
        self.plugin_descriptors, self.command_map, self.services = {}, {}, {}
        self.online_players, self.scheduler, self.enabled, self.log = [], [], set(), []
        self.plugin_data_folders, self.plugin_meta, self.disabled = {}, {}, set()
        self.svc = VoicechatServer()
    # --- plugin loading
    def load_plugin(self, jar):
        desc = PluginDescriptionFile(jar["plugin.yml"])
        self.plugin_descriptors[desc.name] = (jar, desc)
        self.plugin_meta[desc.name] = "legacy"
        for cname, spec in desc.commands.items():
            self.command_map[cname] = PluginCommand(cname, spec.get("description", ""), spec.get("usage", ""), spec.get("permission"))
            self.command_map[desc.name.lower() + ":" + cname] = self.command_map[cname]
        self.plugin_data_folders[desc.name] = jar.get("data_folder")
    def get_plugin(self, name): return name if name in self.plugin_descriptors else None
    def enable_plugins(self, order):
        for name in sorted(self.plugin_descriptors):
            jar, desc = self.plugin_descriptors[name]
            if desc.load != order or name in self.enabled: continue
            for dep in desc.depend:
                if self.get_plugin(dep) is None:
                    raise UnknownDependencyException(dep)
            self.enabled.add(name)
            self.log.append(f"[{name}] Enabling {desc.name}")
            jar["main_class"](self, jar).onEnable()
    def get_services_manager(self):
        srv = self
        class SM:
            def load(self, cls): return srv.services.get(cls if isinstance(cls, str) else cls.__name__)
            def register(self, cls, impl, plugin, priority): srv.services[cls.__name__] = impl
        return SM()
    def get_online_players(self): return list(self.online_players)
    def run_task(self, plugin, fn): fn()
    def get_command_map(self): return self.command_map
    def dispatch_command(self, sender, label, args):
        cmd = self.command_map.get(label)
        if cmd is None: return "Unknown command"
        if cmd.executor is None: return "No executor"
        return cmd.executor.on_command(sender, cmd, label, args)

class FabricServer:
    """Mirrors Fabric Loader mod loading + brigadier registration."""
    def __init__(self):
        self.mods, self.commands, self.log = {}, {}, []
        self.command_registration_callbacks = []
        self.online_players, self.svc = [], VoicechatServer()
        self.config_dir = "/tmp/sim/config"
        self.dispatched = {}
    def load_mod(self, mod):
        self.mods[mod["fabric.mod.json"]["id"]] = mod
    def resolve_dependencies(self):
        """Fabric Loader: mod with unsatisfiable depends is not loaded at all."""
        loaded, failed = {}, {}
        for mod_id, mod in self.mods.items():
            depends = mod["fabric.mod.json"].get("depends", {})
            bad = []
            for dep, range_ in depends.items():
                if dep == "minecraft":
                    if not _semver_match(self.minecraft_version, range_): bad.append(f"{dep} {range_}")
                elif dep == "java":
                    if not _semver_match("25", range_): bad.append(f"{dep} {range_}")
                else:
                    prov = self.mods.get(dep)
                    if prov is None or not _semver_match(prov["fabric.mod.json"]["version"], range_):
                        bad.append(f"{dep} {range_}")
            if bad: failed[mod_id] = bad
            else: loaded[mod_id] = mod
        return loaded, failed
    def start(self):
        self.log.append("Loading Minecraft")
        loaded, failed = self.resolve_dependencies()
        for mid, why in failed.items():
            self.log.append(f"Mod {mid} requires {', '.join(why)} but it is not available!")
        for mid, mod in loaded.items():
            self.log.append(f"Loading {len(loaded)} mods:\n\t - {mid} {mod['fabric.mod.json']['version']}")
            init = mod.get("initializer")
            if init is not None:
                try:
                    init.onInitialize()
                except Exception as e:
                    # Fabric Loader's Knot aborts the whole mod init stage.
                    raise RuntimeError(f"Could not execute entrypoint stage 'main', provided by '{mid}' mod!") from e
        # SVC discovers Fabric plugins via FabricLoader.getEntrypointContainers("voicechat", ...)
        self.svc.registered_plugins = [m["voicechat_entrypoint"] for m in loaded.values() if "voicechat_entrypoint" in m]
        self.svc.start()
        for cb in self.command_registration_callbacks:
            cb(None, None, None)   # brigadier dispatcher registration
        self.log.append("Minecraft loaded")
    def register_command(self, literal, handler):
        self.commands[literal] = handler
    def dispatch(self, source, line):
        parts = line.split()
        # brigadier: longest matching literal chain wins
        for n in range(len(parts), 0, -1):
            lit = " ".join(parts[:n])
            if lit in self.commands:
                return self.commands[lit](source, parts[n:])
        return f"Unknown command: {line}"

def _semver_match(version, range_):
    """Very small subset of Fabric version predicates.

    Supports '*', exact equality, the comparison operators, and the x/X wildcard that
    Fabric semver uses for "any value in this position" (e.g. "26.3.x").
    """
    range_ = range_.strip()
    if range_ == "*": return True
    m = re.match(r"^(>=|<=|>|<|=)?\s*(.+)$", range_)
    op, want = (m.group(1) or "="), m.group(2).strip()
    def parse(v):
        return [int(x) for x in re.findall(r"\d+", v)][:3]
    a = parse(version); a += [0] * (3 - len(a))
    # Split the wanted version, remembering which positions are wildcards.
    b, wild = [], []
    for part in re.split(r"[.\-+]", want)[:3]:
        if part.lower() == "x" or part == "*":
            b.append(0); wild.append(True)
        else:
            d = re.findall(r"\d+", part)
            b.append(int(d[0]) if d else 0); wild.append(False)
    b += [0] * (3 - len(b)); wild += [False] * (3 - len(wild))
    if op in ("=", "=="):
        return all(wild[i] or a[i] == b[i] for i in range(3))
    if op == ">=": return a >= b
    if op == "<=": return a <= b
    if op == ">":  return a > b
    if op == "<":  return a < b
    return False
