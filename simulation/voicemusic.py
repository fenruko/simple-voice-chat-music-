"""Faithful Python port of dev.arena.voicemusic (core + audio + both platform modules).
Ported line-by-line from the Java sources so behaviour matches."""
import os, re, threading, time, uuid, ipaddress, urllib.parse
from fakes import (AudioPlayerManager, AudioLoadResultHandler, FriendlyException,
                   AudioPlaylist, AudioTrack, AudioFrame, YoutubeSourceManager,
                   LavaplayerYoutubeSourceManager, SoundCloudSourceManager,
                   HttpAudioSourceManager, AudioDataFormat)

# --------------------------------------------------------------- core
class MusicConfig:
    DEFAULTS = dict(**{"queue-limit": "50", "volume": "80", "youtube-oauth-enabled": "false",
                       "allow-arbitrary-media-urls": "false", "youtube-oauth-refresh-token": "",
                       "spotify-client-id": "", "spotify-client-secret": ""})
    def __init__(self, queue_limit=50, volume=80, youtube_oauth_enabled=False,
                 allow_arbitrary_media_urls=False, youtube_oauth_refresh_token="",
                 spotify_client_id="", spotify_client_secret=""):
        if not (1 <= queue_limit <= 100): raise ValueError("queueLimit must be 1..100")
        if not (0 <= volume <= 100): raise ValueError("volume must be 0..100")
        self.queueLimit, self.volume = queue_limit, volume
        self.youtubeOAuthEnabled = youtube_oauth_enabled
        self.allowArbitraryMediaUrls = allow_arbitrary_media_urls
        self.youtubeOAuthRefreshToken = (youtube_oauth_refresh_token or "").strip()
        self.spotifyClientId = (spotify_client_id or "").strip()
        self.spotifyClientSecret = (spotify_client_secret or "").strip()
    @classmethod
    def load(cls, path):
        props = dict(cls.DEFAULTS)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                for k, v in cls.DEFAULTS.items(): f.write(f"{k}={v}\n")
        else:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line: continue
                    k, v = line.split("=", 1); props[k.strip()] = v.strip()
        def boolean(v):
            if v.lower() == "true": return True
            if v.lower() == "false": return False
            raise ValueError("boolean settings must be true or false")
        try:
            return cls(int(props["queue-limit"]), int(props["volume"]),
                       boolean(props["youtube-oauth-enabled"]), boolean(props["allow-arbitrary-media-urls"]),
                       props["youtube-oauth-refresh-token"], props["spotify-client-id"], props["spotify-client-secret"])
        except ValueError as e:
            raise IOError(f"Invalid queue-limit, volume, or boolean setting in {path}: {e}")
    @staticmethod
    def save_youtube_refresh_token(path, token):
        if not token or not token.strip(): return
        props = {}
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1); props[k.strip()] = v.strip()
        if token == props.get("youtube-oauth-refresh-token", ""): return
        props["youtube-oauth-refresh-token"] = token
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            for k, v in props.items(): f.write(f"{k}={v}\n")
        os.replace(tmp, path)

class TrackRequest:
    class Kind:
        SEARCH_YOUTUBE, SEARCH_SOUNDCLOUD, REMOTE_URL, SPOTIFY_TRACK = "SEARCH_YOUTUBE", "SEARCH_SOUNDCLOUD", "REMOTE_URL", "SPOTIFY_TRACK"
    MAX_LENGTH = 500
    def __init__(self, kind, input_): self.kind, self.input = kind, input_
    @staticmethod
    def parse(raw):
        if raw is None: raise ValueError("Enter a song name or a supported URL.")
        text = raw.strip()
        if not text or len(text) > TrackRequest.MAX_LENGTH or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise ValueError("Query must be 1–500 printable characters.")
        lower = text.lower()
        if lower.startswith("spotify:"):
            fields = text.split(":")
            if len(fields) == 3 and fields[1].lower() == "track" and re.fullmatch(r"[A-Za-z0-9]{22}", fields[2]):
                return TrackRequest(TrackRequest.Kind.SPOTIFY_TRACK, fields[2])
            raise ValueError("Only Spotify track links are supported (not albums/playlists yet).")
        if lower.startswith("ytsearch:"):
            return TrackRequest(TrackRequest.Kind.SEARCH_YOUTUBE, TrackRequest._require_search(text[9:]))
        if lower.startswith("scsearch:"):
            return TrackRequest(TrackRequest.Kind.SEARCH_SOUNDCLOUD, TrackRequest._require_search(text[9:]))
        if TrackRequest._looks_like_url(text):
            uri = urllib.parse.urlsplit(text)
            scheme, host = uri.scheme, uri.hostname
            if scheme not in ("http", "https") or not host:
                raise ValueError("Only public HTTP/HTTPS media links are supported.")
            if uri.username or uri.password or host.lower() in ("localhost",) or host.lower().endswith((".localhost", ".local", ".internal")):
                raise ValueError("Private and credential-bearing URLs are not allowed.")
            if uri.port not in (None, 80, 443):
                raise ValueError("Custom ports are not allowed for media URLs.")
            if host.lower() in ("open.spotify.com", "www.open.spotify.com"):
                parts = uri.path.split("/")
                type_index = 1
                if len(parts) > 2 and re.fullmatch(r"(?i)intl-[a-z]{2}(?:-[a-z]{2})?", parts[1]): type_index = 2
                if len(parts) > type_index + 1 and parts[type_index] == "track" and re.fullmatch(r"[A-Za-z0-9]{22}", parts[type_index + 1]):
                    return TrackRequest(TrackRequest.Kind.SPOTIFY_TRACK, parts[type_index + 1])
                raise ValueError("Only Spotify track links are supported (not albums/playlists yet).")
            return TrackRequest(TrackRequest.Kind.REMOTE_URL, text)
        return TrackRequest(TrackRequest.Kind.SEARCH_YOUTUBE, text)
    @staticmethod
    def _looks_like_url(s):
        low = s.lower()
        return low.startswith(("http://", "https://", "file:")) or "://" in low
    @staticmethod
    def _require_search(v):
        t = v.strip()
        if not t: raise ValueError("Search text cannot be empty.")
        return t

class RemoteHostPolicy:
    @staticmethod
    def is_trusted_media_provider_url(raw):
        try:
            host = urllib.parse.urlsplit(raw).hostname
            if not host: return False
            host = host.lower()
            return (host in ("youtu.be", "youtube.com", "soundcloud.com")
                    or host.endswith(".youtube.com") or host.endswith(".soundcloud.com"))
        except ValueError: return False
    @staticmethod
    def require_public_http_target(raw):
        try: uri = urllib.parse.urlsplit(raw)
        except ValueError: raise ValueError("Invalid media URL.")
        host = uri.hostname
        if not host: raise ValueError("Media URL must include a public host.")
        if uri.port not in (None, 80, 443): raise ValueError("Custom ports are not allowed for media URLs.")
        if host.lower().endswith((".localhost", ".local", ".internal")) or host.lower() == "localhost":
            raise ValueError("Private network media URLs are not allowed.")
        try:
            for ip in socket_getaddrinfo(host):
                if not RemoteHostPolicy.is_public(ip): raise ValueError("Private or reserved network addresses are not allowed.")
        except OSError: raise ValueError("The media host could not be resolved.")
    @staticmethod
    def is_public(addr):
        ip = ipaddress.ip_address(addr)
        if ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast: return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return RemoteHostPolicy.is_public(str(ip.ipv4_mapped))
        if isinstance(ip, ipaddress.IPv4Address):
            a, b = ip.packed[0], ip.packed[1]
            if a in (0, 10, 127) or a >= 224: return False
            if a == 100 and 64 <= b <= 127: return False
            if a == 169 and b == 254: return False
            if a == 172 and 16 <= b <= 31: return False
            if a == 192 and b in (0, 168): return False
            if a == 198 and b in (18, 19, 51): return False
            if a == 203 and b == 0: return False
        elif isinstance(ip, ipaddress.IPv6Address):
            if ip in ipaddress.ip_network("fc00::/7"): return False
            if ip in ipaddress.ip_network("2001:db8::/32"): return False
        return True

def socket_getaddrinfo(host):
    """Only resolves literal IPs / hosts listed in the fake DNS table."""
    import socket
    try: return [ipaddress.ip_address(host).compressed]
    except ValueError: pass
    table = {"youtube.com": "142.250.185.78", "www.youtube.com": "142.250.185.78", "youtu.be": "142.250.185.78",
             "soundcloud.com": "143.204.0.10", "on.soundcloud.com": "143.204.0.10",
             "media.example.test": "93.184.216.34", "nas.local": "192.168.1.10",
             "localhost": "127.0.0.1", "internal.example.com": "10.0.0.5"}
    if host in table: return [table[host]]
    raise OSError(f"fake DNS: unknown host {host}")

class BoundedTrackQueue:
    def __init__(self, capacity):
        if not (1 <= capacity <= 10_000): raise ValueError("capacity out of range")
        self.capacity, self.items = capacity, []
    def offer(self, item):
        if item is None: raise ValueError("item")
        if len(self.items) >= self.capacity: return False
        self.items.append(item); return True
    def offer_all(self, batch):
        if batch is None or any(x is None for x in batch) or len(batch) > self.capacity - len(self.items): return False
        self.items.extend(batch); return True
    def poll(self): return self.items.pop(0) if self.items else None
    def peek(self): return self.items[0] if self.items else None
    def size(self): return len(self.items)
    def is_empty(self): return not self.items
    def snapshot(self): return list(self.items)
    def clear(self): self.items = []

class PcmFrameConverter:
    SAMPLE_RATE, SAMPLES_PER_FRAME = 48_000, 960
    BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2
    @staticmethod
    def silence(): return [0] * PcmFrameConverter.SAMPLES_PER_FRAME
    @staticmethod
    def decode(pcm):
        if pcm is None or len(pcm) == 0: return PcmFrameConverter.silence()
        if len(pcm) != PcmFrameConverter.BYTES_PER_FRAME:
            raise ValueError("Expected exactly one 20 ms mono PCM frame")
        import struct
        return list(struct.unpack("<960h", pcm))

# --------------------------------------------------------------- audio
class AudioSources:
    class RegisteredSources:
        def __init__(self, manager, youtube): self.manager, self.youtube = manager, youtube
    @staticmethod
    def create_manager(catalog, classpath=None):
        # First thing createManager() does in the real Java source.
        manager = AudioPlayerManager(classpath)
        manager.catalog = catalog
        manager.getConfiguration().setFilterHotSwapEnabled(True)
        manager.getConfiguration().setOutputFormat(AudioDataFormat(1, 48_000, 960, False))
        manager.setFrameBufferDuration(500)
        youtube = YoutubeSourceManager()
        manager.registerSourceManager(youtube)
        # registerRemoteSources(manager, LavaplayerYoutubeAudioSourceManager.class) -> varargs EXCLUDED sources
        for sm in (SoundCloudSourceManager(), HttpAudioSourceManager()):
            manager.registerSourceManager(sm)
        return AudioSources.RegisteredSources(manager, youtube)

class GroupMusicSession:
    def __init__(self, group, voice_api, manager, queue_limit, volume, online_players, announce):
        self.groupId, self.groupName = group.getId(), group.getName()
        self.voiceApi, self.announce = voice_api, announce
        self.queue = BoundedTrackQueue(queue_limit)
        self.channel = voice_api.createStaticAudioChannel(uuid.uuid4())
        if self.channel is None: raise RuntimeError("Simple Voice Chat could not create a music channel.")
        self.channel.setCategory("voice_music")
        self.channel.setBypassGroupIsolation(False)
        self.player = manager.createPlayer()
        self.player.setVolume(volume)
        self.members = {}
        self.closed = self.currentActive = False
        self.lastMembershipChangeNanos = time.monotonic_ns()
        self.voicePlayer = None
        self._track_events = _TrackEvents(self)
        self.player.addListener(self._track_events)
        for pid in online_players(): self.add_if_member(voice_api.getConnectionOf(pid))
    def now_playing(self):
        t = self.player.getPlayingTrack()
        return "Nothing is playing." if t is None else f"Now playing: {t.info.title} — {t.info.author}"
    def queued_count(self): return self.queue.size()
    def is_closed(self): return self.closed
    def member_count(self): return len(self.members)
    def should_expire(self, now, ttl):
        return (not self.closed) and not self.members and (now - self.lastMembershipChangeNanos) >= ttl
    def expire_if_idle(self, now, ttl):
        if self.closed or self.members or (now - self.lastMembershipChangeNanos) < ttl: return False
        self._close_locked(); return True
    def enqueue(self, track):
        if self.closed: return False
        if not self.currentActive:
            self.currentActive = True
            self.player.setPaused(False)
            self.player.startTrack(track, False)
            return True
        return self.queue.offer(track)
    def member_joined(self, connection): self.add_if_member(connection)
    memberJoined = member_joined
    def sync_online_players(self, players):
        for pid in players: self.member_joined(self.voiceApi.getConnectionOf(pid))
    def add_if_member(self, connection):
        if self.closed or connection is None or not connection.isConnected(): return
        current = connection.getGroup()
        if current is None or self.groupId != current.getId(): return
        pid = connection.getPlayer().getUuid()
        if pid not in self.members:
            self.members[pid] = connection
            self.channel.addTarget(connection)
            self.lastMembershipChangeNanos = time.monotonic_ns()
    def member_left(self, connection):
        if connection is None: return
        self.remove_member(connection.getPlayer().getUuid())
    memberLeft = member_left
    def disconnected(self, pid): self.remove_member(pid)
    def remove_member(self, pid):
        if pid in self.members:
            del self.members[pid]
            self.channel.removeTarget_by_uuid(pid)
            self.lastMembershipChangeNanos = time.monotonic_ns()
    def skip(self):
        if self.closed or not self.currentActive: return False
        nxt = self.queue.poll()
        if nxt is None:
            self.currentActive = False; self.player.stopTrack(); self.player.setPaused(False); self.stop_voice_player()
        else: self.player.playTrack(nxt)
        return True
    def pause(self):
        if self.closed or not self.currentActive: return False
        self.player.setPaused(True); return True
    def resume(self):
        if self.closed or not self.currentActive: return False
        self.player.setPaused(False); return True
    def stop(self):
        self.queue.clear(); self.currentActive = False
        self.player.stopTrack(); self.player.setPaused(False); self.stop_voice_player()
    def queue_summary(self):
        items = self.queue.snapshot()
        if not items: return "The queue is empty."
        out = f"Queued tracks ({len(items)}): "
        for i, t in enumerate(items[:10]):
            if i: out += " | "
            out += f"{i+1}. {t.info.title}"
        if len(items) > 10: out += f" | +{len(items)-10} more"
        return out
    def close(self): self._close_locked()
    def _close_locked(self):
        if self.closed: return
        self.closed = True; self.queue.clear(); self.currentActive = False
        self.stop_voice_player()
        self.player.destroy(); self.channel.clearTargets(); self.channel.flush(); self.members.clear()
    def _ensure_voice_player(self):
        if self.voicePlayer is not None or self.closed: return
        self.voicePlayer = self.voiceApi.createAudioPlayer(self.channel, self.voiceApi.createEncoder(), self._next_frame)
        self.voicePlayer.startPlaying()
    def _next_frame(self):
        if self.closed or self.player.isPaused() or not self.currentActive or self.player.getPlayingTrack() is None:
            return PcmFrameConverter.silence()
        frame = self.player.provide()
        if frame is None: return PcmFrameConverter.silence()
        data = frame.data
        if len(data) != PcmFrameConverter.BYTES_PER_FRAME: return PcmFrameConverter.silence()
        return PcmFrameConverter.decode(data)
    def stop_voice_player(self):
        cur, self.voicePlayer = self.voicePlayer, None
        if cur is not None: cur.stopPlaying()

class _TrackEvents:
    def __init__(self, session): self.s = session
    def onTrackStart(self, player, track):
        self.s._ensure_voice_player()
        self.s.announce(f"Now playing in {self.s.groupName}: {track.info.title} — {track.info.author}")
    def onTrackEnd(self, player, track, reason):
        if not reason.mayStartNext or self.s.closed: return
        nxt = self.s.queue.poll()
        if nxt is None:
            self.s.currentActive = False; self.s.stop_voice_player()
        else:
            self.s.currentActive = True; self.s.player.startTrack(nxt, False)
    def onTrackException(self, player, track, error):
        self.s.announce(f"Could not play “{track.info.title}”; skipping it.")
    def onTrackStuck(self, player, track, threshold):
        self.s.announce("Track stalled; skipping it.")
        nxt = self.s.queue.poll()
        if nxt is None:
            self.s.currentActive = False; self.s.player.stopTrack(); self.s.stop_voice_player()
        else:
            self.s.currentActive = True; self.s.player.playTrack(nxt)

# --------------------------------------------------------------- runtime
class SpotifyMetadataClient:
    def __init__(self, client_id, client_secret, executor):
        self.clientId, self.clientSecret = (client_id or "").strip(), (client_secret or "").strip()
        self.configured = bool(self.clientId and self.clientSecret)
    def is_configured(self): return self.configured
    def lookup_track(self, track_id):
        if not re.fullmatch(r"[A-Za-z0-9]{22}", track_id or ""):
            raise ValueError("Invalid Spotify track ID.")
        if not self.configured:
            raise RuntimeError("Spotify links need Spotify app credentials. Set spotify-client-id and spotify-client-secret in the server config.")
        raise RuntimeError("(simulated) spotify lookup")

class MusicRuntime:
    VOLUME_CATEGORY = "voice_music"
    MAX_GROUP_SESSIONS = 32
    PLAY_COOLDOWN_NANOS = 2 * 10**9
    EMPTY_SESSION_TTL_NANOS = 120 * 10**9
    def __init__(self, config, online_player_ids, log, persist_youtube_token, catalog=None, classpath=None):
        self.config, self.lastPersistedYoutubeToken = config, config.youtubeOAuthRefreshToken
        self.onlinePlayerIds, self.log, self.persistYoutubeToken = online_player_ids, log, persist_youtube_token
        self.sources = AudioSources.create_manager(catalog, classpath)
        self.sourceManager, self.youtubeSource = self.sources.manager, self.sources.youtube
        self.groups, self.lastRequests = {}, {}
        self.pendingRequests = threading.Semaphore(16)
        self.voiceApi, self.closed = None, False
        self.io_thread = threading.Thread(target=self._io_loop, daemon=True); self.io_thread.start()
        self.spotify = SpotifyMetadataClient(config.spotifyClientId, config.spotifyClientSecret, None)
        self.announcements = []
    def _io_loop(self): time.sleep(0.01)
    # ---- SVC plugin surface
    def getPluginId(self): return "voice_music"
    def registerEvents(self, registration):
        registration.registerEvent("VoicechatServerStartedEvent", self.on_voice_started)
        registration.registerEvent("VoicechatServerStoppedEvent", self.on_voice_stopped)
        registration.registerEvent("JoinGroupEvent", self.on_group_join)
        registration.registerEvent("LeaveGroupEvent", self.on_group_leave)
        registration.registerEvent("PlayerDisconnectedEvent", self.on_player_disconnect)
    def on_voice_started(self, event=None):
        self.voiceApi = event.getVoicechat() if event is not None else self._server_api()
        cat = self.voiceApi.volumeCategoryBuilder().setId(self.VOLUME_CATEGORY).setName("Music").setDescription("Music streamed to your Simple Voice Chat group.").build()
        self.voiceApi.registerVolumeCategory(cat)
        self.log("Simple Voice Chat music bridge is ready.")
    def on_voice_stopped(self, event=None):
        self.voiceApi = None; self.close_groups()
    def on_group_join(self, event):
        if event.group is None: return
        s = self.groups.get(event.group.getId())
        if s is not None: s.memberJoined(event.connection)
    def on_group_leave(self, event):
        if event.group is None: return
        s = self.groups.get(event.group.getId())
        if s is not None: s.memberLeft(event.connection)
    def on_player_disconnect(self, event):
        self.lastRequests.pop(event.playerUuid, None)
        for s in list(self.groups.values()): s.disconnected(event.playerUuid)
    def _server_api(self): return self._api
    # ---- commands
    def play(self, player_id, query, reply):
        if self.closed: return reply("Music is shutting down.")
        api = self.voiceApi
        if api is None: return reply("Simple Voice Chat is not ready yet.")
        connection = api.getConnectionOf(player_id)
        if connection is None or not connection.isConnected(): return reply("Connect to Simple Voice Chat first.")
        group = connection.getGroup()
        if group is None: return reply("Join a Simple Voice Chat group before starting music.")
        try: request = TrackRequest.parse(query)
        except ValueError as e: return reply(str(e))
        if request.kind == TrackRequest.Kind.REMOTE_URL and not self.config.allowArbitraryMediaUrls \
                and not RemoteHostPolicy.is_trusted_media_provider_url(request.input):
            return reply("Only YouTube and SoundCloud URLs are allowed by default. Set allow-arbitrary-media-urls=true to permit custom hosts.")
        now = time.monotonic_ns()
        prev = self.lastRequests.get(player_id, 0)
        self.lastRequests[player_id] = now
        if now - prev < self.PLAY_COOLDOWN_NANOS: return reply("Please wait a moment before requesting another track.")
        if not self.pendingRequests.acquire(blocking=False):
            return reply("Music is busy resolving other requests. Please retry in a few seconds.")
        class _Release:
            def __init__(self, rt): self.rt, self.done = rt, False
            def run(self):
                if not self.done: self.done = True; self.rt.pendingRequests.release()
        release = _Release(self)
        try:
            session = self.get_or_create(group, api)
            reply("Looking up your track request…")
            if request.kind == TrackRequest.Kind.SPOTIFY_TRACK:
                try:
                    md = self.spotify.lookup_track(request.input)
                    self.load_into_session(session, md, reply, release)
                except Exception as e:
                    try: reply(self._user_error(e))
                    finally: release.run()
                return
            identifier = {TrackRequest.Kind.SEARCH_YOUTUBE: "ytsearch:" + request.input,
                          TrackRequest.Kind.SEARCH_SOUNDCLOUD: "scsearch:" + request.input,
                          TrackRequest.Kind.REMOTE_URL: request.input}[request.kind]
            if request.kind == TrackRequest.Kind.REMOTE_URL:
                try:
                    RemoteHostPolicy.require_public_http_target(identifier)
                    self.load_into_session(session, identifier, reply, release)
                except Exception as e:
                    try: reply(str(e))
                    finally: release.run()
            else:
                self.load_into_session(session, identifier, reply, release)
        except (ValueError, RuntimeError) as e:
            try: reply(str(e))
            finally: release.run()
        except Exception as e:
            self.log(f"Music request failed safely: {type(e).__name__}")
            try: reply("Could not start that music request. Check the server log for details.")
            finally: release.run()
    def load_into_session(self, session, identifier, reply, release):
        if self.closed or session.is_closed():
            try: reply("That voice group music session has expired; try again.")
            finally: release.run()
            return
        try:
            self.sourceManager.loadItemOrdered(session, identifier, _Handler(self, session, reply, release))
        except Exception as e:
            self.log(f"Track resolver rejected a request ({type(e).__name__}).")
            try: reply("Could not resolve that source. Check the URL and retry.")
            finally: release.run()
    def get_or_create(self, group, api):
        if self.closed or self.voiceApi is not api: raise RuntimeError("Simple Voice Chat is not ready.")
        found = self.groups.get(group.getId())
        if found is not None and not found.is_closed(): return found
        if len(self.groups) >= self.MAX_GROUP_SESSIONS:
            raise RuntimeError("Too many active music groups; stop music in an unused group first.")
        created = GroupMusicSession(group, api, self.sourceManager, self.config.queueLimit, self.config.volume,
                                    self.onlinePlayerIds, lambda m: self.log(f"[{group.getName()}] {m}"))
        self.groups[group.getId()] = created
        created.sync_online_players(self.onlinePlayerIds())
        return created
    def skip(self, pid): return self.for_current_group(pid, lambda s: "Skipped the current track." if s.skip() else "Nothing is playing.")
    def pause(self, pid): return self.for_current_group(pid, lambda s: "Paused." if s.pause() else "Nothing is playing.")
    def resume(self, pid): return self.for_current_group(pid, lambda s: "Resumed." if s.resume() else "Nothing is playing.")
    def stop(self, pid): return self.for_current_group(pid, lambda s: (s.stop(), "Stopped music and cleared the queue.")[1])
    def now(self, pid): return self.for_current_group(pid, lambda s: s.now_playing())
    def queue(self, pid): return self.for_current_group(pid, lambda s: s.queue_summary())
    def for_current_group(self, pid, action):
        api = self.voiceApi
        if api is None: return "Simple Voice Chat is not ready."
        connection = api.getConnectionOf(pid)
        if connection is None or not connection.isConnected(): return "Connect to Simple Voice Chat first."
        group = connection.getGroup()
        if group is None: return "Join a Simple Voice Chat group first."
        session = self.groups.get(group.getId())
        return "No music session is active in your group." if session is None else action(session)
    def expire_empty_groups(self):
        if self.closed: return
        now = time.monotonic_ns()
        for gid, s in list(self.groups.items()):
            if s.expire_if_idle(now, self.EMPTY_SESSION_TTL_NANOS): del self.groups[gid]
    def close_groups(self):
        for s in list(self.groups.values()):
            try: s.close()
            except Exception: self.log("A voice-group audio session failed to close cleanly.")
        self.groups.clear()
    def close(self):
        if self.closed: return
        self.closed = True; self.close_groups()
        try: self.sourceManager.shutdown()
        finally: self.lastRequests.clear()
    def _user_error(self, error):
        cause = error
        while getattr(cause, "__cause__", None) is not None: cause = cause.__cause__
        if isinstance(cause, RuntimeError): return str(cause)
        self.log(f"Spotify lookup failed: {type(cause).__name__}")
        return "Spotify lookup failed. Verify Spotify app credentials and retry."

class _Handler(AudioLoadResultHandler):
    def __init__(self, runtime, session, reply, release):
        self.rt, self.s, self.reply, self.release = runtime, session, reply, release
    def trackLoaded(self, track):
        try:
            if not self.s.enqueue(track): self.reply(f"The group queue is full (limit {self.rt.config.queueLimit}).")
            else: self.reply(f"Added “{track.info.title}” to the group queue.")
        finally: self.release.run()
    def playlistLoaded(self, playlist):
        try:
            added = 0
            limit = min(len(playlist.tracks), self.rt.config.queueLimit)
            for i in range(limit):
                if not self.s.enqueue(playlist.tracks[i]): break
                added += 1
            if len(playlist.tracks) > limit: self.reply(f"Added {added} tracks; the playlist was capped to protect the server queue.")
            elif added == 0: self.reply("The queue is full or the playlist is empty.")
            else: self.reply(f"Added {added} track(s) from “{playlist.name}”.")
        finally: self.release.run()
    def noMatches(self):
        try: self.reply("No playable tracks found. Try a YouTube/SoundCloud URL or a different search.")
        finally: self.release.run()
    def loadFailed(self, exception):
        try:
            self.rt.log(f"Source load failed ({exception.severity}). Details suppressed to avoid leaking source URLs or tokens.")
            self.reply("That source could not be loaded. It may be private, region restricted, or temporarily blocked.")
        finally: self.release.run()
