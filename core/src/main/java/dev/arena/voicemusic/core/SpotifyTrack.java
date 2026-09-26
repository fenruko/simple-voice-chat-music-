package dev.arena.voicemusic.core;

import java.util.Objects;

public record SpotifyTrack(String title, String artists, String searchQuery) {
    public SpotifyTrack {
        Objects.requireNonNull(title);
        Objects.requireNonNull(artists);
        Objects.requireNonNull(searchQuery);
        if (title.isBlank() || artists.isBlank()) throw new IllegalArgumentException("Spotify metadata was incomplete");
    }
}
