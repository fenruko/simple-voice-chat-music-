package dev.arena.voicemusic.core;

import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;

class BoundedTrackQueueTest {
    @Test void fifoAndHardCapacity() {
        var q = new BoundedTrackQueue<Integer>(2);
        assertTrue(q.offer(1)); assertTrue(q.offer(2)); assertFalse(q.offer(3));
        assertEquals(1, q.poll()); assertTrue(q.offer(3));
        assertEquals(List.of(2, 3), q.snapshot());
    }
    @Test void bulkInsertIsAtomicAndRejectsNulls() {
        var q = new BoundedTrackQueue<Integer>(3);
        assertTrue(q.offer(1));
        assertFalse(q.offerAll(List.of(2, 3, 4)));
        assertEquals(List.of(1), q.snapshot());
        assertThrows(NullPointerException.class, () -> q.offer(null));
    }
    @Test void concurrentOffersNeverExceedCapacity() throws Exception {
        int workers = 24, each = 500;
        var q = new BoundedTrackQueue<Integer>(1000);
        var pool = Executors.newFixedThreadPool(workers);
        var start = new CountDownLatch(1);
        for (int w=0; w<workers; w++) { final int offset=w*each; pool.submit(() -> { start.await(); for(int i=0;i<each;i++) q.offer(offset+i); return null; }); }
        start.countDown(); pool.shutdown(); assertTrue(pool.awaitTermination(10, TimeUnit.SECONDS));
        assertEquals(1000, q.size()); assertEquals(1000, q.snapshot().stream().distinct().count());
    }
}
