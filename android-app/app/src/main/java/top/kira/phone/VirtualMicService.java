package top.kira.phone;

import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Binder;
import android.os.Build;
import android.os.IBinder;
import android.os.Parcel;
import android.os.Process;
import android.os.RemoteException;
import org.json.JSONObject;
import java.lang.reflect.InvocationTargetException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Shizuku UserService, not an exported Android Service. No root or permission mutation. */
public final class VirtualMicService extends Binder {
    static final String DESCRIPTOR = "top.kira.phone.VirtualMicService";
    static final int PROBE = 1, PREPARE = 2, PLAY = 3, STATUS = 4, STOP = 5;
    private static final int DESTROY = 16777115;
    private final Context context;
    private final int ownerUid;
    private final ScheduledExecutorService worker = Executors.newScheduledThreadPool(2);
    private Session current;
    private String status = "ready", detail = "", target = "";
    private long firstWriteNanos;
    private int writtenSamples;

    public VirtualMicService(Context appContext) {
        context = appContext;
        ownerUid = appContext.getApplicationInfo().uid;
    }

    static boolean allowedTarget(String value) {
        return "top.kira.phone".equals(value) || "com.tencent.mobileqq".equals(value) || "com.tencent.mm".equals(value);
    }

    private boolean routingAllowed() {
        return Build.VERSION.SDK_INT >= 33 && Process.myUid() == 2000
            && context.checkPermission("android.permission.MODIFY_AUDIO_ROUTING", Process.myPid(), Process.myUid()) == PackageManager.PERMISSION_GRANTED;
    }

    @Override protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) throws RemoteException {
        int caller = Binder.getCallingUid();
        if (code == DESTROY) {
            if (caller != ownerUid && caller != 2000 && caller != 0) throw new SecurityException("Private service");
            close(); worker.shutdownNow(); System.exit(0); return true;
        }
        if (caller != ownerUid) throw new SecurityException("Private service");
        if (code == INTERFACE_TRANSACTION) { reply.writeString(DESCRIPTOR); return true; }
        data.enforceInterface(DESCRIPTOR);
        long identity = Binder.clearCallingIdentity();
        try {
            if (code == PREPARE) prepare(data.readString(), data.readStrongBinder());
            else if (code == PLAY) play();
            else if (code == STOP) close();
            else if (code != PROBE && code != STATUS) return super.onTransact(code, data, reply, flags);
            reply.writeNoException(); reply.writeString(snapshot().toString());
        } catch (Throwable error) {
            close();
            synchronized (this) { status = "error"; detail = describe(error); }
            reply.writeNoException(); reply.writeString(snapshot().toString());
        } finally { Binder.restoreCallingIdentity(identity); }
        return true;
    }

    private synchronized JSONObject snapshot() {
        JSONObject value = new JSONObject();
        try {
            value.put("permissionGranted", routingAllowed()).put("uid", Process.myUid())
                .put("active", current != null).put("status", status).put("detail", detail)
                .put("target", target).put("firstWriteNanos", firstWriteNanos).put("writtenSamples", writtenSamples);
        } catch (Exception ignored) { }
        return value;
    }

    private synchronized void prepare(String packageName, IBinder client) throws Exception {
        if (current != null) throw new IllegalStateException("已有测试正在运行");
        if (!allowedTarget(packageName) || client == null) throw new IllegalArgumentException("不支持的测试目标");
        if (!routingAllowed()) throw new SecurityException("此系统未授予 Shizuku shell 音频路由权限（需要 Android 13+）");
        int uid = context.getPackageManager().getApplicationInfo(packageName, 0).uid;
        if (uid < 10000 || uid / 100000 != ownerUid / 100000) throw new SecurityException("只能测试当前用户安装的应用");
        target = packageName; firstWriteNanos = 0; writtenSamples = 0;
        // AudioTrack and AudioManager must carry shell attribution, never the ordinary APK identity.
        Context shell = context.createPackageContext("com.android.shell", Context.CONTEXT_IGNORE_SECURITY);
        AudioManager manager = (AudioManager) shell.getSystemService(Context.AUDIO_SERVICE);
        if (manager == null) throw new IllegalStateException("系统未提供 AudioManager");
        Class<?> rule = Class.forName("android.media.audiopolicy.AudioMixingRule");
        Class<?> rb = Class.forName("android.media.audiopolicy.AudioMixingRule$Builder");
        Object builder = rb.getConstructor().newInstance();
        rb.getMethod("setTargetMixRole", int.class).invoke(builder, rule.getField("MIX_ROLE_INJECTOR").getInt(null));
        rb.getMethod("addMixRule", int.class, Object.class).invoke(builder, rule.getField("RULE_MATCH_UID").getInt(null), Integer.valueOf(uid));
        Object builtRule = rb.getMethod("build").invoke(builder);
        Class<?> mix = Class.forName("android.media.audiopolicy.AudioMix");
        Class<?> mb = Class.forName("android.media.audiopolicy.AudioMix$Builder");
        Object mixBuilder = mb.getConstructor(rule).newInstance(builtRule);
        AudioFormat format = new AudioFormat.Builder().setSampleRate(VirtualMicSignal.RATE)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build();
        mb.getMethod("setFormat", AudioFormat.class).invoke(mixBuilder, format);
        mb.getMethod("setRouteFlags", int.class).invoke(mixBuilder, mix.getField("ROUTE_FLAG_LOOP_BACK").getInt(null));
        Object builtMix = mb.getMethod("build").invoke(mixBuilder);
        Class<?> policy = Class.forName("android.media.audiopolicy.AudioPolicy");
        Class<?> pb = Class.forName("android.media.audiopolicy.AudioPolicy$Builder");
        Object policyBuilder = pb.getConstructor(Context.class).newInstance(shell);
        pb.getMethod("addMix", mix).invoke(policyBuilder, builtMix);
        Object builtPolicy = pb.getMethod("build").invoke(policyBuilder);
        Session session = new Session(manager, policy, builtPolicy, client);
        current = session;
        try {
            int result = (Integer) AudioManager.class.getMethod("registerAudioPolicy", policy).invoke(manager, builtPolicy);
            // AudioManager.SUCCESS is hidden from the public SDK (AudioSystem.SUCCESS = 0).
            if (result != 0) throw new IllegalStateException("系统拒绝注册录音注入路由：" + result);
            session.registered = true;
            session.track = (AudioTrack) policy.getMethod("createAudioTrackSource", mix).invoke(builtPolicy, builtMix);
            if (session.track == null || session.track.getState() != AudioTrack.STATE_INITIALIZED)
                throw new IllegalStateException("系统未能创建注入音轨");
            session.track.setBufferSizeInFrames(960);
            client.linkToDeath(session.death, 0);
            worker.schedule(() -> finish(session, "expired", "测试已达到 5 秒上限"), 5, TimeUnit.SECONDS);
            status = "prepared"; detail = "已建立临时路由，等待测试音";
        } catch (Exception error) { finish(session, "error", describe(error)); throw error; }
    }

    private synchronized void play() {
        Session session = current;
        if (session == null || session.playing) throw new IllegalStateException("测试未准备或已播放");
        session.playing = true; status = "testing"; detail = "正在发送短测试音";
        worker.execute(() -> {
            try {
                short[] samples = VirtualMicSignal.samples();
                session.track.play();
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
                int offset = 0;
                while (!session.cancelled && offset < samples.length && System.nanoTime() < deadline) {
                    int written = session.track.write(samples, offset, Math.min(960, samples.length - offset), AudioTrack.WRITE_NON_BLOCKING);
                    if (written < 0) throw new IllegalStateException("注入音轨写入失败：" + written);
                    if (written == 0) { Thread.sleep(4); continue; }
                    synchronized (VirtualMicService.this) {
                        if (current == session) { if (firstWriteNanos == 0) firstWriteNanos = System.nanoTime(); writtenSamples += written; }
                    }
                    offset += written;
                }
                if (!session.cancelled) {
                    if (offset != samples.length) throw new IllegalStateException("测试音发送超时");
                    Thread.sleep(200);
                    finish(session, "sent", "测试音已提交；是否收到仍需验证");
                }
            } catch (Throwable error) { if (!session.cancelled) finish(session, "error", describe(error)); }
        });
    }

    private synchronized void finish(Session session, String next, String message) {
        if (current != session) return;
        session.cancelled = true;
        if (session.track != null) {
            try { session.track.pause(); session.track.flush(); } catch (RuntimeException ignored) { }
            session.track.release();
        }
        if (session.registered) {
            try { AudioManager.class.getMethod("unregisterAudioPolicy", session.policyClass).invoke(session.manager, session.policy); }
            catch (Throwable ignored) { }
        }
        try { session.client.unlinkToDeath(session.death, 0); } catch (RuntimeException ignored) { }
        current = null; status = next; detail = message;
    }

    private synchronized void close() {
        if (current != null) finish(current, "stopped", "测试已停止，临时音频路由已释放");
    }

    static String describe(Throwable error) {
        while (error instanceof InvocationTargetException && error.getCause() != null) error = error.getCause();
        String message = error.getMessage();
        return error.getClass().getSimpleName() + (message == null ? "" : ": " + message.substring(0, Math.min(message.length(), 250)));
    }

    private final class Session {
        final AudioManager manager;
        final Class<?> policyClass;
        final Object policy;
        final IBinder client;
        final IBinder.DeathRecipient death;
        AudioTrack track;
        volatile boolean cancelled;
        boolean registered, playing;
        Session(AudioManager audio, Class<?> type, Object route, IBinder token) {
            manager = audio; policyClass = type; policy = route; client = token;
            death = () -> finish(this, "stopped", "App 已退出");
        }
    }
}
