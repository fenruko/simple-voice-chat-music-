package dev.arena.voicemusic.core;

import dev.arena.voicemusic.spotify.SpotifyMetadataClient;
import org.junit.jupiter.api.Test;
import java.util.concurrent.Executors;
import static org.junit.jupiter.api.Assertions.*;

class SpotifyMetadataClientTest {
    @Test void noCredentialsFailFastWithoutNetworkAccess() {
        try (var executor = Executors.newSingleThreadExecutor()) {
            var client = new SpotifyMetadataClient("", "", executor);
            assertFalse(client.isConfigured());
            var error = assertThrows(java.util.concurrent.CompletionException.class,
                    () -> client.lookupTrack("0123456789012345678901").join());
            assertInstanceOf(IllegalStateException.class, error.getCause());
            assertTrue(error.getCause().getMessage().contains("credentials"));
        }
    }
    @Test void malformedIdsAreRejected() {
        try (var executor = Executors.newSingleThreadExecutor()) {
            var client = new SpotifyMetadataClient("id", "secret", executor);
            assertThrows(java.util.concurrent.CompletionException.class, () -> client.lookupTrack("not-an-id").join());
        }
    }
    @Test void spotifyTrackRequiresMetadataAndSearchText() {
        assertEquals("Daft Punk", new SpotifyTrack("One More Time", "Daft Punk", "ytsearch:One More Time Daft Punk").artists());
        assertThrows(IllegalArgumentException.class, () -> new SpotifyTrack("", "Artist", "query"));
    }
}
