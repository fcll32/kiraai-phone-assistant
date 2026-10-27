package top.kira.phone;

import java.net.URI;
import java.net.URISyntaxException;

/** Accept a short server address while preserving existing full connection URLs. */
public final class ServerAddress {
    public static final String DEVICE_PATH = "/ws/plugin/phone_control/device";
    private ServerAddress() { }

    public static String normalize(String input) {
        String value = input == null ? "" : input.trim();
        if (value.isEmpty()) throw new IllegalArgumentException("请填写服务器 IP 和端口，例如 203.0.113.10:8443");
        if (value.length() > 2048) throw new IllegalArgumentException("服务器地址太长，请检查是否粘贴了其他内容");
        boolean full = value.contains("://");
        try {
            URI uri = new URI(full ? value : "wss://" + value);
            if (!"wss".equalsIgnoreCase(uri.getScheme()))
                throw new IllegalArgumentException("请填写 IP:端口，或原来的 wss:// 完整地址");
            if (uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null)
                throw new IllegalArgumentException("地址格式不正确，请只填写服务器 IP:端口");
            int port = uri.getPort();
            if ((!full && port == -1) || port == 0 || port > 65535 || uri.getRawAuthority().endsWith(":"))
                throw new IllegalArgumentException("请填写有效端口，例如 203.0.113.10:8443");
            String path = uri.getRawPath();
            if (path == null || path.isEmpty() || path.equals("/")) path = DEVICE_PATH;
            return "wss://" + uri.getRawAuthority() + path;
        } catch (URISyntaxException error) {
            throw new IllegalArgumentException("地址格式不正确，例如 203.0.113.10:8443；IPv6 请使用 [地址]:端口");
        }
    }

    public static String display(String saved) {
        if (saved == null || saved.isEmpty()) return "";
        try {
            URI uri = URI.create(normalize(saved));
            if (DEVICE_PATH.equals(uri.getRawPath())) {
                return uri.getRawAuthority() + (uri.getPort() == -1 ? ":443" : "");
            }
            return uri.toASCIIString();
        } catch (IllegalArgumentException error) { return saved; }
    }
}
