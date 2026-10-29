package top.kira.phone;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.graphics.Rect;
import android.hardware.HardwareBuffer;
import android.media.AudioManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Base64;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

public class PhoneAccessibility extends AccessibilityService {
    public static volatile PhoneAccessibility instance;
    private final Handler main = new Handler(Looper.getMainLooper());
    private long lastScreenshot;
    private final AppCatalog appCatalog = new AppCatalog(SystemClock::elapsedRealtime);
    @Override protected void onServiceConnected() { instance = this; }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) { }
    @Override public void onInterrupt() { }
    @Override public void onDestroy() {
        instance = null; stopService(new Intent(this, ConnectionService.class)); super.onDestroy();
    }
    private <T> T onMain(Callable<T> work, CommandGate gate) throws Exception {
        CompletableFuture<T> result = new CompletableFuture<>();
        main.post(() -> { if (result.isDone()) return;
            try { gate.check(); result.complete(work.call()); } catch (Exception e) { result.completeExceptionally(e); } });
        try { return result.get(6, TimeUnit.SECONDS); }
        catch (Exception e) {
            result.cancel(false);
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            throw e;
        }
    }
    private DisplayMetrics metrics() {
        DisplayMetrics value = new DisplayMetrics();
        ((WindowManager)getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(value);
        return value;
    }
    public JSONObject observe(int maxEdge, String imageFormat, CommandGate gate) throws Exception {
        gate.check();
        if (Build.VERSION.SDK_INT < 30) return onMain(this::uiState, gate);
        long delay = 400 - (SystemClock.elapsedRealtime() - lastScreenshot);
        if (delay > 0) Thread.sleep(delay);
        lastScreenshot = SystemClock.elapsedRealtime();
        CompletableFuture<ScreenshotResult> future = new CompletableFuture<>();
        main.post(() -> { if (future.isDone()) return;
            try { gate.check();
            takeScreenshot(Display.DEFAULT_DISPLAY, getMainExecutor(), new TakeScreenshotCallback() {
            @Override public void onSuccess(ScreenshotResult result) {
                // Transfer ownership only. Full-resolution pixel copies must not
                // block the UI thread; a cancelled/late callback still owns cleanup.
                if (!future.complete(result)) result.getHardwareBuffer().close();
            }
            @Override public void onFailure(int errorCode) {
                future.completeExceptionally(new IllegalStateException("系统截图失败，错误码 " + errorCode + "；受保护窗口可能禁止截图"));
            }
        }); } catch (Exception error) { future.completeExceptionally(error); } });
        ScreenshotResult captured;
        try { captured = future.get(6, TimeUnit.SECONDS); }
        catch (Exception e) {
            future.cancel(false);
            future.thenAccept(result -> result.getHardwareBuffer().close());
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            throw e;
        }
        Bitmap bitmap;
        try (HardwareBuffer buffer = captured.getHardwareBuffer()) {
            gate.check();
            Bitmap hardware = Bitmap.wrapHardwareBuffer(buffer, captured.getColorSpace());
            if (hardware == null) throw new IllegalStateException("无法读取截图缓冲区");
            try {
                bitmap = hardware.copy(Bitmap.Config.ARGB_8888, false);
                if (bitmap == null) throw new IllegalStateException("截图缓冲分配失败");
            } finally { hardware.recycle(); }
        }
        Bitmap preview = bitmap;
        try {
            gate.check();
            int width = bitmap.getWidth(), height = bitmap.getHeight();
            double ratio = Math.min(1.0, maxEdge / (double)Math.max(width, height));
            if (ratio < 1) preview = Bitmap.createScaledBitmap(bitmap, Math.max(1, (int)(width * ratio)), Math.max(1, (int)(height * ratio)), true);
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            boolean jpeg = "jpeg".equals(imageFormat);
            if (!preview.compress(jpeg ? Bitmap.CompressFormat.JPEG : Bitmap.CompressFormat.PNG, jpeg ? 85 : 100, output))
                throw new IllegalStateException("截图编码失败");
            if (output.size() > 8_000_000) throw new IllegalStateException("截图过大，请调低截图长边");
            JSONArray nodes = new JSONArray();
            try {
                JSONObject ui = onMain(this::uiState, gate);
                if (ui.getInt("width") == width && ui.getInt("height") == height) nodes = ui.getJSONArray("nodes");
            } catch (Exception error) {
                // Controls are optional metadata. Preserve a valid image when a
                // window disappears, but never suppress cancellation/expiry.
                gate.check();
            }
            return new JSONObject().put("width", width).put("height", height).put("nodes", nodes)
                .put("image_format", jpeg ? "jpeg" : "png")
                .put("image_base64", Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP));
        } finally { if (preview != bitmap) preview.recycle(); bitmap.recycle(); }
    }
    public JSONObject uiTree(CommandGate gate) throws Exception { return onMain(this::uiState, gate); }
    public JSONObject apps(JSONObject params, CommandGate gate) throws Exception {
        String query = params.optString("query", "").trim().toLowerCase(java.util.Locale.ROOT);
        int offset = (int)number(params, "offset", 0, 0, 100000);
        int limit = (int)number(params, "limit", 50, 1, 100);
        if (query.length() > 80) throw new IllegalArgumentException("搜索名称过长");
        gate.check();
        java.util.SortedMap<String,String> catalog = appCatalog.snapshot(params.optBoolean("refresh", false), () -> {
            Intent launcher = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
            android.content.pm.PackageManager pm = getPackageManager();
            java.util.Map<String,String> loaded = new java.util.TreeMap<>();
            for (android.content.pm.ResolveInfo info : pm.queryIntentActivities(launcher, 0)) {
                gate.check();
                if (info.activityInfo == null || !info.activityInfo.enabled || !info.activityInfo.applicationInfo.enabled) continue;
                String pkg = info.activityInfo.packageName;
                String name = String.valueOf(info.loadLabel(pm));
                if (pkg.length() <= 200) loaded.put(pkg, name.substring(0, Math.min(name.length(), 80)));
            }
            return loaded;
        });
        java.util.TreeMap<String,String> found = new java.util.TreeMap<>();
        for (java.util.Map.Entry<String,String> app : catalog.entrySet()) {
            gate.check();
            String pkg = app.getKey(), name = app.getValue();
            if (query.isEmpty() || name.toLowerCase(java.util.Locale.ROOT).contains(query) || pkg.toLowerCase(java.util.Locale.ROOT).contains(query)) found.put(pkg, name);
        }
        JSONArray entries = new JSONArray(); int index = 0;
        for (java.util.Map.Entry<String,String> app : found.entrySet()) {
            if (index++ < offset) continue;
            if (entries.length() == limit) break;
            entries.put(new JSONObject().put("name", app.getValue()).put("package", app.getKey()));
        }
        gate.check();
        return new JSONObject().put("apps", entries).put("total", found.size()).put("offset", offset)
            .put("next_offset", offset + entries.length() < found.size() ? offset + entries.length() : -1);
    }
    private JSONObject uiState() throws Exception {
        DisplayMetrics size = metrics(); JSONArray nodes = new JSONArray();
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root != null) { try { collect(root, nodes, size, 0, new int[]{0}); } finally { root.recycle(); } }
        return new JSONObject().put("ui_only", true).put("width", size.widthPixels).put("height", size.heightPixels)
            .put("nodes", nodes).put("note", "无障碍控件信息，不是图片；视频、画布和游戏可能不可见");
    }
    private void collect(AccessibilityNodeInfo node, JSONArray nodes, DisplayMetrics size, int depth, int[] visited) throws Exception {
        if (depth > 20 || ++visited[0] > 600 || nodes.length() >= 120) return;
        CharSequence text = node.isPassword() ? "[密码框]" : node.getText();
        CharSequence desc = node.isPassword() ? null : node.getContentDescription();
        if (node.isVisibleToUser() && (node.isClickable() || node.isEditable() || text != null || desc != null)) {
            Rect rect = new Rect(); node.getBoundsInScreen(rect);
            if (!rect.isEmpty() && rect.intersect(0, 0, size.widthPixels, size.heightPixels)) {
                String label = String.valueOf(text != null ? text : desc != null ? desc : "");
                nodes.put(new JSONObject().put("text", label.substring(0, Math.min(label.length(), 160)))
                    .put("editable", node.isEditable()).put("clickable", node.isClickable())
                    .put("x", rect.centerX() * 1000 / Math.max(1, size.widthPixels))
                    .put("y", rect.centerY() * 1000 / Math.max(1, size.heightPixels)));
            }
        }
        for (int i=0; i<node.getChildCount() && visited[0] < 600 && nodes.length()<120; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) { try { collect(child, nodes, size, depth+1, visited); } finally { child.recycle(); } }
        }
    }
    private static double number(JSONObject params, String key, double fallback, double min, double max) throws Exception {
        Object raw = params.opt(key);
        double value = raw == null ? fallback : raw instanceof Number ? ((Number)raw).doubleValue() : Double.NaN;
        if (Double.isNaN(value) || Double.isInfinite(value) || value < min || value > max) throw new IllegalArgumentException("无效参数 " + key);
        return value;
    }
    public JSONObject action(JSONObject request, CommandGate gate) throws Exception {
        gate.check();
        String action = request.getString("action"); JSONObject args = request.getJSONObject("args");
        if (action.equals("wait")) { Thread.sleep((long)(number(args,"seconds",1,0,5)*1000)); return new JSONObject(); }
        if (action.equals("tap") || action.equals("swipe") || action.equals("long_press")) {
            DisplayMetrics size = onMain(this::metrics, gate); JSONArray expected = request.optJSONArray("size");
            if (expected == null || expected.getInt(0) != size.widthPixels || expected.getInt(1) != size.heightPixels)
                throw new IllegalStateException("屏幕尺寸变化，请重新观察");
            float x = (float)(number(args,"x",Double.NaN,0,1000)*(size.widthPixels-1)/1000);
            float y = (float)(number(args,"y",Double.NaN,0,1000)*(size.heightPixels-1)/1000);
            Path path = new Path(); path.moveTo(x,y);
            if (action.equals("swipe")) path.lineTo((float)(number(args,"x2",Double.NaN,0,1000)*(size.widthPixels-1)/1000),
                (float)(number(args,"y2",Double.NaN,0,1000)*(size.heightPixels-1)/1000));
            long duration = action.equals("tap") ? 70 : (long)number(args,"duration_ms",action.equals("long_press")?600:400,100,3000);
            GestureDescription gesture = new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(path,0,duration)).build();
            CompletableFuture<Boolean> completed = new CompletableFuture<>();
            main.post(() -> {
                if (completed.isDone()) return;
                try {
                gate.check();
                DisplayMetrics current = metrics();
                if (current.widthPixels != size.widthPixels || current.heightPixels != size.heightPixels)
                    throw new IllegalStateException("屏幕尺寸变化，请重新观察");
                if (!dispatchGesture(gesture, new GestureResultCallback() {
                    @Override public void onCompleted(GestureDescription g) { completed.complete(true); }
                    @Override public void onCancelled(GestureDescription g) { completed.complete(false); }
                }, main)) completed.complete(false);
                } catch (Exception error) { completed.completeExceptionally(error); }
            });
            try { if (!completed.get(5, TimeUnit.SECONDS)) throw new IllegalStateException("手势被系统取消，请重新观察"); }
            catch (Exception e) { completed.cancel(false); throw e; }
        } else if (action.equals("text")) {
            String value = args.getString("text");
            if (value.length() < 1 || value.length() > 2000) throw new IllegalArgumentException("文本长度无效");
            onMain(() -> {
                AccessibilityNodeInfo node = findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
                if (node == null) throw new IllegalStateException("请先点击输入框");
                try {
                    Bundle bundle = new Bundle(); bundle.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value);
                    if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle)) throw new IllegalStateException("应用不允许无障碍输入");
                } finally { node.recycle(); } return true;
            }, gate);
        } else if (action.equals("open_app")) {
            String pkg = args.getString("package");
            if (!pkg.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+")) throw new IllegalArgumentException("包名无效");
            onMain(() -> { Intent intent = getPackageManager().getLaunchIntentForPackage(pkg);
                if (intent == null) throw new IllegalStateException("应用不存在或没有启动入口");
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); startActivity(intent); return true; }, gate);
        } else if (action.equals("key")) {
            String key = args.getString("key"); onMain(() -> {
                int global = key.equals("back") ? GLOBAL_ACTION_BACK : key.equals("home") ? GLOBAL_ACTION_HOME : key.equals("recent") ? GLOBAL_ACTION_RECENTS : 0;
                if (global != 0) { if (!performGlobalAction(global)) throw new IllegalStateException("系统按键失败"); }
                else if (key.equals("volume_up") || key.equals("volume_down")) ((AudioManager)getSystemService(AUDIO_SERVICE)).adjustVolume(key.equals("volume_up") ? 1 : -1, 0);
                else if (key.equals("enter") && Build.VERSION.SDK_INT >= 33) {
                    AccessibilityNodeInfo node = findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
                    if (node == null) throw new IllegalStateException("输入框未聚焦");
                    try { if (!node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId())) throw new IllegalStateException("应用不支持确认键，请点击屏幕按钮"); }
                    finally { node.recycle(); }
                } else if (key.equals("backspace")) {
                    AccessibilityNodeInfo node = findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
                    if (node == null) throw new IllegalStateException("输入框未聚焦");
                    try {
                        CharSequence old = node.getText(); if (old == null || node.isPassword()) throw new IllegalStateException("无法读取当前文本");
                        String value = old.toString(); int anchor = node.getTextSelectionStart(), edge = node.getTextSelectionEnd();
                        // Android preserves the selection direction; either endpoint may come first.
                        int start = Math.min(anchor, edge), end = Math.max(anchor, edge);
                        if (start < 0 || end > value.length()) throw new IllegalStateException("光标位置不可用");
                        int from = start == end && start > 0 ? value.offsetByCodePoints(start,-1) : start;
                        if (from != end) {
                            Bundle bundle = new Bundle(); bundle.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value.substring(0,from)+value.substring(end));
                            if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,bundle)) throw new IllegalStateException("删除字符失败");
                            Bundle caret = new Bundle();
                            caret.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, from);
                            caret.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, from);
                            if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, caret))
                                throw new IllegalStateException("文字已删除，但光标未能恢复；请重新观察后继续");
                        }
                    } finally { node.recycle(); }
                } else throw new IllegalArgumentException("当前 Android 不支持该按键；请使用屏幕按钮");
                return true;
            }, gate);
        } else throw new IllegalArgumentException("不支持的操作");
        return new JSONObject().put("action_completed",true);
    }
}
