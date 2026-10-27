package top.kira.phone;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.drafts.Draft_6455;
import org.java_websocket.extensions.DefaultExtension;
import org.java_websocket.handshake.ServerHandshake;
import org.java_websocket.protocols.Protocol;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.net.URI;
import java.nio.ByteBuffer;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.UUID;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import javax.net.ssl.SSLParameters;

/** User-started, half-duplex voice transport. It never reconnects or replays speech. */
public final class VoiceCallService extends Service {
    private static final String CHANNEL = "voice_call", STOP = "top.kira.phone.STOP_VOICE";
    private static final int NOTIFICATION = 3, MAX_AUDIO = 10 * 1024 * 1024;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Object turnLock = new Object();
    private final ArrayBlockingQueue<Outbound> outgoing = new ArrayBlockingQueue<>(96);
    private long sendGeneration;
    private static final class Outbound {
        final Object value;
        final long generation;
        Outbound(Object value, long generation) { this.value = value; this.generation = generation; }
    }
    private final AtomicInteger queuedEvents = new AtomicInteger();
    private final Set<File> pendingFiles = new HashSet<>();
    private volatile boolean active, welcomed, listening, muted, loudspeaker = true;
    private volatile long receivedAt, captureGeneration, replyGeneration, quietUntil;
    private volatile String currentTurn = "", interruptId = "";
    private VoiceSocket socket;
    private Thread captureThread, writerThread;
    private volatile AudioRecord recorder;
    private AudioManager audioManager;
    private AudioFocusRequest focus;
    private int oldMode;
    private boolean oldSpeaker, routeSaved;
    private AudioDeviceInfo oldCommunicationDevice;
    private MediaPlayer player;
    private File playbackFile;
    private String endStatus = "idle", endDetail = "通话已结束";
    private volatile long turnStartedAt;
    private long interruptedAt;
    private boolean closing;

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) {
            finish("idle", "通话已结束");
            return START_NOT_STICKY;
        }
        if (active) return START_NOT_STICKY;
        if (intent == null || !VoiceRuntime.attach(this, intent.getStringExtra("reservation"))) {
            stopSelf();
            return START_NOT_STICKY;
        }
        try {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                throw new IllegalStateException("麦克风权限尚未允许");
            NotificationManager notifications = getSystemService(NotificationManager.class);
            notifications.createNotificationChannel(new NotificationChannel(CHANNEL, "App 内通话", NotificationManager.IMPORTANCE_LOW));
            Notification notification = notification();
            if (Build.VERSION.SDK_INT >= 29)
                startForeground(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
            else startForeground(NOTIFICATION, notification);
            active = true;
            prepareAudio();
            SharedPreferences settings = getSharedPreferences("connection", MODE_PRIVATE);
            socket = new VoiceSocket(SocketSecurity.voiceUri(settings.getString("url", "")),
                settings.getString("token", ""), settings.getString("device_id", ""));
            socket.setSocketFactory(SocketSecurity.factory(settings.getString("pin", "")));
            socket.setConnectionLostTimeout(40);
            receivedAt = SystemClock.elapsedRealtime();
            writerThread = new Thread(this::writeLoop, "Kira-voice-send");
            writerThread.start();
            socket.connect();
            main.postDelayed(() -> { if (active && !welcomed) fail("通话连接超时，请检查插件是否开启了语音通话"); }, 15000);
            main.postDelayed(heartbeat, 20000);
        } catch (Exception error) {
            finish("error", "无法开始通话：" + safeMessage(error));
        }
        return START_NOT_STICKY;
    }

    private Notification notification() {
        Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (launch == null) launch = new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            android.net.Uri.parse("package:" + getPackageName()));
        PendingIntent open = PendingIntent.getActivity(this, 21, launch, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 22, new Intent(this, VoiceCallService.class).setAction(STOP),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("KiraAI 手机助手 · 通话中").setContentText("点击返回 App，或挂断结束麦克风使用")
            .setCategory(Notification.CATEGORY_CALL).setOngoing(true).setContentIntent(open)
            .addAction(new Notification.Action.Builder(null, "挂断", stop).build()).build();
    }

    private void prepareAudio() {
        audioManager = getSystemService(AudioManager.class);
        if (audioManager == null) throw new IllegalStateException("系统音频服务不可用");
        oldMode = audioManager.getMode(); oldSpeaker = audioManager.isSpeakerphoneOn();
        if (oldMode == AudioManager.MODE_IN_CALL || oldMode == AudioManager.MODE_IN_COMMUNICATION)
            throw new IllegalStateException("其他通话正在使用音频，请先结束后重试");
        if (Build.VERSION.SDK_INT >= 31) oldCommunicationDevice = audioManager.getCommunicationDevice();
        routeSaved = true;
        AudioAttributes attributes = voiceAttributes();
        focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attributes).setAcceptsDelayedFocusGain(false)
            .setOnAudioFocusChangeListener(change -> {
                if (change < 0 && active) finish("idle", "其他应用接管了音频，通话已结束");
            }, main).build();
        if (audioManager.requestAudioFocus(focus) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED)
            throw new IllegalStateException("麦克风或音频正在被其他通话使用");
        audioManager.setMode(AudioManager.MODE_IN_COMMUNICATION);
        setSpeaker(true);
    }

    private static AudioAttributes voiceAttributes() {
        return new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();
    }

    void setSpeaker(boolean enabled) {
        if (audioManager == null) throw new IllegalStateException("音频尚未准备好");
        if (Build.VERSION.SDK_INT >= 31) {
            int type = enabled ? AudioDeviceInfo.TYPE_BUILTIN_SPEAKER : AudioDeviceInfo.TYPE_BUILTIN_EARPIECE;
            AudioDeviceInfo selected = null;
            for (AudioDeviceInfo device : audioManager.getAvailableCommunicationDevices())
                if (device.getType() == type) { selected = device; break; }
            if (selected == null || !audioManager.setCommunicationDevice(selected)) {
                if (!enabled) throw new IllegalStateException("当前设备没有可用听筒，请使用扬声器");
                audioManager.setSpeakerphoneOn(true);
            }
        } else audioManager.setSpeakerphoneOn(enabled);
        loudspeaker = enabled;
        VoiceRuntime.options(this, muted, loudspeaker);
    }

    void setMuted(boolean enabled) {
        if (muted == enabled) return;
        synchronized (turnLock) {
            muted = enabled;
            captureGeneration++;
        }
        VoiceRuntime.options(this, muted, loudspeaker);
        VoiceRuntime.meter(this, 0);
        if (enabled && !currentTurn.isEmpty() && listening) interruptReply();
        if (listening && player == null) updateListening();
    }

    void interruptReply() {
        if (!active || !welcomed || !interruptId.isEmpty()) return;
        synchronized (turnLock) {
            listening = false; captureGeneration++; replyGeneration++;
            interruptId = UUID.randomUUID().toString();
            interruptedAt = SystemClock.elapsedRealtime();
            sendGeneration++;
            outgoing.clear();
            send(json("type", "interrupt", "request_id", interruptId));
        }
        clearPlayback();
        VoiceRuntime.meter(this, 0);
        VoiceRuntime.update(this, "thinking", "正在停止回复");
        main.postDelayed(() -> {
            if (active && !interruptId.isEmpty() && SystemClock.elapsedRealtime() - interruptedAt >= 6000)
                fail("停止回复没有得到服务器确认，请重新通话");
        }, 6100);
    }

    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            if (!active) return;
            long now = SystemClock.elapsedRealtime();
            if (now - receivedAt > 65000) { fail("语音连接已断开，请重新拨打"); return; }
            if (!listening && !currentTurn.isEmpty() && player == null && now - turnStartedAt > 180000) {
                fail("语音服务响应超时，请检查语音模型设置"); return;
            }
            if (welcomed) send(json("type", "ping"));
            main.postDelayed(this, 20000);
        }
    };

    private boolean send(Object value) {
        synchronized (turnLock) {
            if (!active) return false;
            if (!outgoing.offer(new Outbound(value, sendGeneration))) { fail("网络发送过慢，已结束通话以避免声音堆积"); return false; }
            return true;
        }
    }

    private void writeLoop() {
        try {
            while (active) {
                Outbound item = outgoing.poll(200, TimeUnit.MILLISECONDS);
                if (item == null) continue;
                VoiceSocket peer = socket;
                if (peer == null || !peer.isOpen()) { fail("语音连接中断"); return; }
                long started = SystemClock.elapsedRealtime();
                while (active && peer.hasBufferedData()) {
                    if (SystemClock.elapsedRealtime() - started > 1500) { fail("网络发送过慢，请换稳定网络再拨打"); return; }
                    Thread.sleep(5);
                }
                synchronized (turnLock) {
                    if (!active) return;
                    // A polled packet may outlive clear(); send and interrupt must be ordered.
                    if (item.generation != sendGeneration) continue;
                    if (item.value instanceof byte[]) peer.send((byte[]) item.value);
                    else peer.send(item.value.toString());
                }
            }
        } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        catch (Exception error) { fail("声音发送失败，请重新拨打"); }
    }

    private boolean mayCapture() {
        return active && welcomed && listening && !muted && interruptId.isEmpty()
            && SystemClock.elapsedRealtime() >= quietUntil;
    }

    private void captureLoop() {
        AudioRecord local = null;
        boolean recording = false;
        VoiceVad vad = new VoiceVad();
        ArrayDeque<byte[]> preroll = new ArrayDeque<>();
        long generation = -1;
        String utterance = "";
        short[] frame = new short[VoiceVad.FRAME_SAMPLES];
        try {
            int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException("当前设备不支持语音采样");
            local = new AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(minimum, 640 * 8));
            recorder = local;
            if (local.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("麦克风无法初始化");
            while (active) {
                if (!mayCapture()) {
                    if (recording) { local.stop(); recording = false; }
                    vad.reset(); preroll.clear(); utterance = "";
                    VoiceRuntime.meter(this, 0);
                    Thread.sleep(30);
                    continue;
                }
                if (!recording || generation != captureGeneration) {
                    if (recording) local.stop();
                    generation = captureGeneration; vad.reset(); preroll.clear(); utterance = "";
                    local.startRecording(); recording = true;
                    if (local.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING)
                        throw new IllegalStateException("系统未启动麦克风");
                }
                int offset = 0;
                while (offset < frame.length && active && mayCapture() && generation == captureGeneration) {
                    int count = local.read(frame, offset, frame.length - offset, AudioRecord.READ_BLOCKING);
                    if (count < 0) throw new IllegalStateException("麦克风读取失败");
                    if (count == 0) { Thread.sleep(5); continue; }
                    offset += count;
                }
                synchronized (turnLock) {
                    if (!mayCapture() || generation != captureGeneration || offset != frame.length) continue;
                    byte[] pcm = new byte[frame.length * 2];
                    for (int i = 0; i < frame.length; i++) { pcm[i * 2] = (byte) frame[i]; pcm[i * 2 + 1] = (byte) (frame[i] >>> 8); }
                    int result = vad.accept(frame);
                    VoiceRuntime.meter(this, vad.level());
                    if (utterance.isEmpty()) {
                        preroll.addLast(pcm);
                        while (preroll.size() > 10) preroll.removeFirst();
                    }
                    if (result == VoiceVad.START) {
                        utterance = UUID.randomUUID().toString(); currentTurn = utterance;
                        turnStartedAt = SystemClock.elapsedRealtime();
                        send(json("type", "audio_start", "id", utterance));
                        for (byte[] buffer : preroll) send(buffer);
                        preroll.clear();
                        VoiceRuntime.update(this, "recording", "正在听你说话");
                    } else if (!utterance.isEmpty()) send(pcm);
                    if (result == VoiceVad.END && !utterance.isEmpty()) {
                        listening = false;
                        send(json("type", "audio_end", "id", utterance));
                        VoiceRuntime.update(this, "thinking", "Kira 正在思考");
                        utterance = "";
                    }
                }
            }
        } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        catch (Exception error) { if (active) fail("无法使用麦克风：" + safeMessage(error)); }
        finally {
            if (local != null) {
                try { if (recording) local.stop(); } catch (Exception ignored) { }
                local.release();
            }
            recorder = null;
        }
    }

    private void updateListening() {
        if (!active || !welcomed || !listening || player != null || !interruptId.isEmpty()) return;
        VoiceRuntime.update(this, "listening", muted ? "麦克风已静音" : "可以开始说话");
    }

    private void message(JSONObject message) {
        if (!active) return;
        String type = message.optString("type");
        if ("welcome".equals(type)) {
            if (welcomed || message.optInt("protocol", -1) != 1 || message.optString("call_id").isEmpty()) {
                fail("服务器语音协议不兼容"); return;
            }
            welcomed = true; listening = true;
            VoiceRuntime.welcome(this); updateListening();
            captureThread = new Thread(this::captureLoop, "Kira-voice-mic"); captureThread.start();
            return;
        }
        if ("error".equals(type)) {
            String id = message.optString("id");
            String reason = message.optString("message", message.optString("detail", "服务器未能完成通话"));
            if (welcomed && !id.isEmpty()) {
                if (!interruptId.isEmpty() || !id.equals(currentTurn)) return;
                // The server follows a turn failure with listening; keep this call alive.
                VoiceRuntime.transcript(this, "assistant", "本轮未完成：" + reason);
            } else fail(reason); // Authentication/protocol errors remain fatal.
            return;
        }
        if (!welcomed) { fail("服务器尚未确认语音连接"); return; }
        if ("pong".equals(type) || "heartbeat".equals(type)) return;
        if ("ping".equals(type)) { send(json("type", "pong")); return; }
        String id = message.optString("id");
        if ("state".equals(type)) {
            String next = message.optString("state");
            if (!interruptId.isEmpty()) {
                if ("listening".equals(next) && interruptId.equals(message.optString("interrupt_id"))) {
                    synchronized (turnLock) { interruptId = ""; currentTurn = ""; listening = true; captureGeneration++; }
                    quietUntil = SystemClock.elapsedRealtime() + 250; updateListening();
                }
                return;
            }
            if (!id.isEmpty() && !id.equals(currentTurn)) return;
            if ("listening".equals(next)) {
                // The server can finish before the local decoder/player. Never reopen the mic early.
                listening = true; updateListening();
            } else if ("thinking".equals(next) || "synthesizing".equals(next)) {
                listening = false;
                VoiceRuntime.update(this, next, "thinking".equals(next) ? "Kira 正在思考" : "正在生成回复声音");
            }
        } else if ("transcript".equals(type)) {
            if (!interruptId.isEmpty() || (!id.isEmpty() && !id.equals(currentTurn))) return;
            String role = message.optString("role");
            if ("user".equals(role) || "assistant".equals(role)) VoiceRuntime.transcript(this, role, message.optString("text"));
        } else if ("hangup".equals(type)) finish("idle", "服务器结束了通话");
    }

    private void play(File file, String id, long generation) {
        synchronized (pendingFiles) { pendingFiles.remove(file); }
        if (!active || !interruptId.isEmpty() || generation != replyGeneration || !id.equals(currentTurn)) { file.delete(); return; }
        clearPlayback();
        playbackFile = file;
        captureGeneration++; quietUntil = Long.MAX_VALUE;
        VoiceRuntime.meter(this, 0);
        VoiceRuntime.update(this, "playing", "Kira 正在说话");
        try {
            MediaPlayer next = new MediaPlayer(); player = next;
            next.setAudioAttributes(voiceAttributes());
            next.setDataSource(file.getAbsolutePath());
            next.setOnPreparedListener(prepared -> {
                if (!active || player != prepared) return;
                prepared.start();
                main.postDelayed(() -> { if (active && player == prepared) fail("回复音频过长，已停止播放"); }, 120000);
            });
            next.setOnCompletionListener(completed -> {
                if (player != completed) return;
                clearPlayback(); quietUntil = SystemClock.elapsedRealtime() + 350; updateListening();
            });
            next.setOnErrorListener((failed, what, extra) -> { if (player == failed) fail("无法播放服务器返回的声音，请检查 TTS 音频格式"); return true; });
            next.prepareAsync();
            main.postDelayed(() -> {
                if (active && player == next && !next.isPlaying()) fail("回复音频准备超时");
            }, 10000);
        } catch (Exception error) { fail("无法播放回复声音"); }
    }

    private void clearPlayback() {
        MediaPlayer old = player; player = null;
        if (old != null) {
            try { old.setOnCompletionListener(null); old.setOnErrorListener(null); old.setOnPreparedListener(null); old.release(); }
            catch (Exception ignored) { }
        }
        File oldFile = playbackFile; playbackFile = null;
        if (oldFile != null) oldFile.delete();
    }

    private void event(Runnable callback) {
        if (!active) return;
        if (queuedEvents.incrementAndGet() > 64) { queuedEvents.decrementAndGet(); fail("服务器消息过快，已断开通话"); return; }
        main.post(() -> { try { if (active) callback.run(); } finally { queuedEvents.decrementAndGet(); } });
    }

    private final class VoiceSocket extends WebSocketClient {
        private final String token, deviceId;
        private JSONObject expectedAudio;
        private long expectedGeneration;
        private String lastAudioId = "";
        VoiceSocket(URI uri, String token, String deviceId) {
            super(uri, new Draft_6455(Collections.singletonList(new DefaultExtension()),
                Collections.singletonList(new Protocol("")), MAX_AUDIO), null, 15000);
            this.token = token; this.deviceId = deviceId;
        }
        @Override protected void onSetSSLParameters(SSLParameters parameters) {
            if (!active) {
                SocketSecurity.closeNow(this);
                throw new IllegalStateException("Call cancelled");
            }
            parameters.setEndpointIdentificationAlgorithm("HTTPS");
        }
        @Override public void onOpen(ServerHandshake handshake) {
            if (!active) { SocketSecurity.closeNow(this); return; }
            VoiceCallService.this.send(json("type", "hello", "protocol", 1, "token", token, "device_id", deviceId,
                "name", Build.MANUFACTURER + " " + Build.MODEL));
        }
        @Override public void onMessage(String text) {
            if (!active) return;
            receivedAt = SystemClock.elapsedRealtime();
            if (text.length() > 16384) { fail("语音服务消息过大"); return; }
            try {
                JSONObject message = new JSONObject(text);
                if ("audio".equals(message.optString("type"))) {
                    if (!welcomed || expectedAudio != null || message.optInt("length", 0) <= 0
                            || message.optInt("length", 0) > MAX_AUDIO || message.optString("id").isEmpty()
                            || !message.optString("mime").startsWith("audio/")) {
                        fail("服务器回复的音频格式不正确"); return;
                    }
                    if (lastAudioId.equals(message.optString("id"))) { fail("服务器重复发送了回复音频"); return; }
                    lastAudioId = message.optString("id");
                    expectedAudio = message; expectedGeneration = replyGeneration;
                    return;
                }
                event(() -> message(message));
            } catch (Exception error) { fail("语音服务消息无法读取"); }
        }
        @Override public void onMessage(ByteBuffer bytes) {
            if (!active) return;
            receivedAt = SystemClock.elapsedRealtime();
            JSONObject header = expectedAudio; expectedAudio = null;
            long generation = expectedGeneration;
            if (header == null || bytes.remaining() != header.optInt("length") || bytes.remaining() > MAX_AUDIO) {
                fail("服务器回复音频长度不匹配"); return;
            }
            String id = header.optString("id");
            if (!interruptId.isEmpty() || !id.equals(currentTurn) || generation != replyGeneration) return;
            File temp = null;
            try {
                temp = File.createTempFile("kira-voice-", ".audio", getCacheDir());
                synchronized (pendingFiles) { pendingFiles.add(temp); }
                try (FileOutputStream output = new FileOutputStream(temp)) {
                    byte[] buffer = new byte[8192];
                    while (bytes.hasRemaining()) {
                        int count = Math.min(buffer.length, bytes.remaining()); bytes.get(buffer, 0, count); output.write(buffer, 0, count);
                    }
                }
                File ready = temp;
                synchronized (pendingFiles) {
                    if (active) main.post(() -> play(ready, id, generation));
                    else { pendingFiles.remove(ready); ready.delete(); }
                }
            } catch (Exception error) {
                if (temp != null) { synchronized (pendingFiles) { pendingFiles.remove(temp); temp.delete(); } }
                fail("无法保存回复音频，请检查手机剩余空间");
            }
        }
        @Override public void onClose(int code, String reason, boolean remote) {
            if (active) fail(code == 1008 ? "通话被服务器拒绝，请检查连接密码和插件语音设置" : "语音连接已断开，请重新拨打");
        }
        @Override public void onError(Exception error) { if (active) fail("语音连接失败，请检查地址、校验码和网络"); }
    }

    private static JSONObject json(Object... fields) {
        try {
            JSONObject object = new JSONObject();
            for (int i = 0; i < fields.length; i += 2) object.put((String) fields[i], fields[i + 1]);
            return object;
        } catch (Exception error) { throw new IllegalArgumentException(error); }
    }
    private static String safeMessage(Exception error) {
        if (error instanceof SecurityException) return "系统未授予所需音频权限";
        String message = error.getMessage();
        return message == null || message.length() > 160 ? "请检查音频权限和网络设置" : message;
    }
    private void fail(String reason) { main.post(() -> { if (active) finish("error", reason); }); }

    void finish(String status, String detail) {
        if (closing) return;
        closing = true; endStatus = status; endDetail = detail;
        active = false; welcomed = false; listening = false; captureGeneration++; replyGeneration++;
        synchronized (pendingFiles) {
            main.removeCallbacksAndMessages(null);
            for (File file : pendingFiles) file.delete();
            pendingFiles.clear();
        }
        outgoing.clear();
        if (writerThread != null) writerThread.interrupt();
        if (captureThread != null) captureThread.interrupt();
        AudioRecord microphone = recorder;
        if (microphone != null) { try { microphone.stop(); } catch (Exception ignored) { } }
        SocketSecurity.closeNow(socket);
        clearPlayback();
        if (audioManager != null) {
            if (focus != null) { try { audioManager.abandonAudioFocusRequest(focus); } catch (Exception ignored) { } }
            if (routeSaved) {
                try {
                    if (Build.VERSION.SDK_INT >= 31) {
                        if (oldCommunicationDevice != null) audioManager.setCommunicationDevice(oldCommunicationDevice);
                        else audioManager.clearCommunicationDevice();
                    } else audioManager.setSpeakerphoneOn(oldSpeaker);
                    audioManager.setMode(oldMode);
                } catch (Exception ignored) { }
            }
        }
        stopForeground(true);
        VoiceRuntime.ended(this, status, detail);
        stopSelf();
    }

    @Override public void onDestroy() { finish(endStatus, endDetail); VoiceRuntime.destroyed(this); super.onDestroy(); }
}
