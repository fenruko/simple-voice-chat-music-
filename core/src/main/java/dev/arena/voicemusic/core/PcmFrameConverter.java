package dev.arena.voicemusic.core;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Converts one 20 ms, 48 kHz, mono, signed 16-bit little-endian frame to SVC samples. */
public final class PcmFrameConverter {
    public static final int SAMPLE_RATE = 48_000;
    public static final int SAMPLES_PER_FRAME = 960;
    public static final int BYTES_PER_FRAME = SAMPLES_PER_FRAME * Short.BYTES;
    private static final short[] SILENCE = new short[SAMPLES_PER_FRAME];

    private PcmFrameConverter() { }

    public static short[] decode(byte[] pcm) {
        if (pcm == null || pcm.length == 0) return SILENCE.clone();
        if (pcm.length != BYTES_PER_FRAME) throw new IllegalArgumentException("Expected exactly one 20 ms mono PCM frame");
        short[] output = new short[SAMPLES_PER_FRAME];
        ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(output);
        return output;
    }

    public static short[] silence() { return SILENCE.clone(); }
}
