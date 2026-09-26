package dev.arena.voicemusic.fabric;

import de.maxhenkel.voicechat.api.VoicechatApi;
import de.maxhenkel.voicechat.api.VoicechatPlugin;
import de.maxhenkel.voicechat.api.events.EventRegistration;

/** Simple Voice Chat discovers this entrypoint independently of Fabric's main mod entrypoint. */
public final class FabricVoicePlugin implements VoicechatPlugin {
    @Override public String getPluginId() { return "voice_music"; }
    @Override public void initialize(VoicechatApi api) { }
    @Override public void registerEvents(EventRegistration registration) {
        var runtime = VoiceMusicFabric.RUNTIME;
        if (runtime != null) runtime.registerEvents(registration);
    }
}
