package top.kira.phone;

import java.util.Collections;
import java.util.Map;
import java.util.SortedMap;
import java.util.TreeMap;
import java.util.concurrent.Callable;
import java.util.function.LongSupplier;

/** Short-lived inventory only. Screen observations are never served from here. */
public final class AppCatalog {
    private final LongSupplier clock;
    private SortedMap<String,String> cached;
    private long loadedAt;
    public AppCatalog(LongSupplier clock) { this.clock = clock; }
    public synchronized SortedMap<String,String> snapshot(boolean refresh, Callable<Map<String,String>> loader) throws Exception {
        if (!refresh && cached != null && clock.getAsLong() - loadedAt < 15000) return cached;
        Map<String,String> loaded = loader.call();
        if (loaded.size() > 5000) throw new IllegalStateException("可启动应用数量超过查询上限");
        cached = Collections.unmodifiableSortedMap(new TreeMap<>(loaded));
        loadedAt = clock.getAsLong();
        return cached;
    }
}
