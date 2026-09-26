package dev.arena.voicemusic.core;

import org.junit.jupiter.api.Test;
import java.util.Random;
import static org.junit.jupiter.api.Assertions.*;

class TrackRequestTest {
    private static final String SPOTIFY_ID = "0123456789012345678901";

    @Test void normalTextDefaultsToYoutubeSearch() {
        assertEquals(new TrackRequest(TrackRequest.Kind.SEARCH_YOUTUBE, "Daft Punk One More Time"), TrackRequest.parse(" Daft Punk One More Time "));
    }
    @Test void explicitSoundcloudSearchIsRecognized() {
        assertEquals(TrackRequest.Kind.SEARCH_SOUNDCLOUD, TrackRequest.parse("scsearch: jazz mix").kind());
    }
    @Test void spotifyWebAndUriLinksParseToTrackId() {
        assertEquals(new TrackRequest(TrackRequest.Kind.SPOTIFY_TRACK, SPOTIFY_ID), TrackRequest.parse("spotify:track:" + SPOTIFY_ID));
        assertEquals(SPOTIFY_ID, TrackRequest.parse("https://open.spotify.com/track/" + SPOTIFY_ID + "?si=abc").input());
        assertEquals(SPOTIFY_ID, TrackRequest.parse("https://open.spotify.com/intl-en/track/" + SPOTIFY_ID).input());
    }
    @Test void permitsHttpAndHttpsButRejectsCredentialsAndPrivateAliases() {
        assertEquals(TrackRequest.Kind.REMOTE_URL, TrackRequest.parse("https://www.youtube.com/watch?v=abcdefghijk").kind());
        assertFalse(RemoteHostPolicy.isTrustedMediaProviderUrl("https://media.example.test/music.mp3"));
        assertTrue(RemoteHostPolicy.isTrustedMediaProviderUrl("https://on.soundcloud.com/example"));
        assertFalse(RemoteHostPolicy.isTrustedMediaProviderUrl("https://youtube.com.attacker.example/video"));
        assertThrows(IllegalArgumentException.class, () -> TrackRequest.parse("file:///etc/passwd"));
        assertThrows(IllegalArgumentException.class, () -> TrackRequest.parse("https://user:pass@example.test/a.mp3"));
        assertThrows(IllegalArgumentException.class, () -> TrackRequest.parse("http://localhost/a.mp3"));
    }
    @Test void parserSurvivesDeterministicAdversarialInput() {
        Random random = new Random(0x5eed);
        String alphabet = "abcXYZ0123:/?&=%\\[]{}\"\n\t";
        for (int i = 0; i < 20_000; i++) {
            int length = random.nextInt(520);
            StringBuilder input = new StringBuilder(length);
            for (int j = 0; j < length; j++) input.append(alphabet.charAt(random.nextInt(alphabet.length())));
            try { assertNotNull(TrackRequest.parse(input.toString())); }
            catch (IllegalArgumentException expected) { /* expected for malformed/unbounded input */ }
        }
    }

    @Test void rejectsMalformedSpotifyAndControlInput() {
        assertThrows(IllegalArgumentException.class, () -> TrackRequest.parse("spotify:album:" + SPOTIFY_ID));
        assertThrows(IllegalArgumentException.class, () -> TrackRequest.parse(" \n"));
        assertThrows(IllegalArgumentException.class, () -> TrackRequest.parse("x".repeat(501)));
    }
}
