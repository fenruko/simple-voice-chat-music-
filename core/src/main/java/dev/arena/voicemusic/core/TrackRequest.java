package dev.arena.voicemusic.core;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.Objects;

/** Parsed and validated input accepted by /music play. */
public record TrackRequest(Kind kind, String input) {
    public enum Kind { SEARCH_YOUTUBE, SEARCH_SOUNDCLOUD, REMOTE_URL, SPOTIFY_TRACK }

    private static final int MAX_LENGTH = 500;

    public TrackRequest {
        Objects.requireNonNull(kind, "kind");
        Objects.requireNonNull(input, "input");
    }

    public static TrackRequest parse(String raw) {
        if (raw == null) throw new IllegalArgumentException("Enter a song name or a supported URL.");
        String input = raw.strip();
        if (input.isEmpty() || input.length() > MAX_LENGTH || input.chars().anyMatch(Character::isISOControl)) {
            throw new IllegalArgumentException("Query must be 1–500 printable characters.");
        }
        String lower = input.toLowerCase(Locale.ROOT);
        if (lower.startsWith("spotify:")) {
            String[] fields = input.split(":");
            if (fields.length == 3 && fields[1].equalsIgnoreCase("track") && fields[2].matches("[A-Za-z0-9]{22}")) {
                return new TrackRequest(Kind.SPOTIFY_TRACK, fields[2]);
            }
            throw new IllegalArgumentException("Only Spotify track links are supported (not albums/playlists yet).");
        }
        if (lower.startsWith("ytsearch:")) {
            return new TrackRequest(Kind.SEARCH_YOUTUBE, requireSearchText(input.substring(9)));
        }
        if (lower.startsWith("scsearch:")) {
            return new TrackRequest(Kind.SEARCH_SOUNDCLOUD, requireSearchText(input.substring(9)));
        }
        if (looksLikeUrl(input)) {
            URI uri;
            try { uri = new URI(input); }
            catch (URISyntaxException ex) { throw new IllegalArgumentException("That URL is malformed."); }
            String scheme = uri.getScheme();
            String host = uri.getHost();
            if (scheme == null || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https")) || host == null) {
                throw new IllegalArgumentException("Only public HTTP/HTTPS media links are supported.");
            }
            if (uri.getUserInfo() != null || host.equalsIgnoreCase("localhost") || host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".internal")) {
                throw new IllegalArgumentException("Private and credential-bearing URLs are not allowed.");
            }
            if (uri.getPort() != -1 && uri.getPort() != 80 && uri.getPort() != 443) throw new IllegalArgumentException("Custom ports are not allowed for media URLs.");
            if (host.equalsIgnoreCase("open.spotify.com") || host.equalsIgnoreCase("www.open.spotify.com")) {
                String[] parts = uri.getPath().split("/");
                int typeIndex = 1;
                if (parts.length > 2 && parts[1].matches("(?i)intl-[a-z]{2}(?:-[a-z]{2})?")) typeIndex = 2;
                if (parts.length > typeIndex + 1 && parts[typeIndex].equals("track")
                        && parts[typeIndex + 1].matches("[A-Za-z0-9]{22}")) {
                    return new TrackRequest(Kind.SPOTIFY_TRACK, parts[typeIndex + 1]);
                }
                throw new IllegalArgumentException("Only Spotify track links are supported (not albums/playlists yet).");
            }
            if (host.equalsIgnoreCase("soundcloud.com") || host.equalsIgnoreCase("www.soundcloud.com") || host.equalsIgnoreCase("on.soundcloud.com")) {
                return new TrackRequest(Kind.REMOTE_URL, uri.toASCIIString());
            }
            return new TrackRequest(Kind.REMOTE_URL, uri.toASCIIString());
        }
        return new TrackRequest(Kind.SEARCH_YOUTUBE, input);
    }

    private static boolean looksLikeUrl(String s) {
        String lower = s.toLowerCase(Locale.ROOT);
        return lower.startsWith("http://") || lower.startsWith("https://") || lower.startsWith("file:") || lower.contains("://");
    }

    private static String requireSearchText(String value) {
        String text = value.strip();
        if (text.isEmpty()) throw new IllegalArgumentException("Search text cannot be empty.");
        return text;
    }
}
