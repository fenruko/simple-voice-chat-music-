package dev.arena.voicemusic.spotify;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import dev.arena.voicemusic.core.SpotifyTrack;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import java.util.StringJoiner;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;

/** Spotify is metadata-only here; playback is mirrored through the configured YouTube search source. */
public final class SpotifyMetadataClient {
    private final String clientId;
    private final String clientSecret;
    private final HttpClient http;
    private final Executor executor;
    private final URI tokenEndpoint;
    private final URI trackEndpointBase;
    private volatile CachedToken cached;

    public SpotifyMetadataClient(String clientId, String clientSecret, Executor executor) {
        this(clientId, clientSecret, executor, URI.create("https://accounts.spotify.com/api/token"),
                URI.create("https://api.spotify.com/v1/tracks/"));
    }

    SpotifyMetadataClient(String clientId, String clientSecret, Executor executor, URI tokenEndpoint, URI trackEndpointBase) {
        this.clientId = clientId == null ? "" : clientId.strip();
        this.clientSecret = clientSecret == null ? "" : clientSecret.strip();
        this.executor = executor;
        this.tokenEndpoint = tokenEndpoint;
        this.trackEndpointBase = trackEndpointBase;
        this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(8))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    public boolean isConfigured() { return !clientId.isBlank() && !clientSecret.isBlank(); }

    public CompletableFuture<SpotifyTrack> lookupTrack(String id) {
        if (id == null || !id.matches("[A-Za-z0-9]{22}")) return CompletableFuture.failedFuture(new IllegalArgumentException("Invalid Spotify track ID."));
        if (!isConfigured()) return CompletableFuture.failedFuture(new IllegalStateException("Spotify links need Spotify app credentials. Set spotify-client-id and spotify-client-secret in the server config."));
        return CompletableFuture.supplyAsync(() -> {
            try {
                String token = token();
                HttpRequest request = HttpRequest.newBuilder(URI.create(trackEndpointBase.toString() + id))
                        .timeout(Duration.ofSeconds(10)).header("Authorization", "Bearer " + token).GET().build();
                HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() == 429) throw new IllegalStateException("Spotify is rate limiting track lookups. Try again shortly.");
                if (response.statusCode() == 401 || response.statusCode() == 403) {
                    cached = null;
                    throw new IllegalStateException("Spotify rejected its app credentials. Check the server config.");
                }
                if (response.statusCode() != 200) throw new IllegalStateException("Spotify track lookup failed (HTTP " + response.statusCode() + ").");
                JsonObject json = JsonParser.parseString(response.body()).getAsJsonObject();
                String title = json.get("name").getAsString();
                StringJoiner artists = new StringJoiner(" ");
                json.getAsJsonArray("artists").forEach(a -> artists.add(a.getAsJsonObject().get("name").getAsString()));
                String artistText = artists.toString();
                return new SpotifyTrack(title, artistText, "ytsearch:" + title + " " + artistText);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("Spotify lookup was interrupted.", ex);
            } catch (Exception ex) {
                if (ex instanceof RuntimeException runtime) throw runtime;
                throw new IllegalStateException("Spotify metadata could not be loaded.", ex);
            }
        }, executor);
    }

    private synchronized String token() throws Exception {
        long now = System.nanoTime();
        if (cached != null && cached.expiresAtNanos > now) return cached.value;
        String credentials = Base64.getEncoder().encodeToString((clientId + ":" + clientSecret).getBytes(StandardCharsets.UTF_8));
        String body = "grant_type=" + URLEncoder.encode("client_credentials", StandardCharsets.UTF_8);
        HttpRequest request = HttpRequest.newBuilder(tokenEndpoint)
                .timeout(Duration.ofSeconds(10)).header("Authorization", "Basic " + credentials)
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(HttpRequest.BodyPublishers.ofString(body)).build();
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) throw new IllegalStateException("Spotify app authentication failed (HTTP " + response.statusCode() + ").");
        JsonObject json = JsonParser.parseString(response.body()).getAsJsonObject();
        long expires = Math.max(60, json.get("expires_in").getAsLong());
        cached = new CachedToken(json.get("access_token").getAsString(), now + Duration.ofSeconds(expires - 30).toNanos());
        return cached.value;
    }

    private record CachedToken(String value, long expiresAtNanos) { }
}
