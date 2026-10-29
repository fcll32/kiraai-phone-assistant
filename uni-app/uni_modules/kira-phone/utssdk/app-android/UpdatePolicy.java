package top.kira.phone;

import java.io.File;
import java.io.FileInputStream;
import java.net.URI;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.function.BooleanSupplier;
import java.util.Set;

/** Pure update boundaries, also exercised on the JVM without Android. */
public final class UpdatePolicy {
    public static final long MAX_APK_BYTES = 200L * 1024 * 1024;
    private UpdatePolicy() { }
    public static String version(String tag) {
        if (tag == null || !tag.matches("[vV]?[0-9]{1,9}\\.[0-9]{1,9}\\.[0-9]{1,9}"))
            throw new IllegalArgumentException("发布版本格式不正确");
        return tag.replaceFirst("^[vV]", "");
    }
    public static int compare(String a, String b) {
        String[] left = version(a).split("\\."), right = version(b).split("\\.");
        for (int i = 0; i < 3; i++) {
            int result = Integer.compare(Integer.parseInt(left[i]), Integer.parseInt(right[i]));
            if (result != 0) return result;
        }
        return 0;
    }
    public static String repository(String value) {
        if (value == null || !value.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"))
            throw new IllegalArgumentException("更新仓库配置不正确");
        return value;
    }
    public static String apkName(String tag) { return "KiraAI-Phone-Assistant-" + version(tag) + ".apk"; }
    public static String assetUrl(String repo, String tag, String name, String value) {
        try {
            repository(repo); version(tag);
            if (!name.matches("[A-Za-z0-9_.-]+")) throw new IllegalArgumentException();
            URI uri = new URI(value);
            if (!"https".equals(uri.getScheme()) || !"github.com".equals(uri.getHost())
                    || (uri.getPort() != -1 && uri.getPort() != 443) || uri.getUserInfo() != null
                    || uri.getRawQuery() != null || uri.getRawFragment() != null
                    || !uri.getRawPath().equals("/" + repo + "/releases/download/" + tag + "/" + name))
                throw new IllegalArgumentException();
            return value;
        } catch (Exception error) { throw new IllegalArgumentException("更新地址不是当前仓库的正式发布包"); }
    }
    public static String digest(String value) {
        String hash = value == null ? "" : value.replaceFirst("^sha256:", "");
        if (!hash.matches("[0-9a-fA-F]{64}")) throw new IllegalArgumentException("发布包缺少完整性校验信息");
        return hash.toLowerCase(Locale.ROOT);
    }
    public static String checksum(String content, String name) {
        String found = null;
        for (String line : content.split("\\r?\\n")) {
            if (line.matches("[0-9a-fA-F]{64}  " + java.util.regex.Pattern.quote(name))) {
                if (found != null) throw new IllegalArgumentException("发布包校验信息重复");
                found = line.substring(0, 64);
            }
        }
        return digest(found);
    }
    public static long size(long value) {
        if (value <= 0 || value > MAX_APK_BYTES) throw new IllegalArgumentException("安装包大小不正确或超过 200 MB");
        return value;
    }
    public static void verifyIdentity(String application, String advertised, long currentCode,
            String archiveApplication, String archiveVersion, long archiveCode, int minimumSdk, int sdk,
            Set<String> installedSigners, Set<String> archiveSigners) {
        if (!application.equals(archiveApplication) || !advertised.equals(archiveVersion))
            throw new IllegalArgumentException("下载的不是当前 App 对应版本的安装包");
        if (minimumSdk > sdk) throw new IllegalArgumentException("新版暂不支持这台手机的 Android 版本");
        if (archiveCode <= currentCode) throw new IllegalArgumentException("新版内部版本码未递增或已安装，请重新检查发布包");
        if (installedSigners.isEmpty() || !installedSigners.equals(archiveSigners))
            throw new IllegalArgumentException("安装包签名不一致，无法覆盖更新；请联系发布者");
    }
    public static void verifyFile(File file, long expectedSize, String expectedHash, BooleanSupplier current) throws Exception {
        if (file.length() != size(expectedSize)) throw new IllegalArgumentException("安装包不完整，请重新下载");
        MessageDigest sha = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) {
                if (!current.getAsBoolean()) throw new InterruptedException("更新已取消");
                sha.update(buffer, 0, count);
            }
        }
        StringBuilder hash = new StringBuilder();
        for (byte b : sha.digest()) hash.append(String.format(Locale.ROOT, "%02x", b & 255));
        if (!current.getAsBoolean()) throw new InterruptedException("更新已取消");
        if (!MessageDigest.isEqual(hash.toString().getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                digest(expectedHash).getBytes(java.nio.charset.StandardCharsets.US_ASCII)))
            throw new IllegalArgumentException("安装包校验失败，请重新下载");
    }
}
