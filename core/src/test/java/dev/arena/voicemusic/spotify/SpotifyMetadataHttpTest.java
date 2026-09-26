package dev.arena.voicemusic.spotify;

import dev.arena.voicemusic.core.SpotifyTrack;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.concurrent.CompletionException;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

class SpotifyMetadataHttpTest {
    private static final String TRACK_ID = "0123456789012345678901";
    private static final String TOKEN_JSON = "{\"access_token\":\"unit-test-access-token\",\"expires_in\":3600,\"token_type\":\"Bearer\"}";
    private static final String TRACK_JSON = "{\"name\":\"One More Time\",\"artists\":[{\"name\":\"Daft Punk\"}]}";

    @Test void performsClientCredentialsLookupAndCachesTheAccessToken() throws Exception {
        try (MockWebServer server = new MockWebServer(); var executor = Executors.newSingleThreadExecutor()) {
            server.start();
            server.enqueue(json(200, TOKEN_JSON));
            server.enqueue(json(200, TRACK_JSON));
            server.enqueue(json(200, TRACK_JSON));
            var client = client(server, executor);

            SpotifyTrack first = client.lookupTrack(TRACK_ID).get(5, TimeUnit.SECONDS);
            SpotifyTrack second = client.lookupTrack(TRACK_ID).get(5, TimeUnit.SECONDS);

            assertEquals("One More Time", first.title());
            assertEquals("Daft Punk", first.artists());
            assertEquals("ytsearch:One More Time Daft Punk", first.searchQuery());
            assertEquals(first, second);
            assertEquals(3, server.getRequestCount());
            RecordedRequest tokenRequest = server.takeRequest();
            assertEquals("POST", tokenRequest.getMethod());
            assertEquals("Basic " + Base64.getEncoder().encodeToString("app-id:app-secret".getBytes(StandardCharsets.UTF_8)),
                    tokenRequest.getHeader("Authorization"));
            assertTrue(tokenRequest.getBody().readUtf8().contains("grant_type=client_credentials"));
            for (int i = 0; i < 2; i++) {
                RecordedRequest trackRequest = server.takeRequest();
                assertEquals("/v1/tracks/" + TRACK_ID, trackRequest.getPath());
                assertEquals("Bearer unit-test-access-token", trackRequest.getHeader("Authorization"));
            }
        }
    }

    @Test void rateLimitIsReportedWithoutLeakingResponseBody() throws Exception {
        try (MockWebServer server = new MockWebServer(); var executor = Executors.newSingleThreadExecutor()) {
            server.start();
            server.enqueue(json(200, TOKEN_JSON));
            server.enqueue(json(429, "private provider response"));
            CompletionException failure = assertThrows(CompletionException.class,
                    () -> client(server, executor).lookupTrack(TRACK_ID).join());
            assertInstanceOf(IllegalStateException.class, failure.getCause());
            assertEquals("Spotify is rate limiting track lookups. Try again shortly.", failure.getCause().getMessage());
        }
    }

    @Test void rejectedCredentialsProduceAUsefulSanitizedError() throws Exception {
        try (MockWebServer server = new MockWebServer(); var executor = Executors.newSingleThreadExecutor()) {
            server.start();
            server.enqueue(json(401, "secret detail must not escape"));
            CompletionException failure = assertThrows(CompletionException.class,
                    () -> client(server, executor).lookupTrack(TRACK_ID).join());
            assertInstanceOf(IllegalStateException.class, failure.getCause());
            assertEquals("Spotify app authentication failed (HTTP 401).", failure.getCause().getMessage());
        }
    }

    private static SpotifyMetadataClient client(MockWebServer server, java.util.concurrent.Executor executor) {
        return new SpotifyMetadataClient("app-id", "app-secret", executor,
                server.url("/api/token").uri(), server.url("/v1/tracks/").uri());
    }

    private static MockResponse json(int status, String body) {
        return new MockResponse().setResponseCode(status).setHeader("Content-Type", "application/json; charset=utf-8").setBody(body);
    }
}
