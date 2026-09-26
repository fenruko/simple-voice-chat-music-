package dev.arena.voicemusic.audio;

import com.sedmelluq.discord.lavaplayer.format.Pcm16AudioDataFormat;
import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.player.DefaultAudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.source.AudioSourceManagers;
import dev.lavalink.youtube.YoutubeAudioSourceManager;


/** Source registration deliberately excludes Lavaplayer's deprecated built-in YouTube implementation. */
public final class AudioSources {
    private AudioSources() { }

    public record RegisteredSources(AudioPlayerManager manager, YoutubeAudioSourceManager youtube) { }

    public static RegisteredSources createManager() {
        AudioPlayerManager manager = new DefaultAudioPlayerManager();
        manager.getConfiguration().setFilterHotSwapEnabled(true);
        manager.getConfiguration().setOutputFormat(new Pcm16AudioDataFormat(1, 48_000, 960, false));
        manager.setFrameBufferDuration(500);
        YoutubeAudioSourceManager youtube = new YoutubeAudioSourceManager();
        manager.registerSourceManager(youtube);
        AudioSourceManagers.registerRemoteSources(manager,
                com.sedmelluq.discord.lavaplayer.source.youtube.YoutubeAudioSourceManager.class);
        return new RegisteredSources(manager, youtube);
    }
}
