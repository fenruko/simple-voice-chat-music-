package dev.arena.voicemusic.core;

import org.junit.jupiter.api.Test;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import static org.junit.jupiter.api.Assertions.*;

class PcmFrameConverterTest {
    @Test void exactMonoLittleEndianFrameIsDecodedWithoutSignLoss() {
        byte[] bytes = new byte[PcmFrameConverter.BYTES_PER_FRAME];
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).putShort((short)-32768).putShort((short)32767);
        short[] samples = PcmFrameConverter.decode(bytes);
        assertEquals(PcmFrameConverter.SAMPLES_PER_FRAME, samples.length);
        assertEquals(Short.MIN_VALUE, samples[0]); assertEquals(Short.MAX_VALUE, samples[1]);
    }
    @Test void nullOrEmptyFrameBecomesCorrectSilence() {
        assertEquals(960, PcmFrameConverter.decode(null).length);
        for (short s : PcmFrameConverter.decode(new byte[0])) assertEquals(0, s);
    }
    @Test void malformedFrameIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> PcmFrameConverter.decode(new byte[1919]));
        assertThrows(IllegalArgumentException.class, () -> PcmFrameConverter.decode(new byte[1921]));
    }
}
