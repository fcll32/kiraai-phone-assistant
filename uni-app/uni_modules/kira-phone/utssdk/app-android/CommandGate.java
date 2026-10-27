package top.kira.phone;

import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;

/** Recheck connection ownership and expiry immediately before a side effect. */
public final class CommandGate {
    private final BooleanSupplier connected;
    private final LongSupplier clock;
    private final long deadline;

    public CommandGate(BooleanSupplier connected, LongSupplier clock, long ttl) {
        if (ttl < 1 || ttl > 60000) throw new IllegalArgumentException("Invalid command TTL");
        this.connected = connected; this.clock = clock; this.deadline = clock.getAsLong() + ttl;
    }
    public void check() {
        if (Thread.currentThread().isInterrupted() || !connected.getAsBoolean() || clock.getAsLong() >= deadline)
            throw new IllegalStateException("连接已取消或请求已过期，请重新观察");
    }
}
