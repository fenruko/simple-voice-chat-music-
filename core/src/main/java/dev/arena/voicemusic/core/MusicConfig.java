package dev.arena.voicemusic.core;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.Properties;
import java.util.Set;

/** Server-local settings; do not expose the config file or OAuth-related server logs. */
public record MusicConfig(int queueLimit, int volume, boolean youtubeOAuthEnabled, boolean allowArbitraryMediaUrls, String youtubeOAuthRefreshToken, String spotifyClientId, String spotifyClientSecret) {
    public MusicConfig {
        if (queueLimit < 1 || queueLimit > 100) throw new IllegalArgumentException("queueLimit must be 1..100");
        if (volume < 0 || volume > 100) throw new IllegalArgumentException("volume must be 0..100");
        youtubeOAuthRefreshToken = youtubeOAuthRefreshToken == null ? "" : youtubeOAuthRefreshToken.strip();
        spotifyClientId = spotifyClientId == null ? "" : spotifyClientId.strip();
        spotifyClientSecret = spotifyClientSecret == null ? "" : spotifyClientSecret.strip();
    }

    public static MusicConfig load(Path file) throws IOException {
        Properties p = new Properties();
        if (Files.notExists(file)) {
            Files.createDirectories(file.toAbsolutePath().getParent());
            p.setProperty("queue-limit", "50");
            p.setProperty("volume", "80");
            p.setProperty("youtube-oauth-enabled", "false");
            p.setProperty("allow-arbitrary-media-urls", "false");
            p.setProperty("youtube-oauth-refresh-token", "");
            p.setProperty("spotify-client-id", "");
            p.setProperty("spotify-client-secret", "");
            try (var out = Files.newOutputStream(file)) { p.store(out, "Voice Music configuration. Keep this file private."); }
            restrictPermissions(file);
        } else {
            restrictPermissions(file);
            try (var in = Files.newInputStream(file)) { p.load(in); }
        }
        restrictPermissions(file);
        try {
            return new MusicConfig(Integer.parseInt(p.getProperty("queue-limit", "50")),
                    Integer.parseInt(p.getProperty("volume", "80")),
                    parseBoolean(p.getProperty("youtube-oauth-enabled", "false")),
                    parseBoolean(p.getProperty("allow-arbitrary-media-urls", "false")),
                    p.getProperty("youtube-oauth-refresh-token", ""),
                    p.getProperty("spotify-client-id", ""), p.getProperty("spotify-client-secret", ""));
        } catch (IllegalArgumentException ex) {
            throw new IOException("Invalid queue-limit, volume, or boolean setting in " + file + ": " + ex.getMessage(), ex);
        }
    }

    private static boolean parseBoolean(String value) {
        if ("true".equalsIgnoreCase(value)) return true;
        if ("false".equalsIgnoreCase(value)) return false;
        throw new IllegalArgumentException("boolean settings must be true or false");
    }

    public static synchronized void saveYoutubeRefreshToken(Path file, String token) throws IOException {
        if (token == null || token.isBlank()) return;
        Properties properties = new Properties();
        if (Files.exists(file)) { try (var in = Files.newInputStream(file)) { properties.load(in); } }
        if (token.equals(properties.getProperty("youtube-oauth-refresh-token", ""))) return;
        properties.setProperty("youtube-oauth-refresh-token", token);
        Path absolute = file.toAbsolutePath();
        Files.createDirectories(absolute.getParent());
        Path temp = Files.createTempFile(absolute.getParent(), "voice-music-", ".tmp");
        try {
            restrictPermissions(temp);
            try (var out = Files.newOutputStream(temp)) { properties.store(out, "Voice Music config; OAuth refresh token is sensitive. Keep private."); }
            restrictPermissions(temp);
            try { Files.move(temp, absolute, java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE); }
            catch (java.nio.file.AtomicMoveNotSupportedException ignored) { Files.move(temp, absolute, java.nio.file.StandardCopyOption.REPLACE_EXISTING); }
            restrictPermissions(absolute);
        } finally { Files.deleteIfExists(temp); }
    }

    private static void restrictPermissions(Path file) {
        try { Files.setPosixFilePermissions(file, Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE)); }
        catch (UnsupportedOperationException | IOException ignored) { /* Non-POSIX filesystem. */ }
    }
}
