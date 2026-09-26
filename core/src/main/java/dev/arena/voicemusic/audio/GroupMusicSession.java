package dev.arena.voicemusic.audio;

import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.player.event.AudioEventAdapter;
import com.sedmelluq.discord.lavaplayer.tools.FriendlyException;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import com.sedmelluq.discord.lavaplayer.track.AudioTrackEndReason;
import de.maxhenkel.voicechat.api.Group;
import de.maxhenkel.voicechat.api.VoicechatConnection;
import de.maxhenkel.voicechat.api.VoicechatServerApi;
import de.maxhenkel.voicechat.api.audiochannel.StaticAudioChannel;
import dev.arena.voicemusic.core.BoundedTrackQueue;
import dev.arena.voicemusic.core.PcmFrameConverter;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** One queue and one SVC channel per voice group. Audio never leaks to other groups. */
public final class GroupMusicSession implements AutoCloseable {
    private final UUID groupId;
    private final String groupName;
    private final VoicechatServerApi voiceApi;
    private final StaticAudioChannel channel;
    private final com.sedmelluq.discord.lavaplayer.player.AudioPlayer player;
    private final BoundedTrackQueue<AudioTrack> queue;
    private final Map<UUID, VoicechatConnection> members = new HashMap<>();
    private final ReentrantLock lock = new ReentrantLock();
    private final Consumer<String> announce;
    private de.maxhenkel.voicechat.api.audiochannel.AudioPlayer voicePlayer;
    private volatile boolean closed;
    private volatile boolean currentActive;
    private volatile long lastMembershipChangeNanos = System.nanoTime();

    public GroupMusicSession(Group group, VoicechatServerApi voiceApi, AudioPlayerManager manager,
                             int queueLimit, int volume, Supplier<Collection<UUID>> onlinePlayers,
                             Consumer<String> announce) {
        this.groupId = group.getId();
        this.groupName = group.getName();
        this.voiceApi = voiceApi;
        this.announce = announce;
        this.queue = new BoundedTrackQueue<>(queueLimit);
        this.channel = voiceApi.createStaticAudioChannel(UUID.randomUUID());
        if (channel == null) throw new IllegalStateException("Simple Voice Chat could not create a music channel.");
        this.channel.setCategory("voice_music");
        this.channel.setBypassGroupIsolation(false);
        this.player = manager.createPlayer();
        this.player.setVolume(volume); // Lavaplayer baseline 100 is normal gain; 80 is 80%.
        this.player.addListener(new TrackEvents());
        for (UUID id : onlinePlayers.get()) addIfMember(voiceApi.getConnectionOf(id));
    }

    public UUID groupId() { return groupId; }
    public String groupName() { return groupName; }
    public String nowPlaying() {
        AudioTrack track = player.getPlayingTrack();
        return track == null ? "Nothing is playing." : "Now playing: " + track.getInfo().title + " — " + track.getInfo().author;
    }
    public int queuedCount() { return queue.size(); }
    public boolean isClosed() { return closed; }
    public int memberCount() { lock.lock(); try { return members.size(); } finally { lock.unlock(); } }
    public boolean shouldExpire(long nowNanos, long ttlNanos) {
        lock.lock(); try { return !closed && members.isEmpty() && nowNanos - lastMembershipChangeNanos >= ttlNanos; }
        finally { lock.unlock(); }
    }
    public boolean expireIfIdle(long nowNanos, long ttlNanos) {
        lock.lock();
        try {
            if (closed || !members.isEmpty() || nowNanos - lastMembershipChangeNanos < ttlNanos) return false;
            closeLocked();
            return true;
        } finally { lock.unlock(); }
    }

    public boolean enqueue(AudioTrack track) {
        lock.lock();
        try {
            if (closed) return false;
            if (!currentActive) {
                currentActive = true;
                player.setPaused(false);
                player.startTrack(track, false);
                return true;
            }
            return queue.offer(track);
        } finally { lock.unlock(); }
    }

    public void memberJoined(VoicechatConnection connection) {
        lock.lock();
        try { addIfMember(connection); }
        finally { lock.unlock(); }
    }

    public void syncOnlinePlayers(Collection<UUID> onlinePlayers) {
        for (UUID id : onlinePlayers) memberJoined(voiceApi.getConnectionOf(id));
    }

    private void addIfMember(VoicechatConnection connection) {
        if (closed || connection == null || !connection.isConnected()) return;
        Group current = connection.getGroup();
        if (current == null || !groupId.equals(current.getId())) return;
        UUID playerId = connection.getPlayerUuid();
        if (members.putIfAbsent(playerId, connection) == null) { channel.addTarget(connection); lastMembershipChangeNanos = System.nanoTime(); }
    }

    public void memberLeft(VoicechatConnection connection) {
        if (connection == null) return;
        lock.lock();
        try { removeMember(connection.getPlayerUuid()); }
        finally { lock.unlock(); }
    }

    public void disconnected(UUID playerId) {
        lock.lock();
        try { removeMember(playerId); }
        finally { lock.unlock(); }
    }

    private void removeMember(UUID playerId) {
        VoicechatConnection removed = members.remove(playerId);
        if (removed != null) { channel.removeTarget(removed); lastMembershipChangeNanos = System.nanoTime(); }
    }

    public boolean skip() {
        lock.lock();
        try {
            if (closed || !currentActive) return false;
            AudioTrack next = queue.poll();
            if (next == null) {
                currentActive = false;
                player.stopTrack();
                player.setPaused(false);
                stopVoicePlayer();
            } else player.playTrack(next);
            return true;
        } finally { lock.unlock(); }
    }

    public boolean pause() {
        lock.lock();
        try { if (closed || !currentActive) return false; player.setPaused(true); return true; }
        finally { lock.unlock(); }
    }
    public boolean resume() {
        lock.lock();
        try { if (closed || !currentActive) return false; player.setPaused(false); return true; }
        finally { lock.unlock(); }
    }

    public void stop() {
        lock.lock();
        try {
            queue.clear();
            currentActive = false;
            player.stopTrack();
            player.setPaused(false);
            stopVoicePlayer();
        } finally { lock.unlock(); }
    }

    public String queueSummary() {
        var items = queue.snapshot();
        if (items.isEmpty()) return "The queue is empty.";
        StringBuilder out = new StringBuilder("Queued tracks (" + items.size() + "): ");
        for (int i = 0; i < Math.min(items.size(), 10); i++) {
            if (i > 0) out.append(" | ");
            out.append(i + 1).append(". ").append(items.get(i).getInfo().title);
        }
        if (items.size() > 10) out.append(" | +").append(items.size() - 10).append(" more");
        return out.toString();
    }

    @Override public void close() {
        lock.lock();
        try {
            closeLocked();
        } finally { lock.unlock(); }
    }

    private void closeLocked() {
        if (closed) return;
        closed = true;
        queue.clear();
        currentActive = false;
        try { stopVoicePlayer(); } catch (RuntimeException ignored) { }
        try { player.destroy(); } catch (RuntimeException ignored) { }
        try { channel.clearTargets(); } catch (RuntimeException ignored) { }
        try { channel.flush(); } catch (RuntimeException ignored) { }
        members.clear();
    }

    private synchronized void ensureVoicePlayer() {
        if (voicePlayer != null || closed) return;
        voicePlayer = voiceApi.createAudioPlayer(channel, voiceApi.createEncoder(), this::nextFrame);
        voicePlayer.startPlaying();
    }

    private short[] nextFrame() {
        if (closed || player.isPaused() || !currentActive || player.getPlayingTrack() == null) return PcmFrameConverter.silence();
        var frame = player.provide();
        if (frame == null) return PcmFrameConverter.silence();
        byte[] data = frame.getData();
        if (data.length != PcmFrameConverter.BYTES_PER_FRAME) return PcmFrameConverter.silence();
        return PcmFrameConverter.decode(data);
    }

    private synchronized void stopVoicePlayer() {
        de.maxhenkel.voicechat.api.audiochannel.AudioPlayer current = voicePlayer;
        voicePlayer = null;
        if (current != null) current.stopPlaying();
    }

    private final class TrackEvents extends AudioEventAdapter {
        @Override public void onTrackStart(com.sedmelluq.discord.lavaplayer.player.AudioPlayer ignored, AudioTrack track) {
            ensureVoicePlayer();
            announce.accept("Now playing in " + groupName + ": " + track.getInfo().title + " — " + track.getInfo().author);
        }
        @Override public void onTrackEnd(com.sedmelluq.discord.lavaplayer.player.AudioPlayer ignored, AudioTrack track, AudioTrackEndReason reason) {
            if (!reason.mayStartNext || closed) return;
            lock.lock();
            try {
                AudioTrack next = queue.poll();
                if (next == null) { currentActive = false; stopVoicePlayer(); }
                else { currentActive = true; player.startTrack(next, false); }
            } finally { lock.unlock(); }
        }
        @Override public void onTrackException(com.sedmelluq.discord.lavaplayer.player.AudioPlayer ignored, AudioTrack track, FriendlyException error) {
            announce.accept("Could not play “" + track.getInfo().title + "”; skipping it.");
            // The following track-end event advances the queue; advancing here too can skip two tracks.
        }
        @Override public void onTrackStuck(com.sedmelluq.discord.lavaplayer.player.AudioPlayer ignored, AudioTrack track, long thresholdMs) {
            announce.accept("Track stalled; skipping it.");
            skipAfterFailure();
        }
        private void skipAfterFailure() {
            lock.lock();
            try {
                AudioTrack next = queue.poll();
                if (next == null) { currentActive = false; player.stopTrack(); stopVoicePlayer(); }
                else { currentActive = true; player.playTrack(next); }
            } finally { lock.unlock(); }
        }
    }
}
