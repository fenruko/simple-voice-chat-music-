# Why `/music` did not exist - simulation and proof

This directory contains a self-contained Python simulation of a live server: Bukkit/Paper
plugin loading, Simple Voice Chat's plugin/service model, Lavaplayer's player manager and
source managers, and Fabric Loader's mod loading with its `depends` gate. The ports in
`voicemusic.py` follow the Java sources line by line.

```sh
cd simulation && python3 run_tests.py
```

88 checks, all passing. Scenarios 4b/4c/4d are labelled `REPRO` on purpose: they
reconstruct the *broken* build to show the symptom the user reported, so the diagnosis
cannot silently regress.

## The reported symptom

> "when i use it on my server literally nothing happens, i see no command to play at all"

`/music` is registered by the plugin/mod itself, so a missing command means the artifact
never reached its enable/init stage. Both platforms had ways to make that happen.

## Root cause 1 - the Fabric jar did not ship its own runtime dependencies

`fabric/build.gradle` used

```gradle
include("dev.arbjerg:lavaplayer:${lavaplayer_version}") { ... }
include "dev.lavalink.youtube:v2:${youtube_source_version}"
```

Loom's `include` configuration is resolved **non-transitively** - see
`IncludeConfigurations#addNonTransitiveDependencies` in `fabric-loom`, which explicitly
builds a resolving configuration from `source.getIncoming().getDependencies()` only. So
those two lines nested *only* `lavaplayer`'s main jar and *only* youtube-source's jar.

`lavaplayer`'s main module declares `api(projects.common)`, and `dev.arbjerg:lava-common`
is the artifact that holds `com.sedmelluq.lava.common.tools.DaemonThreadFactory`.
`DefaultAudioPlayerManager`'s constructor instantiates it immediately:

```java
trackInfoExecutorService = ExecutorsTools.createEagerlyScalingExecutor(
        1, DEFAULT_LOADER_POOL_SIZE, TimeUnit.SECONDS.toMillis(30), LOADER_QUEUE_CAPACITY,
        new DaemonThreadFactory("info-loader"));
```

and `AudioSources.createManager()` - the very first thing `new MusicRuntime(...)` does -
calls `new DefaultAudioPlayerManager()`. On a Fabric server that is

```
NoClassDefFoundError: com/sedmelluq/lava/common/tools/DaemonThreadFactory
```

which the old `VoiceMusicFabric.onInitialize()` rethrew as `IllegalStateException`, and
Fabric Loader's `Knot` turns that into a fatal mod-init failure. The mod never became
usable and `/music` never existed.

The same gap hides `org.mozilla:rhino-engine`, `com.grack:nanojson`, `jsoup`,
`commons-io`, `base64`, `org.json`, `httpclient`/`httpcore`, Jackson and
`lavaplayer-natives` (scenario 5 covers the playback-time variant of that).

Paper was never affected: `paper/build.gradle` uses the shadow plugin, and `shadowJar`
bundles the whole `runtimeClasspath`.

## Root cause 2 - `fabric.mod.json` rejected valid installs

```json
"minecraft": "=26.3",          // Simple Voice Chat itself uses "26.3.x"
"voicechat_api": ">=2.6.24"    // the build's own dev runtime pins SVC 2.6.23
```

Fabric Loader **silently skips** a mod whose `depends` block is unsatisfied - no
entrypoints run, no `/music`, and nothing the player can see. Scenario 4b blocks the mod
for anyone whose SVC build bundles an older `voicechat_api` (including the SVC build this
repo's own `runtimeOnly` pins); scenario 4c blocks it on any `26.3.x` patch server.

`fabric-api` was also a hard dependency although it is never bundled and was never
documented. It stays a dependency (it is on virtually every Fabric server) but the README
now states it explicitly, under both requirements and troubleshooting.

## Root cause 3 - a broken engine removed the command

Both entry points built the audio engine *before* registering the command and treated any
failure as fatal: Paper called `disablePlugin(this)`, Fabric rethrew out of
`onInitialize()`. Either way the command disappeared, which is indistinguishable from
"not installed". Both now register the command first and log the real cause, so `/music`
stays available and reports it (scenarios 4d, 8, 10).

## The fix

- `fabric/build.gradle` resolves the audio engine's runtime classpath once and nests every
  jar it produced, instead of naming two modules by hand. A `verifyBundledLibraries` task
  fails the build if the nested set ever drifts from that classpath again.
- `fabric.mod.json` uses `26.3.x` for Minecraft and `*` for `voicechat_api`, and declares
  `voicechat` itself. `gradle.properties` documents why those ranges must stay permissive.
- `VoiceMusicFabric` / `VoiceMusicPaper` register the command first and never throw or
  self-disable; `/music help` keeps working so a player can tell "broken" from "absent".
- `README.md` documents the Fabric API requirement and a "there is no `/music` command"
  troubleshooting path.

## What is *not* proven here

The simulation cannot prove real source-provider availability or SVC voice transport. The
release validation checklist in the main `README.md` still has to be run against a live
server on both platforms.
