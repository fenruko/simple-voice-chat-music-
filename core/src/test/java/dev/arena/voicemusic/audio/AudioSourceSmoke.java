package dev.arena.voicemusic.audio;

import com.sedmelluq.discord.lavaplayer.player.AudioPlayer;
import com.sedmelluq.discord.lavaplayer.tools.FriendlyException;
import com.sedmelluq.discord.lavaplayer.track.playback.AudioFrame;
import com.sedmelluq.discord.lavaplayer.track.AudioPlaylist;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import com.sedmelluq.discord.lavaplayer.player.AudioLoadResultHandler;

import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/** Optional network smoke test: resolves a real source and decodes one PCM frame. */
public final class AudioSourceSmoke {
    private AudioSourceSmoke() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass one public media URL");
        AudioSources.RegisteredSources sources = AudioSources.createManager();
        AudioPlayer player = sources.manager().createPlayer();
        CompletableFuture<AudioTrack> loaded = new CompletableFuture<>();
        try {
            sources.manager().loadItemOrdered(AudioSourceSmoke.class, args[0], new AudioLoadResultHandler() {
                @Override public void trackLoaded(AudioTrack track) { loaded.complete(track); }
                @Override public void playlistLoaded(AudioPlaylist playlist) {
                    if (playlist.getTracks().isEmpty()) loaded.completeExceptionally(new IllegalStateException("Empty playlist"));
                    else loaded.complete(playlist.getTracks().get(0));
                }
                @Override public void noMatches() { loaded.completeExceptionally(new IllegalStateException("No playable source found")); }
                @Override public void loadFailed(FriendlyException exception) {
                    loaded.completeExceptionally(new IllegalStateException("Source load failed: " + exception.severity + " (" + exception.getClass().getSimpleName() + ")"));
                }
            });

            AudioTrack track = loaded.get(60, TimeUnit.SECONDS);
            if (!player.startTrack(track, false)) throw new IllegalStateException("Audio player rejected the resolved track");
            long deadline = System.nanoTime() + Duration.ofSeconds(30).toNanos();
            AudioFrame frame = null;
            while (System.nanoTime() < deadline) {
                frame = player.provide();
                if (frame != null && frame.getData() != null && frame.getData().length > 0) break;
                Thread.sleep(20);
            }
            if (frame == null || frame.getData() == null || frame.getData().length == 0) {
                throw new IllegalStateException("Resolved the track but received no decoded audio frame within 30 seconds");
            }
            System.out.printf("Source smoke passed: resolved '%s' and decoded a %d-byte PCM frame.%n",
                    track.getInfo().title, frame.getData().length);
        } finally {
            player.stopTrack();
            sources.manager().shutdown();
        }
    }
}
