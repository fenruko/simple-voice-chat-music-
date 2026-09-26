package dev.arena.voicemusic.core;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.Set;
import static org.junit.jupiter.api.Assertions.*;

class MusicConfigTest {
    @TempDir Path temp;

    @Test void createsSafeDefaultsAndKeepsOAuthOffUntilExplicitlyEnabled() throws Exception {
        Path file = temp.resolve("voice-music.properties");
        MusicConfig config = MusicConfig.load(file);
        assertEquals(50, config.queueLimit());
        assertEquals(80, config.volume());
        assertFalse(config.youtubeOAuthEnabled());
        assertFalse(config.allowArbitraryMediaUrls());
        assertEquals("", config.youtubeOAuthRefreshToken());
        assertTrue(Files.isRegularFile(file));
    }

    @Test void oauthTokenPersistenceIsAtomicAndPreservesOtherSettings() throws Exception {
        Path file = temp.resolve("voice-music.properties");
        Files.writeString(file, "queue-limit=17\nvolume=62\nyoutube-oauth-enabled=true\nallow-arbitrary-media-urls=true\nspotify-client-id=client\nspotify-client-secret=secret\n");
        MusicConfig.saveYoutubeRefreshToken(file, "refresh-token-value");
        MusicConfig loaded = MusicConfig.load(file);
        assertEquals(17, loaded.queueLimit());
        assertEquals(62, loaded.volume());
        assertTrue(loaded.youtubeOAuthEnabled());
        assertTrue(loaded.allowArbitraryMediaUrls());
        assertEquals("refresh-token-value", loaded.youtubeOAuthRefreshToken());
        assertEquals("client", loaded.spotifyClientId());
        assertEquals("secret", loaded.spotifyClientSecret());
        try {
            assertEquals(Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE), Files.getPosixFilePermissions(file));
        } catch (UnsupportedOperationException ignored) { /* Non-POSIX filesystem. */ }
        try (var files = Files.list(temp)) {
            assertTrue(files.noneMatch(path -> path.getFileName().toString().endsWith(".tmp")));
        }
    }

    @Test void invalidConfigFailsWithActionableIOException() throws Exception {
        Path file = temp.resolve("bad.properties");
        Files.writeString(file, "queue-limit=not-a-number\n");
        assertTrue(assertThrows(java.io.IOException.class, () -> MusicConfig.load(file)).getMessage().contains("Invalid queue-limit"));
        Files.writeString(file, "youtube-oauth-enabled=maybe\n");
        assertTrue(assertThrows(java.io.IOException.class, () -> MusicConfig.load(file)).getMessage().contains("boolean setting"));
    }
}
