package top.kira.phone;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.provider.Settings;
import android.view.View;
import android.view.ViewAnimationUtils;
import android.view.WindowManager;
import org.json.JSONObject;
import java.util.Locale;
import java.util.UUID;

/** Small UI boundary shared by the native services and the uni-app x interface. */
public final class PhoneRuntime {
    public static final int PROTOCOL_VERSION = 1;
    private PhoneRuntime() { }
    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("connection", Context.MODE_PRIVATE);
    }
    public static String state(Context context) {
        try {
            SharedPreferences settings = prefs(context);
            if (!settings.contains("device_id")) settings.edit().putString("device_id", UUID.randomUUID().toString()).commit();
            boolean configured;
            try {
                ServerAddress.normalize(settings.getString("url", ""));
                configured = ConnectionPassword.valid(settings.getString("token", ""));
            } catch (Exception error) { configured = false; }
            return new JSONObject().put("running", ConnectionService.running)
                .put("connected", ConnectionService.running && ConnectionService.status.startsWith("已连接"))
                .put("status", ConnectionService.status).put("accessibility", PhoneAccessibility.instance != null)
                .put("configured", configured).put("sdk", Build.VERSION.SDK_INT)
                .put("deviceName", Build.MANUFACTURER + " " + Build.MODEL)
                .put("deviceId", settings.getString("device_id", ""))
                .put("address", ServerAddress.display(settings.getString("url", "")))
                .put("version", context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName)
                .put("reducedMotion", settings.getBoolean("reduced_motion", false))
                .put("screenProtected", settings.getBoolean("screen_protected", true))
                .put("secureConfigured", settings.contains("screen_protected"))
                .put("animationSpeed", settings.getInt("animation_speed", 1)).toString();
        } catch (Exception error) { throw new IllegalStateException("无法读取手机状态", error); }
    }
    public static String config(Context context) {
        try {
            SharedPreferences settings = prefs(context);
            return new JSONObject().put("address", ServerAddress.display(settings.getString("url", "")))
                .put("password", settings.getString("token", ""))
                .put("fingerprint", settings.getString("pin", "")).toString();
        } catch (Exception error) { throw new IllegalStateException("无法读取连接设置", error); }
    }
    public static void save(Context context, String address, String password, String fingerprint) {
        synchronized (VoiceRuntime.AUDIO_LOCK) {
        if (ConnectionService.running) throw new IllegalStateException("请先停止连接，再修改设置");
        if (VoiceRuntime.isActive() || VirtualMicRuntime.isActive()) throw new IllegalStateException("请先结束通话或虚拟麦克风实验，再修改设置");
        String[] config = validateConfig(address, password, fingerprint);
        if (!prefs(context).edit().putString("url", config[0]).putString("token", password).putString("pin", config[1]).commit())
            throw new IllegalStateException("设置保存失败，请检查手机存储空间");
        }
    }
    private static String[] validateConfig(String address, String password, String fingerprint) {
        String normalized = ServerAddress.normalize(address);
        if (!ConnectionPassword.valid(password)) throw new IllegalArgumentException("连接密码需 8–128 位英文字母、数字或符号，不含空格");
        String pin = fingerprint == null ? "" : fingerprint.replaceAll("[\\s:]", "").toLowerCase(Locale.ROOT);
        if (!pin.isEmpty() && !pin.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("服务器校验码需要 64 位字母和数字");
        return new String[]{normalized, pin};
    }
    public static void start(Activity activity) {
        synchronized (VoiceRuntime.AUDIO_LOCK) {
        if (ConnectionService.running) throw new IllegalStateException("连接已启动");
        if (PhoneAccessibility.instance == null) throw new IllegalStateException("请先开启无障碍服务");
        SharedPreferences settings = prefs(activity);
        validateConfig(settings.getString("url", ""), settings.getString("token", ""), settings.getString("pin", ""));
        activity.startForegroundService(new Intent(activity, ConnectionService.class));
        }
    }
    public static void stop(Context context) {
        context.stopService(new Intent(context, ConnectionService.class));
    }
    public static void openAccessibility(Activity activity) {
        activity.startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
    }
    public static void secure(Activity activity) {
        applySecure(activity, prefs(activity).getBoolean("screen_protected", true), false);
    }
    public static boolean secure(Activity activity, boolean enabled) {
        return applySecure(activity, enabled, true);
    }
    private static void setWindowSecure(Activity activity, boolean enabled) {
        if (enabled) activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        else activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
        if (Build.VERSION.SDK_INT >= 33) activity.setRecentsScreenshotEnabled(!enabled);
    }
    private static boolean applySecure(Activity activity, boolean enabled, boolean persist) {
        java.util.concurrent.FutureTask<Boolean> task = new java.util.concurrent.FutureTask<>(() -> {
            boolean previous = (activity.getWindow().getAttributes().flags & WindowManager.LayoutParams.FLAG_SECURE) != 0;
            try {
                setWindowSecure(activity, enabled);
                boolean applied = (activity.getWindow().getAttributes().flags & WindowManager.LayoutParams.FLAG_SECURE) != 0;
                if (applied != enabled) throw new IllegalStateException("系统未应用截屏保护设置");
                if (persist && !prefs(activity).edit().putBoolean("screen_protected", applied).commit())
                    throw new IllegalStateException("截屏保护设置保存失败");
                return applied;
            } catch (Exception error) {
                setWindowSecure(activity, previous);
                throw error;
            }
        });
        activity.runOnUiThread(task);
        try { return task.get(3, java.util.concurrent.TimeUnit.SECONDS); }
        catch (InterruptedException error) {
            task.cancel(false);
            Thread.currentThread().interrupt();
            throw new IllegalStateException("界面保护已取消", error);
        } catch (Exception error) {
            task.cancel(false);
            throw new IllegalStateException("无法切换截屏保护，请重新打开 App", error);
        }
    }
    public static void prepare(Activity activity) {
        secure(activity);
        activity.runOnUiThread(() -> {
            if (Build.VERSION.SDK_INT >= 33 && activity.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED)
                activity.requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, 73);
        });
    }
    public static void preferences(Context context, boolean reducedMotion, int speed) {
        if (speed < 0 || speed > 2) throw new IllegalArgumentException("动画速度无效");
        if (!prefs(context).edit().putBoolean("reduced_motion", reducedMotion).putInt("animation_speed", speed).commit())
            throw new IllegalStateException("偏好保存失败");
    }
    public static void reveal(Activity activity, int duration, int x, int y) {
        if (prefs(activity).getBoolean("reduced_motion", false)) return;
        activity.runOnUiThread(() -> revealOnUiThread(activity, duration, x, y));
    }
    private static void revealOnUiThread(Activity activity, int duration, int x, int y) {
        View view = activity.findViewById(android.R.id.content);
        if (view == null || !view.isAttachedToWindow() || view.getWidth() == 0 || view.getHeight() == 0) return;
        int width = view.getWidth(), height = view.getHeight();
        x = Math.max(0, Math.min(width, x));
        y = Math.max(0, Math.min(height, y));
        android.animation.Animator animator = ViewAnimationUtils.createCircularReveal(view, x, y, 0,
            (float)Math.hypot(Math.max(x, width - x), Math.max(y, height - y)));
        animator.setDuration(Math.max(120, Math.min(700, duration)));
        animator.start();
    }
}
