package top.kira.phone;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.Locale;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** TLS helpers for a separate voice socket; hostname verification is still required. */
public final class SocketSecurity {
    private SocketSecurity() { }

    /** WebSocket close alone cannot interrupt an in-progress SSL handshake. */
    public static void closeNow(org.java_websocket.client.WebSocketClient client) {
        if (client == null) return;
        try { java.net.Socket raw = client.getSocket(); if (raw != null) raw.close(); } catch (Exception ignored) { }
        try { client.closeConnection(1000, "Stopped locally"); } catch (Exception ignored) { }
    }

    public static URI voiceUri(String address) {
        URI device = URI.create(ServerAddress.normalize(address));
        String path = device.getRawPath();
        if (path.endsWith("/device")) path = path.substring(0, path.length() - 7) + "/voice";
        else if (!path.endsWith("/voice"))
            throw new IllegalArgumentException("自定义服务器地址需要以 /device 结尾，才能连接通话服务");
        return URI.create("wss://" + device.getRawAuthority() + path);
    }

    public static SSLSocketFactory factory(String fingerprint) throws Exception {
        String pin = fingerprint == null ? "" : fingerprint.replaceAll("[\\s:]", "").toLowerCase(Locale.ROOT);
        if (pin.isEmpty()) return (SSLSocketFactory) SSLSocketFactory.getDefault();
        if (!pin.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("服务器校验码格式错误");
        final byte[] expected = pin.getBytes(StandardCharsets.US_ASCII);
        X509TrustManager trust = new X509TrustManager() {
            @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            @Override public void checkClientTrusted(X509Certificate[] chain, String authType) throws CertificateException {
                throw new CertificateException("Client certificate not supported");
            }
            @Override public void checkServerTrusted(X509Certificate[] chain, String authType) throws CertificateException {
                if (chain == null || chain.length == 0) throw new CertificateException("Missing certificate");
                chain[0].checkValidity();
                try {
                    byte[] digest = MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded());
                    StringBuilder hex = new StringBuilder(64);
                    for (byte b : digest) hex.append(String.format(Locale.ROOT, "%02x", b & 255));
                    if (!MessageDigest.isEqual(expected, hex.toString().getBytes(StandardCharsets.US_ASCII)))
                        throw new CertificateException("Certificate fingerprint mismatch");
                } catch (CertificateException error) { throw error; }
                catch (Exception error) { throw new CertificateException(error); }
            }
        };
        SSLContext tls = SSLContext.getInstance("TLS");
        tls.init(null, new TrustManager[]{trust}, null);
        return tls.getSocketFactory();
    }
}
