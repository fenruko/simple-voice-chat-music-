package dev.arena.voicemusic.core;

import org.junit.jupiter.api.Test;
import java.net.InetAddress;
import static org.junit.jupiter.api.Assertions.*;

class RemoteHostPolicyTest {
    @Test void rejectsLoopbackPrivateLinkLocalAndDocumentationRanges() throws Exception {
        for (String ip : new String[]{"127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.1", "169.254.3.4", "100.64.0.1", "192.0.2.1", "198.51.100.2", "203.0.113.9", "224.0.0.1"}) {
            assertFalse(RemoteHostPolicy.isPublic(InetAddress.getByName(ip)), ip);
        }
        assertFalse(RemoteHostPolicy.isPublic(InetAddress.getByName("::1")));
        assertFalse(RemoteHostPolicy.isPublic(InetAddress.getByName("fd00::1")));
        byte[] mappedLoopback = new byte[16];
        mappedLoopback[10] = (byte) 0xff; mappedLoopback[11] = (byte) 0xff;
        mappedLoopback[12] = 127; mappedLoopback[15] = 1;
        assertFalse(RemoteHostPolicy.isPublic(InetAddress.getByAddress(mappedLoopback)));
    }
    @Test void rejectsCustomPortsAndPrivateNames() {
        assertThrows(IllegalArgumentException.class, () -> RemoteHostPolicy.requirePublicHttpTarget("http://127.0.0.1/music.mp3"));
        assertThrows(IllegalArgumentException.class, () -> RemoteHostPolicy.requirePublicHttpTarget("https://nas.local/audio.mp3"));
        assertThrows(IllegalArgumentException.class, () -> TrackRequest.parse("https://example.com:8443/song.mp3"));
    }
    @Test void acceptsAnExternallyRoutableAddress() throws Exception {
        assertTrue(RemoteHostPolicy.isPublic(InetAddress.getByName("1.1.1.1")));
    }
}
