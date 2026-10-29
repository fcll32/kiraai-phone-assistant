package top.kira.phone;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;
import androidx.core.content.FileProvider;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/** Public GitHub updates. No phone credentials, permissive TLS, or silent installs. */
public final class UpdateRuntime {
    public static final class ApkProvider extends FileProvider { public ApkProvider() { super(); } }
    private static final Object LOCK = new Object();
    private static final ExecutorService WORK = Executors.newSingleThreadExecutor(r -> { Thread t = new Thread(r, "kira-update"); t.setDaemon(true); return t; });
    private static final ScheduledExecutorService TIMER = Executors.newSingleThreadScheduledExecutor(r -> { Thread t = new Thread(r, "kira-update-progress"); t.setDaemon(true); return t; });
    private static volatile Context app;
    private static volatile String snapshot = "{\"status\":\"idle\",\"detail\":\"从 GitHub 正式发布检查新版\",\"progress\":0}";
    private static volatile HttpURLConnection connection;
    private static long generation = 0, downloadId = -1;
    private static long lastQuietCheck = -1;
    private static JSONObject release;
    private static File file;
    private static String status = "idle", detail = "从 GitHub 正式发布检查新版";
    private static long downloaded = 0;
    private static ScheduledFuture<?> poll;
    private UpdateRuntime() { }
    private static SharedPreferences prefs() { return app.getSharedPreferences("app_update", Context.MODE_PRIVATE); }
    private static DownloadManager manager() { return (DownloadManager) app.getSystemService(Context.DOWNLOAD_SERVICE); }
    private static String repo() {
        int id = app.getResources().getIdentifier("update_repository", "string", app.getPackageName());
        if (id == 0) throw new IllegalStateException("安装包缺少更新仓库配置");
        return UpdatePolicy.repository(app.getString(id));
    }
    private static void ensure(Context context) {
        if (app != null) return;
        synchronized (LOCK) {
            if (app != null) return;
            app = context.getApplicationContext(); WORK.execute(UpdateRuntime::restore);
        }
    }
    private static boolean current(long value) { synchronized (LOCK) { return generation == value; } }
    private static boolean busy() { return Arrays.asList("checking", "downloading", "verifying").contains(status); }
    private static void publish(long ticket, String next, String message, long bytes) {
        synchronized (LOCK) {
            if (ticket != generation) return;
            status = next; detail = message; downloaded = bytes;
            try {
                long total = release == null ? 0 : release.optLong("size");
                snapshot = new JSONObject().put("status", next).put("detail", message)
                    .put("version", release == null ? "" : release.optString("version"))
                    .put("notes", release == null ? "" : release.optString("notes"))
                    .put("bytes", bytes).put("total", total)
                    .put("progress", total > 0 ? Math.max(0, Math.min(1, (double) bytes / total)) : 0).toString();
            } catch (Exception ignored) { }
        }
    }
    public static String state(Context context) { ensure(context); return snapshot; }
    public static String projectUrl(Context context) { ensure(context); return "https://github.com/" + repo(); }
    public static void openProject(Activity activity) {
        if (activity == null || activity.isFinishing()) throw new IllegalStateException("请回到 App 后再打开项目");
        try { activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(projectUrl(activity))).addCategory(Intent.CATEGORY_BROWSABLE)); }
        catch (android.content.ActivityNotFoundException error) { throw new IllegalStateException("未找到浏览器，请手动访问 GitHub 项目", error); }
    }
    public static void checkQuietly(Context context) {
        ensure(context);
        // Queue behind restore: never discard a download that is being restored.
        WORK.execute(() -> {
            synchronized (LOCK) {
                long now = android.os.SystemClock.elapsedRealtime();
                if (busy() || release != null || (lastQuietCheck >= 0 && now - lastQuietCheck < TimeUnit.HOURS.toMillis(6))) return;
                lastQuietCheck = now;
                check(context);
            }
        });
    }
    public static void check(Context context) {
        ensure(context); final long ticket;
        synchronized (LOCK) {
            if (busy()) return;
            ticket = ++generation; publish(ticket, "checking", "正在检查 GitHub 正式发布…", 0);
        }
        WORK.execute(() -> {
            try {
                synchronized (LOCK) { if (!current(ticket)) return; clearDownload(); release = null; }
                JSONObject root = new JSONObject(fetch("https://api.github.com/repos/" + repo() + "/releases/latest", ticket));
                if (root.optBoolean("draft") || root.optBoolean("prerelease")) throw new IllegalArgumentException("暂时没有正式版本");
                String tag = root.getString("tag_name"), version = UpdatePolicy.version(tag);
                PackageInfo installed = app.getPackageManager().getPackageInfo(app.getPackageName(), 0);
                if (UpdatePolicy.compare(version, installed.versionName) <= 0) { publish(ticket, "latest", "当前已是最新正式版本", 0); return; }
                JSONArray assets = root.getJSONArray("assets"); JSONObject apk = null, sums = null;
                String name = UpdatePolicy.apkName(tag);
                for (int i = 0; i < assets.length(); i++) {
                    JSONObject asset = assets.getJSONObject(i);
                    if (name.equals(asset.optString("name"))) apk = asset;
                    if ("SHA256SUMS.txt".equals(asset.optString("name"))) sums = asset;
                }
                if (apk == null) throw new IllegalArgumentException("新版尚未上传手机安装包，请稍后再试");
                String hash;
                try { hash = UpdatePolicy.digest(apk.optString("digest")); }
                catch (IllegalArgumentException missing) {
                    if (sums == null) throw missing;
                    hash = UpdatePolicy.checksum(fetch(UpdatePolicy.assetUrl(repo(), tag, "SHA256SUMS.txt", sums.getString("browser_download_url")), ticket), name);
                }
                String notes = root.isNull("body") ? "" : root.optString("body"); if (notes.length() > 4000) notes = notes.substring(0, 4000);
                JSONObject next = new JSONObject().put("version", version).put("tag", tag).put("name", name)
                    .put("url", UpdatePolicy.assetUrl(repo(), tag, name, apk.getString("browser_download_url")))
                    .put("size", UpdatePolicy.size(apk.getLong("size"))).put("sha256", hash).put("notes", notes);
                synchronized (LOCK) { if (!current(ticket)) return; clearDownload(); release = next; }
                publish(ticket, "available", "发现新版，点下载后才会下载安装包", 0);
            } catch (Exception error) { failed(ticket, error); }
        });
    }
    public static void download(Context context) {
        ensure(context); final long ticket; final JSONObject info; final File target;
        synchronized (LOCK) {
            if (busy() || release == null) return;
            ticket = ++generation; info = release;
            File directory = app.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
            if (directory == null) throw new IllegalStateException("手机暂时无法保存安装包");
            target = new File(directory, "updates/kira-update-" + UUID.randomUUID() + ".apk");
            publish(ticket, "downloading", "准备下载…", 0);
        }
        WORK.execute(() -> {
            long id = -1;
            try {
                synchronized (LOCK) { if (!current(ticket)) return; clearDownload(); file = target; }
                File parent = target.getParentFile();
                if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) throw new IllegalStateException("无法保存安装包，请检查手机存储空间");
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(info.getString("url")))
                    .setTitle("KiraAI 手机助手 " + info.getString("version"))
                    .setDescription("下载完成后回到 App 确认安装")
                    .setMimeType("application/vnd.android.package-archive")
                    .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    .setDestinationInExternalFilesDir(app, Environment.DIRECTORY_DOWNLOADS, "updates/" + target.getName());
                id = manager().enqueue(request);
                synchronized (LOCK) {
                    if (!current(ticket)) { manager().remove(id); return; }
                    downloadId = id; save(); startPoll(ticket);
                }
            } catch (Exception error) { if (id >= 0) manager().remove(id); failed(ticket, error); }
        });
    }
    public static void cancel(Context context) {
        ensure(context);
        synchronized (LOCK) {
            long ticket = ++generation; stopPoll(); publish(ticket, "cancelled", "已取消，可以重新检查或下载", 0);
            HttpURLConnection active = connection;
            long oldId = downloadId; File oldFile = file; downloadId = -1; file = null; prefs().edit().clear().apply();
            TIMER.execute(() -> {
                try { if (active != null) active.disconnect(); } catch (RuntimeException ignored) { }
                try { if (oldId >= 0) manager().remove(oldId); } catch (RuntimeException ignored) { }
                if (oldFile != null) oldFile.delete();
            });
        }
    }
    private static void startPoll(long ticket) {
        stopPoll(); poll = TIMER.scheduleWithFixedDelay(() -> poll(ticket), 0, 1, TimeUnit.SECONDS);
    }
    private static void stopPoll() { if (poll != null) poll.cancel(false); poll = null; }
    private static void poll(long ticket) {
        try {
            final long id; synchronized (LOCK) { if (!current(ticket)) return; id = downloadId; }
            try (Cursor row = manager().query(new DownloadManager.Query().setFilterById(id))) {
                if (row == null || !row.moveToFirst()) throw new IllegalArgumentException("下载任务已被移除，请重新下载");
                int next = row.getInt(row.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                long bytes = row.getLong(row.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR));
                if (bytes > UpdatePolicy.MAX_APK_BYTES) throw new IllegalArgumentException("安装包超过大小限制");
                if (next == DownloadManager.STATUS_FAILED) throw new IllegalArgumentException("下载失败，请检查网络或存储空间后重试");
                if (next == DownloadManager.STATUS_SUCCESSFUL) {
                    synchronized (LOCK) { if (!current(ticket) || !"downloading".equals(status)) return; stopPoll(); publish(ticket, "verifying", "正在校验安装包…", bytes); }
                    WORK.execute(() -> { try { verify(ticket); publish(ticket, "ready", "下载和校验完成，点安装更新", bytes); } catch (Exception error) { failed(ticket, error); } });
                } else publish(ticket, "downloading", next == DownloadManager.STATUS_PAUSED ? "下载已暂停，等待网络恢复…" : "正在下载，可离开这个页面", bytes);
            }
        } catch (Exception error) { failed(ticket, error); }
    }
    public static void install(Activity activity) {
        ensure(activity); final long ticket;
        synchronized (LOCK) {
            if (!Arrays.asList("ready", "permission").contains(status)) return;
            ticket = ++generation; publish(ticket, "verifying", "安装前再次校验…", downloaded);
        }
        WORK.execute(() -> {
            try {
                verify(ticket);
                activity.runOnUiThread(() -> {
                    synchronized (LOCK) {
                        if (!current(ticket)) return;
                        try {
                            if (activity.isFinishing() || activity.isDestroyed() || !activity.hasWindowFocus()) throw new IllegalStateException("请回到 App 再点安装更新");
                            synchronized (VoiceRuntime.AUDIO_LOCK) {
                                if (ConnectionService.running || VoiceRuntime.isActive() || VirtualMicRuntime.isActive()) throw new IllegalStateException("请先停止手机连接、通话和测试，再安装更新");
                                if (!activity.getPackageManager().canRequestPackageInstalls()) {
                                    publish(ticket, "permission", "请允许安装应用，返回后再点“安装更新”", downloaded);
                                    activity.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + app.getPackageName()))); return;
                                }
                                Uri uri = FileProvider.getUriForFile(app, app.getPackageName() + ".updates", file);
                                Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                                intent.setClipData(ClipData.newRawUri("KiraAI update", uri));
                                activity.startActivity(intent); publish(ticket, "ready", "请在系统安装页面确认；取消后可以重试", downloaded);
                            }
                        } catch (Exception error) { publish(ticket, "ready", error instanceof IllegalStateException ? error.getMessage() : "无法打开系统安装页面，请稍后重试", downloaded); }
                    }
                });
            } catch (Exception error) { failed(ticket, error); }
        });
    }
    private static long code(PackageInfo info) { return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode; }
    private static Set<String> signers(PackageInfo info) {
        Signature[] signatures = Build.VERSION.SDK_INT >= 28 ? (info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners()) : info.signatures;
        Set<String> result = new HashSet<>();
        if (signatures != null) for (Signature signature : signatures) result.add(signature.toCharsString());
        return result;
    }
    private static void verify(long ticket) throws Exception {
        final JSONObject info; final File target;
        synchronized (LOCK) { if (!current(ticket)) throw new InterruptedException(); info = release; target = file; }
        if (info == null || target == null) throw new IllegalArgumentException("安装包已不存在，请重新下载");
        UpdatePolicy.verifyFile(target, info.getLong("size"), info.getString("sha256"), () -> current(ticket));
        PackageManager pm = app.getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo archive = pm.getPackageArchiveInfo(target.getAbsolutePath(), flags), installed = pm.getPackageInfo(app.getPackageName(), flags);
        if (archive == null || archive.applicationInfo == null) throw new IllegalArgumentException("安装包无法读取，请重新下载");
        UpdatePolicy.verifyIdentity(app.getPackageName(), info.getString("version"), code(installed),
            archive.packageName, archive.versionName, code(archive), archive.applicationInfo.minSdkVersion,
            Build.VERSION.SDK_INT, signers(installed), signers(archive));
        if (!current(ticket)) throw new InterruptedException();
    }
    private static String fetch(String address, long ticket) throws Exception {
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(25);
        for (int hop = 0; hop < 6; hop++) {
            if (!current(ticket)) throw new InterruptedException();
            if (System.nanoTime() > deadline) throw new java.net.SocketTimeoutException();
            URL url = new URL(address);
            if (!"https".equals(url.getProtocol()) || url.getUserInfo() != null || (url.getPort() != -1 && url.getPort() != 443)
                    || !Arrays.asList("api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com").contains(url.getHost()))
                throw new IllegalArgumentException("更新服务返回了不受支持的地址");
            HttpURLConnection request = (HttpURLConnection) url.openConnection(); connection = request;
            try {
                if (!current(ticket)) throw new InterruptedException();
                request.setConnectTimeout(8000); request.setReadTimeout(10000); request.setInstanceFollowRedirects(false);
                request.setRequestProperty("User-Agent", "KiraAI-Phone-Assistant"); request.setRequestProperty("Accept", "application/vnd.github+json");
                int status = request.getResponseCode();
                if (status >= 300 && status < 400) { String location = request.getHeaderField("Location"); if (location == null) throw new IllegalArgumentException("更新服务重定向无效"); address = new URL(url, location).toString(); continue; }
                if (status != 200) throw new IllegalArgumentException(status == 404 ? "暂时没有可用的正式发布" : status == 403 || status == 429 ? "GitHub 访问频率受限，请稍后再试" : "更新服务暂时不可用（HTTP " + status + "）");
                try (InputStream input = request.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[8192]; int count;
                    while ((count = input.read(buffer)) != -1) { if (!current(ticket)) throw new InterruptedException(); if (System.nanoTime() > deadline) throw new java.net.SocketTimeoutException(); if (output.size() + count > 512 * 1024) throw new IllegalArgumentException("更新信息过大"); output.write(buffer, 0, count); }
                    return new String(output.toByteArray(), StandardCharsets.UTF_8);
                }
            } finally { if (connection == request) connection = null; request.disconnect(); }
        }
        throw new IllegalArgumentException("更新服务跳转过多，请稍后重试");
    }
    private static void failed(long ticket, Exception error) {
        synchronized (LOCK) {
            if (!current(ticket)) return;
            stopPoll(); clearDownload();
            publish(ticket, "error", error instanceof IllegalArgumentException || error instanceof IllegalStateException ? error.getMessage() : "更新失败，请检查网络或存储空间后重试", 0);
        }
    }
    private static void clearDownload() {
        stopPoll(); if (downloadId >= 0) { try { manager().remove(downloadId); } catch (RuntimeException ignored) { } }; downloadId = -1;
        if (file != null) file.delete(); file = null; prefs().edit().clear().apply();
    }
    private static void save() throws Exception {
        JSONObject value = new JSONObject().put("release", release).put("id", downloadId).put("file", file.getName());
        if (!prefs().edit().putString("task", value.toString()).commit()) throw new IllegalStateException("无法保存下载进度，请重试");
    }
    private static void restore() {
        synchronized (LOCK) {
            try {
                String saved = prefs().getString("task", ""); if (saved.isEmpty()) return;
                JSONObject value = new JSONObject(saved), info = value.getJSONObject("release");
                UpdatePolicy.version(info.getString("version")); UpdatePolicy.size(info.getLong("size")); UpdatePolicy.digest(info.getString("sha256"));
                UpdatePolicy.assetUrl(repo(), info.getString("tag"), UpdatePolicy.apkName(info.getString("tag")), info.getString("url"));
                String name = value.getString("file"); if (!name.matches("kira-update-[a-zA-Z0-9-]+\\.apk")) throw new IllegalArgumentException();
                File directory = app.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS); if (directory == null) throw new IllegalStateException();
                release = info; downloadId = value.getLong("id"); file = new File(directory, "updates/" + name);
                if (generation != 0) { clearDownload(); release = null; return; }
                PackageInfo installed = app.getPackageManager().getPackageInfo(app.getPackageName(), 0);
                if (UpdatePolicy.compare(info.getString("version"), installed.versionName) <= 0) { clearDownload(); release = null; publish(0, "latest", "当前已是最新正式版本", 0); return; }
                publish(0, "downloading", "正在恢复下载状态…", 0); startPoll(0);
            } catch (Exception error) { clearDownload(); publish(0, "idle", "可重新检查并下载新版", 0); }
        }
    }
}
