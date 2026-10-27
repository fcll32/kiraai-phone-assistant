package top.kira.phone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import org.java_websocket.drafts.Draft_6455;
import org.java_websocket.extensions.DefaultExtension;
import org.java_websocket.protocols.Protocol;
import org.json.JSONObject;
import javax.net.ssl.SSLParameters;
import java.net.URI;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public class ConnectionService extends Service {
    public static volatile String status = "已停止";
    public static volatile boolean running;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean busy = new AtomicBoolean();
    private final Set<String> completedIds = Collections.synchronizedSet(new LinkedHashSet<>());
    private volatile PhoneSocket socket;
    private volatile boolean active;
    private int retry;
    private volatile long lastReceived;
    private volatile boolean welcomed;
    private volatile boolean fatalFailure;
    private boolean reconnectPending;
    private volatile String lastFailure = "";
    private String stoppedStatus = "已停止";
    private SharedPreferences prefs() { return getSharedPreferences("connection", MODE_PRIVATE); }

    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int id) {
        if (intent != null && "stop".equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        // Repeated start intents must not overwrite the authenticated status.
        if (active) return START_NOT_STICKY;
        NotificationManager manager = (NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel("connection", "手机控制连接", NotificationManager.IMPORTANCE_LOW));
        Notification notification = notification("正在连接你的服务器");
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(1, notification);
        active = true; running = true; retry = 0; lastFailure = ""; connect(); main.postDelayed(heartbeat, 20000);
        return START_NOT_STICKY;
    }
    private Notification notification(String message) {
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (launch == null) launch = new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            android.net.Uri.parse("package:" + getPackageName()));
        PendingIntent open = PendingIntent.getActivity(this, 0, launch, flags);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, ConnectionService.class).setAction("stop"), flags);
        return new Notification.Builder(this, "connection").setContentTitle(getApplicationInfo().loadLabel(getPackageManager()))
            .setContentText(message).setSmallIcon(android.R.drawable.stat_notify_sync).setOngoing(true)
            .setContentIntent(open).addAction(new Notification.Action.Builder(null,"停止控制",stop).build()).build();
    }
    private void update(String message) {
        status = message;
        if (active) ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(1, notification(message));
    }
    private void connect() {
        if (!active) return;
        if (PhoneAccessibility.instance == null) { stoppedStatus = "无障碍服务已关闭，请重新启用"; update(stoppedStatus); stopSelf(); return; }
        try {
            URI uri = URI.create(prefs().getString("url", ""));
            if (!"wss".equals(uri.getScheme()) || uri.getHost() == null) throw new IllegalArgumentException("仅支持 WSS 加密地址");
            PhoneSocket client = new PhoneSocket(uri);
            String pin = prefs().getString("pin", "");
            client.setSocketFactory(SocketSecurity.factory(pin));
            client.setConnectionLostTimeout(40);
            socket = client; welcomed = false; fatalFailure = false; lastReceived = SystemClock.elapsedRealtime();
            update(lastFailure.isEmpty() ? "正在连接 " + uri.getHost() : lastFailure);
            client.connect();
            main.postDelayed(() -> {
                if (!active || socket != client || welcomed || fatalFailure || client.closing || client.isClosed()) return;
                // Socket.connect() is bounded, but Java-WebSocket does not put a read
                // timeout on TLS or the WebSocket upgrade/handshake. Close it ourselves
                // so a half-open peer cannot leave the UI on "connecting" forever.
                lastFailure = "连接超时：服务器端口已接受连接，但没有完成 TLS/WebSocket 握手或认证应答。请确认地址中的端口是 KiraAI 手机连接页显示的端口，并检查服务器日志。正在重试…";
                update(lastFailure);
                client.closing = true;
                socket = null;
                SocketSecurity.closeNow(client);
                reconnect();
            }, 20000);
        } catch (Exception e) {
            PhoneSocket failed = socket; socket = null;
            SocketSecurity.closeNow(failed);
            String message = ConnectionFailure.message(e);
            lastFailure = message;
            update(message);
            if (ConnectionFailure.permanent(e)) { stoppedStatus = message; stopSelf(); }
            else reconnect();
        }
    }
    private void reconnect() {
        if (!active || fatalFailure || reconnectPending) return;
        reconnectPending = true;
        int delay = Math.min(30, 1 << Math.min(5, retry++));
        main.postDelayed(() -> {
            reconnectPending = false;
            if (active && !fatalFailure && (socket == null || socket.isClosed())) connect();
        }, delay * 1000L);
    }
    private final Runnable heartbeat = new Runnable() {
        public void run() {
            if (!active) return;
            PhoneSocket client = socket;
            if (client != null && client.isOpen()) {
                try {
                    if (SystemClock.elapsedRealtime() - lastReceived > 65000) client.close(1001,"Heartbeat timeout");
                    else client.send("{\"type\":\"heartbeat\"}");
                } catch (RuntimeException ignored) { client.close(); }
            }
            main.postDelayed(this, 20000);
        }
    };
    private class PhoneSocket extends WebSocketClient {
        private volatile boolean closing;
        PhoneSocket(URI uri) {
            super(uri, new Draft_6455(Collections.singletonList(new DefaultExtension()),
                Collections.singletonList(new Protocol("")), 65536), null, 15000);
        }
        @Override protected void onSetSSLParameters(SSLParameters parameters) {
            // Stop may race socket creation. Recheck immediately before TLS blocks.
            if (!active || socket != this || closing) {
                SocketSecurity.closeNow(this);
                throw new IllegalStateException("Connection cancelled");
            }
            parameters.setEndpointIdentificationAlgorithm("HTTPS");
        }
        @Override public void onOpen(ServerHandshake handshake) {
            if (!active || socket != this) { SocketSecurity.closeNow(this); return; }
            try {
                send(new JSONObject().put("type","hello").put("protocol",PhoneRuntime.PROTOCOL_VERSION)
                    .put("token",prefs().getString("token", ""))
                    .put("device_id",prefs().getString("device_id", ""))
                    .put("capabilities", new org.json.JSONArray().put("ui_tree").put("apps").put("apps_refresh"))
                    .put("name",Build.MANUFACTURER + " " + Build.MODEL).put("sdk",Build.VERSION.SDK_INT).toString());
            } catch (Exception e) { close(1002,"Invalid handshake"); }
        }
        @Override public void onMessage(String raw) {
            if (!active || socket != this) return;
            lastReceived = SystemClock.elapsedRealtime();
            try {
                if (raw.length() > 16384) throw new IllegalArgumentException("Command too large");
                JSONObject message = new JSONObject(raw); String type = message.optString("type");
                if (type.equals("welcome")) {
                    if (message.optInt("protocol", -1) != PhoneRuntime.PROTOCOL_VERSION) throw new IllegalArgumentException("Unsupported protocol");
                    welcomed = true; retry = 0; lastFailure = "";
                    main.post(() -> { if (active && socket == this) update("已连接 · 等待按需操作"); }); return;
                }
                if (type.equals("heartbeat_ack")) return;
                if (!welcomed || !type.equals("command")) throw new IllegalArgumentException("Unexpected message");
                String id = message.getString("id");
                if (!id.matches("[0-9a-f]{32}")) throw new IllegalArgumentException("Invalid request id");
                long ttl = message.getLong("ttl_ms");
                CommandGate gate = new CommandGate(() -> active && socket == this && isOpen(), SystemClock::elapsedRealtime, ttl);
                String method = message.getString("method"); JSONObject params = message.getJSONObject("params");
                if (completedIds.contains(id)) { respond(id, null, "重复请求已拒绝，避免重复操作"); return; }
                if (!busy.compareAndSet(false,true)) { respond(id,null,"手机正在执行上一项操作"); return; }
                try { worker.submit(() -> {
                    JSONObject data = null;
                    String error = null;
                    try {
                        gate.check();
                        PhoneAccessibility accessibility = PhoneAccessibility.instance;
                        if (accessibility == null) throw new IllegalStateException("请开启无障碍服务");
                        if (method.equals("screenshot")) data = accessibility.observe(
                            Math.max(320,Math.min(2560,params.optInt("max_edge",1280))), params.optString("image_format","png"), gate);
                        else if (method.equals("ui_tree")) data = accessibility.uiTree(gate);
                        else if (method.equals("apps")) data = accessibility.apps(params, gate);
                        else if (method.equals("action")) data = accessibility.action(params, gate);
                        else throw new IllegalArgumentException("未知方法");
                        gate.check();
                    } catch (Exception e) {
                        Throwable reason = e.getCause() == null ? e : e.getCause();
                        error = reason.getMessage() == null ? reason.getClass().getSimpleName() : reason.getMessage();
                    } finally { busy.set(false); }
                    // Publish availability before the reply can trigger the next command.
                    // The single worker still serializes execution; do not clear busy again
                    // after sending, since the next request may already own that flag.
                    respond(id,data,error);
                }); } catch (java.util.concurrent.RejectedExecutionException error) { busy.set(false); throw error; }
                synchronized (completedIds) {
                    completedIds.add(id);
                    if (completedIds.size() > 256) completedIds.remove(completedIds.iterator().next());
                }
            } catch (Exception e) { close(1002,"Invalid command"); }
        }
        private void respond(String id, JSONObject data, String error) {
            if (!active || socket != this || !isOpen()) return;
            try { send(new JSONObject().put("type","result").put("id",id).put("ok",error == null)
                .put("data",data == null ? new JSONObject() : data).put("error",error == null ? "" : error).toString()); }
            catch (Exception e) { close(1011,"Response failed"); }
        }
        @Override public void onClose(int code, String reason, boolean remote) {
            if (socket != this || !active) return;
            main.post(() -> {
                if (!active || socket != this) return;
                if (fatalFailure) { stoppedStatus = lastFailure; update(stoppedStatus); stopSelf(); }
                else if (code == 1008) { stoppedStatus = "连接密码或指定手机不匹配，请检查插件设置后重连"; update(stoppedStatus); stopSelf(); }
                else if (code == 1013) { lastFailure = ConnectionFailure.message(new IllegalStateException("already connected")); update(lastFailure); reconnect(); }
                else { if (lastFailure.isEmpty()) lastFailure = "连接已断开，正在重连"; update(lastFailure); reconnect(); }
            });
        }
        @Override public void onError(Exception error) {
            if (socket != this || !active || closing) return;
            final String message = ConnectionFailure.message(error);
            lastFailure = message;
            final boolean fatal = ConnectionFailure.permanent(error);
            fatalFailure = fatal;
            // Closing the socket to reach onClose can raise a second "Socket closed"
            // callback. Keep the first cause instead of replacing it with our own close.
            if (!fatal) { closing = true; try { close(); } catch (RuntimeException ignored) { } }
            main.post(() -> {
                if (!active || socket != this) return;
                update(message);
                if (fatal) { stoppedStatus = message; stopSelf(); }
                else reconnect();
            });
        }
    }
    @Override public void onDestroy() {
        active = false; running = false; main.removeCallbacksAndMessages(null);
        PhoneSocket client = socket; socket = null;
        SocketSecurity.closeNow(client);
        worker.shutdownNow(); busy.set(false); status = stoppedStatus;
        stopForeground(true); super.onDestroy();
    }
}
