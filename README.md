# Voice Music

Server-side music streaming for Simple Voice Chat. This project builds two **separate** server artifacts: a Fabric mod and a Paper plugin. The server resolves and decodes supported sources locally with Lavaplayer and streams 48 kHz mono PCM through the Simple Voice Chat API; it does not need Lavalink or a separate music host.

## Current scope

- `/music play <query or URL>` searches YouTube for plain text; supports YouTube URLs, SoundCloud URLs/search (`scsearch:`), and Spotify track URLs. Custom public HTTP(S) media hosts are opt-in.
- Spotify **track** URLs are resolved with Spotify Web API app credentials, then mirrored to a YouTube search result. Spotify itself is metadata-only here. Spotify albums/playlists are not supported yet.
- Each SVC group has its own queue and output channel. The plugin selects targets by group UUID and updates targets as players join/leave. Music is not broadcast to other groups.
- `/music queue`, `/music now`, `/music skip`, `/music pause`, `/music resume`, `/music stop` and `/music gui` are available. `gui` shows clickable chat buttons. A custom screen would require an additional client-side mod.
- Queue length, per-player request cooldown, active group count, playback cleanup, URL validation, and OAuth/Spotify configuration are bounded. Arbitrary HTTP hosts are disabled by default; enable `allow-arbitrary-media-urls=true` only if you trust requesters, because DNS rebinding and redirects are not fully prevented for arbitrary hosts.

## Server requirements

- Build/runtime: Java 25 for Minecraft 26.3.
- Simple Voice Chat must be installed on the server and on every client that should hear music.
- Install **only the artifact matching the server software**. Paper and Fabric cannot run together in one server.
- ViaVersion/ViaBackwards do not translate the separate Simple Voice Chat connection. Test the installed SVC client versions with your exact server/version mix before relying on voice playback.
- The server needs outbound HTTPS access to the selected media source. Some providers restrict automated playback or change their APIs.

## Install

1. Install the matching 26.3 Simple Voice Chat server build.
2. Put `voice-music-fabric-*.jar` in a Fabric server's `mods/` folder, **or** `voice-music-paper-*.jar` in a Paper server's `plugins/` folder.
3. Restart. Run `/music help` in game. The plugin creates `voice-music.properties` in its config/data folder on first start.
4. Join the same Simple Voice Chat group as your friend, then run `/music play <song or URL>`.

### Spotify setup
Spotify links require a Spotify developer app. Put its Client ID and Client Secret in `voice-music.properties` (`spotify-client-id` and `spotify-client-secret`). These are stable app credentials, not session cookies. Keep the file private. The plugin resolves the Spotify title/artist and searches YouTube for a playable match; it never streams Spotify's protected audio directly.

### YouTube login (optional)
Anonymous playback may work for public videos, but YouTube can block automated requests. To enable the source library's official device OAuth flow, set `youtube-oauth-enabled=true` and restart. Complete the URL/code shown in the server console, preferably with a secondary account. The plugin saves the resulting refresh token to `voice-music.properties` with owner-only file permissions where supported, then the source library refreshes access tokens automatically. **The upstream source logs the refresh token once during device authorization: keep Aternos console/log access private. No YouTube cookie file is used.** If you prefer no account login, leave this setting false and use sources that work anonymously (such as public SoundCloud tracks).

## Build and test

```sh
./gradlew :core:test :fabric:build :paper:build
```

The `core` suite covers parser abuse cases, URL/private-network defenses, PCM frame sizes/byte order, concurrent queue limits, configuration/token persistence, and SVC group-target isolation/cleanup. `.github/workflows/verify.yml` runs the tests, builds both jars on Java 25, checks the packaged descriptors, and uploads build artifacts.

### Release validation still required

The tests are unit/mocked tests; they cannot prove source-provider availability or SVC voice transport across ViaVersion client/server combinations. Before calling a build production-ready, install it on both target server types and run the acceptance checks below with two real clients:

1. Same SVC group: play a short public SoundCloud track; both hear it.
2. Different SVC group: verify those users hear nothing.
3. Join/leave the group while audio is playing; targets update without restart.
4. Check play/search, queue cap, skip, pause/resume, stop, server shutdown, and reconnect.
5. Exercise YouTube anonymously and with optional OAuth; test one Spotify track with credentials.
6. Confirm no private URL/IP is fetched and no Spotify app credentials or personal data appear in logs. If OAuth is enabled, the upstream library will print its refresh token during device authorization; keep those logs private. If you explicitly enable arbitrary media hosts, separately test redirects and DNS behavior in a restricted environment.

This repo starts as a clean implementation; it has not yet been exercised against a live Minecraft server in this environment.
