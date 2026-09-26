package dev.arena.voicemusic.audio;

import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.tools.FriendlyException;
import com.sedmelluq.discord.lavaplayer.track.AudioPlaylist;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import com.sedmelluq.discord.lavaplayer.player.AudioLoadResultHandler;
import de.maxhenkel.voicechat.api.Group;
import de.maxhenkel.voicechat.api.VoicechatConnection;
import de.maxhenkel.voicechat.api.VoicechatServerApi;
import de.maxhenkel.voicechat.api.VolumeCategory;
import de.maxhenkel.voicechat.api.audiochannel.StaticAudioChannel;
import de.maxhenkel.voicechat.api.events.JoinGroupEvent;
import de.maxhenkel.voicechat.api.events.LeaveGroupEvent;
import de.maxhenkel.voicechat.api.events.PlayerDisconnectedEvent;
import de.maxhenkel.voicechat.api.events.VoicechatServerStartedEvent;
import de.maxhenkel.voicechat.api.events.VoicechatServerStoppedEvent;
import de.maxhenkel.voicechat.api.events.EventRegistration;
import de.maxhenkel.voicechat.api.VoicechatPlugin;
import dev.arena.voicemusic.core.MusicConfig;
import dev.arena.voicemusic.core.RemoteHostPolicy;
import dev.arena.voicemusic.core.TrackRequest;
import dev.arena.voicemusic.spotify.SpotifyMetadataClient;

import java.time.Duration;
import java.util.Collection;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Owns source manager, group players, lifecycle and voice-chat listener synchronization. */
public final class MusicRuntime implements VoicechatPlugin, AutoCloseable {
    public static final String VOLUME_CATEGORY = "voice_music";
    private static final int MAX_GROUP_SESSIONS = 32;
    private static final long PLAY_COOLDOWN_NANOS = Duration.ofSeconds(2).toNanos();
    private static final long EMPTY_SESSION_TTL_NANOS = Duration.ofMinutes(2).toNanos();

    private final MusicConfig config;
    private final Supplier<Collection<UUID>> onlinePlayerIds;
    private final Consumer<String> log;
    private final Consumer<String> persistYoutubeToken;
    private final AudioPlayerManager sourceManager;
    private final dev.lavalink.youtube.YoutubeAudioSourceManager youtubeSource;
    private final ScheduledExecutorService ioExecutor;
    private final SpotifyMetadataClient spotify;
    private final Map<UUID, GroupMusicSession> groups = new ConcurrentHashMap<>();
    private final Map<UUID, AtomicLong> lastRequests = new ConcurrentHashMap<>();
    private volatile String lastPersistedYoutubeToken;
    private final Semaphore pendingRequests = new Semaphore(16);
    private volatile VoicechatServerApi voiceApi;
    private volatile boolean closed;

    public MusicRuntime(MusicConfig config, Supplier<Collection<UUID>> onlinePlayerIds, Consumer<String> log, Consumer<String> persistYoutubeToken) {
        this.config = config;
        this.lastPersistedYoutubeToken = config.youtubeOAuthRefreshToken();
        this.onlinePlayerIds = onlinePlayerIds;
        this.log = log;
        this.persistYoutubeToken = persistYoutubeToken;
        AudioSources.RegisteredSources sources = AudioSources.createManager();
        this.sourceManager = sources.manager();
        this.youtubeSource = sources.youtube();
        this.ioExecutor = Executors.newScheduledThreadPool(3, r -> {
            Thread t = new Thread(r, "voice-music-io"); t.setDaemon(true); return t;
        });
        this.spotify = new SpotifyMetadataClient(config.spotifyClientId(), config.spotifyClientSecret(), ioExecutor);
        if (config.youtubeOAuthEnabled()) {
            ioExecutor.execute(this::initializeYouTubeOAuth);
            ioExecutor.scheduleAtFixedRate(this::persistYoutubeOAuthSafely, 5, 15, TimeUnit.SECONDS);
        }
        ioExecutor.scheduleAtFixedRate(this::expireEmptyGroupsSafely, 1, 1, TimeUnit.MINUTES);
    }

    @Override public String getPluginId() { return "voice_music"; }

    @Override public void registerEvents(EventRegistration registration) {
        registration.registerEvent(VoicechatServerStartedEvent.class, this::onVoiceStarted);
        registration.registerEvent(VoicechatServerStoppedEvent.class, this::onVoiceStopped);
        registration.registerEvent(JoinGroupEvent.class, this::onGroupJoin);
        registration.registerEvent(LeaveGroupEvent.class, this::onGroupLeave);
        registration.registerEvent(PlayerDisconnectedEvent.class, this::onPlayerDisconnect);
    }

    private void initializeYouTubeOAuth() {
        try {
            String token = config.youtubeOAuthRefreshToken();
            youtubeSource.useOauth2(token.isBlank() ? null : token, !token.isBlank());
            log.accept(token.isBlank()
                    ? "YouTube device login was requested. Follow the URL/code in the server log and use a secondary account. The upstream source logs the refresh token; keep console logs private. It will be saved to config automatically."
                    : "YouTube OAuth refresh token loaded.");
        } catch (Throwable error) {
            log.accept("YouTube OAuth initialization failed; public unauthenticated sources remain available (" + error.getClass().getSimpleName() + ").");
        }
    }

    private void persistYoutubeOAuthSafely() {
        if (closed || !config.youtubeOAuthEnabled()) return;
        try {
            String token = youtubeSource.getOauth2RefreshToken();
            if (token != null && !token.isBlank() && !token.equals(lastPersistedYoutubeToken)) {
                persistYoutubeToken.accept(token);
                lastPersistedYoutubeToken = token;
            }
        } catch (Throwable error) { log.accept("Could not persist YouTube OAuth refresh token; check server config permissions."); }
    }

    private void onVoiceStarted(VoicechatServerStartedEvent event) {
        voiceApi = event.getVoicechat();
        VolumeCategory category = voiceApi.volumeCategoryBuilder().setId(VOLUME_CATEGORY)
                .setName("Music").setDescription("Music streamed to your Simple Voice Chat group.").build();
        voiceApi.registerVolumeCategory(category);
        log.accept("Simple Voice Chat music bridge is ready.");
    }

    private void onVoiceStopped(VoicechatServerStoppedEvent event) {
        voiceApi = null;
        closeGroups();
    }

    private void onGroupJoin(JoinGroupEvent event) {
        VoicechatConnection connection = event.getConnection();
        Group group = event.getGroup();
        if (group == null) return;
        GroupMusicSession session = groups.get(group.getId());
        if (session != null) session.memberJoined(connection);
    }

    private void onGroupLeave(LeaveGroupEvent event) {
        Group group = event.getGroup();
        if (group == null) return;
        GroupMusicSession session = groups.get(group.getId());
        if (session != null) session.memberLeft(event.getConnection());
    }

    private void onPlayerDisconnect(PlayerDisconnectedEvent event) {
        UUID id = event.getPlayerUuid();
        lastRequests.remove(id);
        groups.values().forEach(s -> s.disconnected(id));
    }

    public void play(UUID playerId, String query, Consumer<String> reply) {
        if (closed) { reply.accept("Music is shutting down."); return; }
        VoicechatServerApi api = voiceApi;
        if (api == null) { reply.accept("Simple Voice Chat is not ready yet."); return; }
        VoicechatConnection connection = api.getConnectionOf(playerId);
        if (connection == null || !connection.isConnected()) { reply.accept("Connect to Simple Voice Chat first."); return; }
        Group group = connection.getGroup();
        if (group == null) { reply.accept("Join a Simple Voice Chat group before starting music."); return; }

        final TrackRequest request;
        try { request = TrackRequest.parse(query); }
        catch (IllegalArgumentException ex) { reply.accept(ex.getMessage()); return; }
        if (request.kind() == TrackRequest.Kind.REMOTE_URL && !config.allowArbitraryMediaUrls()
                && !RemoteHostPolicy.isTrustedMediaProviderUrl(request.input())) {
            reply.accept("Only YouTube and SoundCloud URLs are allowed by default. Set allow-arbitrary-media-urls=true to permit custom hosts.");
            return;
        }
        long now = System.nanoTime();
        AtomicLong clock = lastRequests.computeIfAbsent(playerId, ignored -> new AtomicLong(0));
        long previous = clock.getAndSet(now);
        if (now - previous < PLAY_COOLDOWN_NANOS) { reply.accept("Please wait a moment before requesting another track."); return; }
        if (!pendingRequests.tryAcquire()) { reply.accept("Music is busy resolving other requests. Please retry in a few seconds."); return; }
        AtomicBoolean released = new AtomicBoolean();
        Runnable release = () -> { if (released.compareAndSet(false, true)) pendingRequests.release(); };
        try {
            // Platform commands invoke this on the server thread; snapshot existing group members before any I/O.
            GroupMusicSession session = getOrCreate(group, api);
            reply.accept("Looking up your track request…");
            if (request.kind() == TrackRequest.Kind.SPOTIFY_TRACK) {
                spotify.lookupTrack(request.input()).whenCompleteAsync((metadata, error) -> {
                    if (error != null) { try { reply.accept(userError(error)); } finally { release.run(); } }
                    else loadIntoSession(session, metadata.searchQuery(), reply, release);
                }, ioExecutor).exceptionally(error -> { release.run(); return null; });
                return;
            }
            String identifier = switch (request.kind()) {
                case SEARCH_YOUTUBE -> "ytsearch:" + request.input();
                case SEARCH_SOUNDCLOUD -> "scsearch:" + request.input();
                case REMOTE_URL -> request.input();
                case SPOTIFY_TRACK -> throw new IllegalStateException("Spotify dispatch invariant violated");
            };
            if (request.kind() == TrackRequest.Kind.REMOTE_URL) {
                ioExecutor.execute(() -> {
                    try {
                        RemoteHostPolicy.requirePublicHttpTarget(identifier);
                        loadIntoSession(session, identifier, reply, release);
                    } catch (RuntimeException ex) { try { reply.accept(ex.getMessage()); } finally { release.run(); } }
                });
            } else loadIntoSession(session, identifier, reply, release);
        } catch (IllegalArgumentException | IllegalStateException ex) {
            try { reply.accept(ex.getMessage()); } finally { release.run(); }
        } catch (Throwable ex) {
            log.accept("Music request failed safely: " + ex.getClass().getSimpleName());
            try { reply.accept("Could not start that music request. Check the server log for details."); } finally { release.run(); }
        }
    }

    private void loadIntoSession(GroupMusicSession session, String identifier, Consumer<String> reply, Runnable release) {
        if (closed || session.isClosed()) { try { reply.accept("That voice group music session has expired; try again."); } finally { release.run(); } return; }
        try {
            sourceManager.loadItemOrdered(session, identifier, new AudioLoadResultHandler() {
                @Override public void trackLoaded(AudioTrack track) {
                    try {
                        if (!session.enqueue(track)) reply.accept("The group queue is full (limit " + config.queueLimit() + ").");
                        else reply.accept("Added “" + track.getInfo().title + "” to the group queue.");
                    } catch (Throwable ex) { reply.accept("Could not add that track to the queue."); }
                    finally { release.run(); }
                }
                @Override public void playlistLoaded(AudioPlaylist playlist) {
                    try {
                        int added = 0;
                        int limit = Math.min(playlist.getTracks().size(), config.queueLimit());
                        for (int i = 0; i < limit; i++) {
                            if (!session.enqueue(playlist.getTracks().get(i))) break;
                            added++;
                        }
                        if (playlist.getTracks().size() > limit) reply.accept("Added " + added + " tracks; the playlist was capped to protect the server queue.");
                        else if (added == 0) reply.accept("The queue is full or the playlist is empty.");
                        else reply.accept("Added " + added + " track(s) from “" + playlist.getName() + "”.");
                    } catch (Throwable ex) { reply.accept("Could not queue that playlist."); }
                    finally { release.run(); }
                }
                @Override public void noMatches() {
                    try { reply.accept("No playable tracks found. Try a YouTube/SoundCloud URL or a different search."); }
                    finally { release.run(); }
                }
                @Override public void loadFailed(FriendlyException exception) {
                    try {
                        log.accept("Source load failed (" + exception.severity + "). Details suppressed to avoid leaking source URLs or tokens.");
                        reply.accept("That source could not be loaded. It may be private, region restricted, or temporarily blocked.");
                    } finally { release.run(); }
                }
            });
        } catch (Throwable ex) {
            log.accept("Track resolver rejected a request (" + ex.getClass().getSimpleName() + ").");
            try { reply.accept("Could not resolve that source. Check the URL and retry."); } finally { release.run(); }
        }
    }

    private GroupMusicSession getOrCreate(Group group, VoicechatServerApi api) {
        synchronized (groups) {
            if (closed || voiceApi != api) throw new IllegalStateException("Simple Voice Chat is not ready.");
            GroupMusicSession found = groups.get(group.getId());
            if (found != null && !found.isClosed()) return found;
            if (groups.size() >= MAX_GROUP_SESSIONS) throw new IllegalStateException("Too many active music groups; stop music in an unused group first.");
            GroupMusicSession created = new GroupMusicSession(group, api, sourceManager, config.queueLimit(), config.volume(), onlinePlayerIds,
                    message -> log.accept("[" + group.getName() + "] " + message));
            groups.put(group.getId(), created);
            // Close the join-event race between the constructor snapshot and map publication.
            created.syncOnlinePlayers(onlinePlayerIds.get());
            return created;
        }
    }

    public String skip(UUID playerId) { return forCurrentGroup(playerId, s -> s.skip() ? "Skipped the current track." : "Nothing is playing."); }
    public String pause(UUID playerId) { return forCurrentGroup(playerId, s -> s.pause() ? "Paused." : "Nothing is playing."); }
    public String resume(UUID playerId) { return forCurrentGroup(playerId, s -> s.resume() ? "Resumed." : "Nothing is playing."); }
    public String stop(UUID playerId) { return forCurrentGroup(playerId, s -> { s.stop(); return "Stopped music and cleared the queue."; }); }
    public String now(UUID playerId) { return forCurrentGroup(playerId, GroupMusicSession::nowPlaying); }
    public String queue(UUID playerId) { return forCurrentGroup(playerId, GroupMusicSession::queueSummary); }

    private String forCurrentGroup(UUID playerId, java.util.function.Function<GroupMusicSession, String> action) {
        VoicechatServerApi api = voiceApi;
        if (api == null) return "Simple Voice Chat is not ready.";
        VoicechatConnection connection = api.getConnectionOf(playerId);
        if (connection == null || !connection.isConnected()) return "Connect to Simple Voice Chat first.";
        Group group = connection.getGroup();
        if (group == null) return "Join a Simple Voice Chat group first.";
        GroupMusicSession session = groups.get(group.getId());
        return session == null ? "No music session is active in your group." : action.apply(session);
    }

    private void expireEmptyGroupsSafely() {
        if (closed) return;
        try {
            long now = System.nanoTime();
            groups.entrySet().removeIf(entry -> {
                GroupMusicSession session = entry.getValue();
                if (!session.expireIfIdle(now, EMPTY_SESSION_TTL_NANOS)) return false;
                return true;
            });
        } catch (Throwable error) { log.accept("Idle-session supervisor recovered from an internal error."); }
    }

    private String userError(Throwable error) {
        Throwable cause = error;
        while (cause.getCause() != null) cause = cause.getCause();
        if (cause instanceof IllegalStateException) return cause.getMessage();
        log.accept("Spotify lookup failed: " + cause.getClass().getSimpleName());
        return "Spotify lookup failed. Verify Spotify app credentials and retry.";
    }

    private void closeGroups() {
        synchronized (groups) {
            groups.values().forEach(session -> {
                try { session.close(); }
                catch (RuntimeException error) { log.accept("A voice-group audio session failed to close cleanly."); }
            });
            groups.clear();
        }
    }

    @Override public synchronized void close() {
        if (closed) return;
        closed = true;
        closeGroups();
        try { sourceManager.shutdown(); }
        finally { ioExecutor.shutdownNow(); lastRequests.clear(); }
    }
}
