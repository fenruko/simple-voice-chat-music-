package dev.arena.voicemusic.core;

import java.util.ArrayDeque;
import java.util.List;
import java.util.Objects;

/** A synchronized FIFO with a hard bound; bulk additions are all-or-nothing. */
public final class BoundedTrackQueue<T> {
    private final int capacity;
    private final ArrayDeque<T> items = new ArrayDeque<>();

    public BoundedTrackQueue(int capacity) {
        if (capacity < 1 || capacity > 10_000) throw new IllegalArgumentException("capacity out of range");
        this.capacity = capacity;
    }

    public synchronized boolean offer(T item) {
        Objects.requireNonNull(item, "item");
        if (items.size() >= capacity) return false;
        return items.offerLast(item);
    }

    public synchronized boolean offerAll(List<? extends T> batch) {
        Objects.requireNonNull(batch, "batch");
        if (batch.stream().anyMatch(Objects::isNull) || batch.size() > capacity - items.size()) return false;
        items.addAll(batch);
        return true;
    }

    public synchronized T poll() { return items.pollFirst(); }
    public synchronized T peek() { return items.peekFirst(); }
    public synchronized int size() { return items.size(); }
    public int capacity() { return capacity; }
    public synchronized boolean isEmpty() { return items.isEmpty(); }
    public synchronized List<T> snapshot() { return List.copyOf(items); }
    public synchronized void clear() { items.clear(); }
}
