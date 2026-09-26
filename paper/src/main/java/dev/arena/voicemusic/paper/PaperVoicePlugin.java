package dev.arena.voicemusic.paper;

import de.maxhenkel.voicechat.api.VoicechatApi;
import de.maxhenkel.voicechat.api.VoicechatPlugin;
import de.maxhenkel.voicechat.api.events.EventRegistration;
import dev.arena.voicemusic.audio.MusicRuntime;

final class PaperVoicePlugin implements VoicechatPlugin {
    private final MusicRuntime runtime;
    PaperVoicePlugin(MusicRuntime runtime) { this.runtime = runtime; }
    @Override public String getPluginId() { return "voice_music"; }
    @Override public void initialize(VoicechatApi api) { }
    @Override public void registerEvents(EventRegistration registration) { runtime.registerEvents(registration); }
}
