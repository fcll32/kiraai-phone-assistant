package top.kira.phone;

import android.Manifest;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.AudioTimestamp;
import android.media.MediaRecorder;
import android.os.Binder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Parcel;
import org.json.JSONObject;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import rikka.shizuku.Shizuku;

/** Explicit, bounded diagnostics only. Neither a persistent virtual sound card nor automatic injection. */
public final class VirtualMicRuntime {
    private static final ExecutorService worker = Executors.newSingleThreadExecutor();
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final Binder lifetime = new Binder();
    private static volatile boolean active;
    private static volatile IBinder remote;
    private static boolean binding, listenerInstalled, permissionGranted, verified;
    private static String status = "idle", detail = "仅 Android 13+ 可尝试，是否可用以本机测试为准", target = "top.kira.phone";
    private static long latencyMs = -1;
    private static double score;
    private static Run current;
    private static Shizuku.UserServiceArgs serviceArgs;
    private VirtualMicRuntime() { }

    public static boolean isActive() { return active; }

    public static String state(Context context) {
        synchronized (VoiceRuntime.AUDIO_LOCK) {
            try {
                boolean running = running();
                return new JSONObject().put("supported", Build.VERSION.SDK_INT >= 33)
                    .put("shizukuRunning", running).put("authorized", running && authorized())
                    .put("bound", remote != null && remote.isBinderAlive()).put("active", active)
                    .put("permissionGranted", permissionGranted).put("status", status).put("detail", detail)
                    .put("target", target).put("verified", verified).put("latencyMs", latencyMs)
                    .put("latencyKind", "local_audio_path_estimate").put("score", score).toString();
            } catch (Exception error) { throw new IllegalStateException("无法读取实验状态", error); }
        }
    }

    public static void authorize(Activity activity) {
        if (Build.VERSION.SDK_INT < 33) throw new IllegalStateException("此实验需要 Android 13 或以上；普通通话不受影响");
        if (!running()) throw new IllegalStateException("请先安装并启动 Shizuku，使用无线调试或电脑 ADB 启动");
        if (Shizuku.getVersion() < 13) throw new IllegalStateException("请更新 Shizuku 至支持 v13 API 的版本");
        if (Shizuku.getUid() != 2000) throw new IllegalStateException("此实验只接受通过 ADB 启动的 Shizuku shell 模式");
        Context app = activity.getApplicationContext();
        main.post(() -> {
            try {
                if (!listenerInstalled) {
                    Shizuku.addRequestPermissionResultListener((request, grant) -> {
                        if (request != 761) return;
                        if (grant == PackageManager.PERMISSION_GRANTED) bind(app);
                        else message("denied", "未获得 Shizuku 授权");
                    });
                    listenerInstalled = true;
                }
                if (authorized()) bind(app);
                else { message("authorizing", "请在 Shizuku 弹窗中允许本次授权"); Shizuku.requestPermission(761); }
            } catch (Throwable error) { message("error", VirtualMicService.describe(error)); }
        });
    }

    private static boolean running() { try { return Shizuku.pingBinder(); } catch (Throwable ignored) { return false; } }
    private static boolean authorized() {
        try { return Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED; } catch (Throwable ignored) { return false; }
    }

    private static void bind(Context context) {
        synchronized (VoiceRuntime.AUDIO_LOCK) {
            if (binding || remote != null) return;
            binding = true; status = "binding"; detail = "正在检查本机音频路由能力";
            serviceArgs = new Shizuku.UserServiceArgs(new ComponentName(context, VirtualMicService.class))
                .daemon(false).processNameSuffix("virtual_mic").tag("kira-virtual-mic").version(1);
        }
        try { Shizuku.bindUserService(serviceArgs, connection); }
        catch (Throwable error) {
            synchronized (VoiceRuntime.AUDIO_LOCK) { binding = false; }
            message("error", VirtualMicService.describe(error));
        }
    }

    private static final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder service) {
            synchronized (VoiceRuntime.AUDIO_LOCK) { binding = false; remote = service; }
            worker.execute(() -> {
                try {
                    JSONObject result = transact(service, VirtualMicService.PROBE, null);
                    synchronized (VoiceRuntime.AUDIO_LOCK) {
                        if (remote != service) return;
                        permissionGranted = result.optBoolean("permissionGranted");
                        status = permissionGranted ? "ready" : "unavailable";
                        detail = permissionGranted ? "权限检查通过，可开始一次短测试；这还不代表注入成功"
                            : "本机 Shizuku shell 没有音频路由权限，此系统不能使用该实验";
                    }
                } catch (Throwable error) { message("error", VirtualMicService.describe(error)); }
            });
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            synchronized (VoiceRuntime.AUDIO_LOCK) {
                remote = null; binding = false; permissionGranted = false;
                if (current != null) current.cancelled = true;
                status = "disconnected"; detail = "Shizuku 服务已断开，请重新授权";
            }
        }
    };

    public static void test(Activity activity, String packageName) {
        if (Build.VERSION.SDK_INT < 33) throw new IllegalStateException("此实验需要 Android 13 或以上");
        if (activity == null || activity.isFinishing() || activity.isDestroyed() || !activity.hasWindowFocus())
            throw new IllegalStateException("请在 App 前台开始测试");
        if (!VirtualMicService.allowedTarget(packageName)) throw new IllegalArgumentException("只能选择本 App、QQ 或微信");
        boolean self = "top.kira.phone".equals(packageName);
        if (self && activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            throw new IllegalStateException("请先在通话卡片中允许麦克风权限，再运行本机验证");
        Run run;
        synchronized (VoiceRuntime.AUDIO_LOCK) {
            if (VoiceRuntime.isActive() || active) throw new IllegalStateException("请先结束通话或当前实验");
            if (!running() || !authorized() || remote == null || !remote.isBinderAlive() || !permissionGranted)
                throw new IllegalStateException("请先连接 Shizuku 并通过本机权限检查");
            run = new Run(remote, packageName); current = run; active = true;
            target = packageName; verified = false; latencyMs = -1; score = 0;
            status = "preparing"; detail = self ? "正在准备本机收音验证" : "最多发送 5 秒测试音，请由通话对方确认；App 无法验证对方收音";
        }
        worker.execute(() -> execute(run));
    }

    public static void stop(Context context) {
        synchronized (VoiceRuntime.AUDIO_LOCK) {
            if (current != null) { current.cancelled = true; status = "stopping"; detail = "正在释放临时音频路由"; }
            else { status = "stopped"; detail = "实验已停止"; }
        }
    }

    private static void execute(Run run) {
        AudioRecord recorder = null;
        String next = "error", explanation = "测试未完成";
        boolean matched = false;
        double confidence = 0;
        long measured = -1;
        try {
            check(run);
            JSONObject prepared = transact(run.binder, VirtualMicService.PREPARE, run.target);
            requireSuccess(prepared); check(run);
            boolean self = "top.kira.phone".equals(run.target);
            short[] capture = self ? new short[VirtualMicSignal.RATE * 3] : null;
            int count = 0;
            if (self) {
                int minimum = AudioRecord.getMinBufferSize(VirtualMicSignal.RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                if (minimum < 0) throw new IllegalStateException("本机不支持 48kHz 单声道录音");
                recorder = new AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                    .setAudioFormat(new AudioFormat.Builder().setSampleRate(VirtualMicSignal.RATE)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                    .setBufferSizeInBytes(Math.max(minimum * 2, 19200)).build();
                if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("无法建立本机验证录音");
                recorder.startRecording();
                if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException("系统拒绝本机验证录音");
            }
            check(run);
            requireSuccess(transact(run.binder, VirtualMicService.PLAY, null));
            messageFor(run, "testing", self ? "正在收音并比对测试信号，约 3 秒" : "正在发送短测试音，尚未验证对方能否收到");
            long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (System.nanoTime() < end) {
                check(run);
                if (self && count < capture.length) {
                    int read = recorder.read(capture, count, Math.min(1920, capture.length - count), AudioRecord.READ_NON_BLOCKING);
                    if (read < 0) throw new IllegalStateException("本机验证录音失败：" + read);
                    count += read;
                }
                Thread.sleep(4);
            }
            JSONObject result = transact(run.binder, VirtualMicService.STATUS, null);
            requireSuccess(result);
            if (result.optInt("writtenSamples") != VirtualMicSignal.samples().length)
                throw new IllegalStateException("测试音未完整送入路由");
            if (self) {
                AudioTimestamp timestamp = new AudioTimestamp();
                boolean timed = recorder.getTimestamp(timestamp, AudioTimestamp.TIMEBASE_MONOTONIC) == AudioRecord.SUCCESS;
                recorder.stop();
                VirtualMicSignal.Result detection = VirtualMicSignal.detect(capture, count);
                matched = detection.detected; confidence = detection.score;
                if (matched && timed && result.optLong("firstWriteNanos") > 0) {
                    long startNs = timestamp.nanoTime - timestamp.framePosition * 1000000000L / VirtualMicSignal.RATE;
                    long delay = (startNs - result.optLong("firstWriteNanos")) / 1000000
                        + (detection.offsetSamples - VirtualMicSignal.LEAD) * 1000L / VirtualMicSignal.RATE;
                    if (delay >= 0 && delay < 5000) measured = delay;
                }
                next = matched ? "verified" : "unverified";
                explanation = matched ? "本 App 已从录音接口收到匹配信号；不代表 QQ／微信兼容"
                    : "未从本 App 录音接口检测到完整测试信号，本机注入尚未验证";
            } else {
                next = "sent"; explanation = "测试音已提交，QQ／微信是否收到须由通话对方确认；兼容性未验证";
            }
        } catch (InterruptedException error) { next = "stopped"; explanation = "实验已取消"; }
        catch (Throwable error) { explanation = VirtualMicService.describe(error); }
        finally {
            if (recorder != null) {
                try { recorder.stop(); } catch (RuntimeException ignored) { }
                recorder.release();
            }
            try { transact(run.binder, VirtualMicService.STOP, null); }
            catch (Throwable ignored) {
                // A dead helper loses its policy automatically. A live helper has its own 5s watchdog.
            }
            synchronized (VoiceRuntime.AUDIO_LOCK) {
                if (current == run) {
                    current = null; active = false;
                    status = run.cancelled ? "stopped" : next;
                    detail = run.cancelled ? "实验已停止，临时路由已释放" : explanation;
                    verified = !run.cancelled && matched; score = confidence; latencyMs = run.cancelled ? -1 : measured;
                }
            }
        }
    }

    private static void check(Run run) throws InterruptedException { if (run.cancelled) throw new InterruptedException(); }
    private static void requireSuccess(JSONObject result) {
        if ("error".equals(result.optString("status")) || "expired".equals(result.optString("status")))
            throw new IllegalStateException(result.optString("detail", "音频路由失败"));
    }
    private static JSONObject transact(IBinder service, int code, String packageName) throws Exception {
        Parcel data = Parcel.obtain(), reply = Parcel.obtain();
        try {
            data.writeInterfaceToken(VirtualMicService.DESCRIPTOR);
            if (code == VirtualMicService.PREPARE) { data.writeString(packageName); data.writeStrongBinder(lifetime); }
            if (!service.transact(code, data, reply, 0)) throw new IllegalStateException("Shizuku 服务没有响应此请求");
            reply.readException(); return new JSONObject(reply.readString());
        } finally { data.recycle(); reply.recycle(); }
    }
    private static void message(String value, String text) {
        synchronized (VoiceRuntime.AUDIO_LOCK) { if (!active) { status = value; detail = text; } }
    }
    private static void messageFor(Run run, String value, String text) {
        synchronized (VoiceRuntime.AUDIO_LOCK) { if (current == run && !run.cancelled) { status = value; detail = text; } }
    }
    private static final class Run {
        final IBinder binder;
        final String target;
        volatile boolean cancelled;
        Run(IBinder service, String packageName) { binder = service; target = packageName; }
    }
}
