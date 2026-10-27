package top.kira.phone;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayDeque;
import java.util.UUID;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** Small, synchronous UI bridge. Audio never crosses the JavaScript boundary. */
public final class VoiceRuntime {
    public static final Object AUDIO_LOCK = new Object();
    private static boolean active, connected, muted, speaker = true;
    private static double level;
    private static long startedAt;
    private static String status = "idle", detail = "", reservation = "";
    private static VoiceCallService service;
    private static final ArrayDeque<JSONObject> transcripts = new ArrayDeque<>();
    private VoiceRuntime() { }

    public static boolean isActive() { synchronized (AUDIO_LOCK) { return active; } }

    public static String state(Context context) {
        synchronized (AUDIO_LOCK) {
            try {
                boolean granted = context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
                JSONArray history = new JSONArray();
                for (JSONObject item : transcripts) history.put(item);
                return new JSONObject().put("active", active).put("connected", connected)
                    .put("status", status).put("detail", detail).put("microphoneGranted", granted)
                    .put("permission", granted).put("muted", muted).put("speaker", speaker)
                    .put("level", level).put("startedAt", startedAt).put("transcripts", history).toString();
            } catch (Exception error) { throw new IllegalStateException("无法读取通话状态", error); }
        }
    }

    public static void requestMicrophone(Activity activity) {
        onMain(() -> {
            requireForeground(activity);
            if (activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                activity.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 74);
        });
    }

    public static void start(Activity activity) {
        onMain(() -> {
            requireForeground(activity);
            if (activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                throw new IllegalStateException("请先允许麦克风权限，再开始通话");
            synchronized (AUDIO_LOCK) {
                if (active || service != null) throw new IllegalStateException("通话正在启动或结束，请稍后再试");
                if (VirtualMicRuntime.isActive()) throw new IllegalStateException("请先停止虚拟麦克风实验");
                SharedPreferences settings = activity.getSharedPreferences("connection", Context.MODE_PRIVATE);
                SocketSecurity.voiceUri(settings.getString("url", ""));
                if (!ConnectionPassword.valid(settings.getString("token", ""))) throw new IllegalStateException("请先保存服务器连接设置");
                if (!settings.contains("device_id")) settings.edit().putString("device_id", UUID.randomUUID().toString()).commit();
                active = true; connected = false; muted = false; speaker = true;
                status = "connecting"; detail = "正在连接语音服务"; level = 0; startedAt = 0;
                transcripts.clear(); reservation = UUID.randomUUID().toString();
                try {
                    activity.startForegroundService(new Intent(activity, VoiceCallService.class).putExtra("reservation", reservation));
                } catch (RuntimeException error) {
                    active = false; status = "error"; detail = "系统未允许开始通话，请保持 App 在前台重试";
                    reservation = "";
                    throw new IllegalStateException(detail, error);
                }
            }
        });
    }

    public static void stop(Context context) {
        onMain(() -> {
            VoiceCallService current;
            synchronized (AUDIO_LOCK) {
                current = service;
                if (current == null) {
                    active = false; connected = false; reservation = "";
                    status = "idle"; detail = "通话已结束"; level = 0;
                }
            }
            if (current != null) current.finish("idle", "通话已结束");
            else context.stopService(new Intent(context, VoiceCallService.class));
        });
    }

    public static void mute(Context context, boolean value) {
        onMain(() -> { VoiceCallService current = requireService(); current.setMuted(value); });
    }
    public static void speaker(Context context, boolean value) {
        onMain(() -> { VoiceCallService current = requireService(); current.setSpeaker(value); });
    }
    public static void interrupt(Context context) {
        onMain(() -> requireService().interruptReply());
    }

    private static VoiceCallService requireService() {
        synchronized (AUDIO_LOCK) {
            if (!active || service == null || !connected) throw new IllegalStateException("请先建立通话连接");
            return service;
        }
    }
    private static void requireForeground(Activity activity) {
        if (activity == null || activity.isFinishing() || activity.isDestroyed() || !activity.hasWindowFocus())
            throw new IllegalStateException("请在 App 页面中开始通话");
    }
    private static void onMain(Runnable action) {
        if (Looper.myLooper() == Looper.getMainLooper()) { action.run(); return; }
        FutureTask<Void> task = new FutureTask<>(action, null);
        new Handler(Looper.getMainLooper()).post(task);
        try { task.get(5, TimeUnit.SECONDS); }
        catch (InterruptedException error) { task.cancel(false); Thread.currentThread().interrupt(); throw new IllegalStateException("操作已取消", error); }
        catch (Exception error) {
            task.cancel(false);
            Throwable cause = error.getCause();
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            throw new IllegalStateException("通话界面暂时没有响应", error);
        }
    }

    static boolean attach(VoiceCallService current, String token) {
        synchronized (AUDIO_LOCK) {
            if (!active || reservation.isEmpty() || !reservation.equals(token) || service != null) return false;
            service = current;
            return true;
        }
    }
    static void update(VoiceCallService current, String next, String message) {
        synchronized (AUDIO_LOCK) {
            if (service != current || !active) return;
            status = next; detail = message == null ? "" : message;
        }
    }
    static void welcome(VoiceCallService current) {
        synchronized (AUDIO_LOCK) {
            if (service != current || !active) return;
            connected = true; startedAt = System.currentTimeMillis();
        }
    }
    static void options(VoiceCallService current, boolean micMuted, boolean loudspeaker) {
        synchronized (AUDIO_LOCK) { if (service == current) { muted = micMuted; speaker = loudspeaker; } }
    }
    static void meter(VoiceCallService current, double value) {
        synchronized (AUDIO_LOCK) { if (service == current) level = value; }
    }
    static void transcript(VoiceCallService current, String role, String text) {
        synchronized (AUDIO_LOCK) {
            if (service != current || !active) return;
            try {
                transcripts.addLast(new JSONObject().put("role", role).put("text", text.substring(0, Math.min(4000, text.length()))));
                while (transcripts.size() > 30) transcripts.removeFirst();
            } catch (Exception ignored) { }
        }
    }
    static void ended(VoiceCallService current, String next, String message) {
        synchronized (AUDIO_LOCK) {
            if (service != current) return;
            active = false; connected = false; reservation = ""; level = 0;
            status = next; detail = message;
        }
    }
    static void destroyed(VoiceCallService current) {
        synchronized (AUDIO_LOCK) { if (service == current) service = null; }
    }
}
