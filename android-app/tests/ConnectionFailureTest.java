package top.kira.phone;

import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.security.cert.CertificateException;

public class ConnectionFailureTest {
    private static int checks;

    private static void contains(String expected, Throwable failure) {
        checks++;
        String message = ConnectionFailure.message(failure);
        if (!message.contains(expected)) throw new AssertionError("Expected " + expected + " in " + message);
    }

    private static void rejected(Throwable failure) {
        checks++;
        if (ConnectionFailure.permanent(failure)) throw new AssertionError("Should retry: " + failure);
    }

    private static void permanent(Throwable failure) {
        checks++;
        if (!ConnectionFailure.permanent(failure)) throw new AssertionError("Should stop: " + failure);
    }

    public static void main(String[] args) {
        Throwable pin = new CertificateException("Server certificate fingerprint mismatch");
        contains("校验码", pin);
        permanent(pin);

        Throwable expired = new CertificateException("certificate expired");
        contains("手机时间", expired);
        permanent(expired);

        Throwable hostname = new CertificateException("No subject alternative names matching IP address");
        contains("地址不一致", hostname);
        permanent(hostname);

        contains("超时", new SocketTimeoutException("connect timed out"));
        rejected(new SocketTimeoutException("connect timed out"));

        contains("拒绝连接", new ConnectException("Connection refused"));
        rejected(new ConnectException("Connection refused"));

        contains("找不到服务器", new UnknownHostException("Unable to resolve hostname"));
        rejected(new UnknownHostException("Unable to resolve hostname"));

        contains("重试", new IllegalStateException("The HTTP response code was 503"));
        rejected(new IllegalStateException("The HTTP response code was 503"));

        contains("服务器在连接建立时关闭", new java.net.SocketException("Socket closed"));
        rejected(new java.net.SocketException("Socket closed"));

        contains("配置无效", new IllegalArgumentException("仅支持 WSS 加密地址"));
        permanent(new IllegalArgumentException("仅支持 WSS 加密地址"));

        Throwable interrupted = new javax.net.ssl.SSLHandshakeException("SSL handshake aborted: Connection reset by peer");
        contains("中断", interrupted);
        rejected(interrupted);

        Throwable closed = new javax.net.ssl.SSLHandshakeException("Remote host terminated the handshake");
        contains("中断", closed);
        rejected(closed);

        Throwable wrongPort = new javax.net.ssl.SSLException("Unable to parse TLS packet header: wrong version number");
        contains("端口可能接到了普通 HTTP", wrongPort);
        permanent(wrongPort);

        Throwable wrappedPin = new javax.net.ssl.SSLHandshakeException("SSL handshake aborted");
        wrappedPin.initCause(pin);
        contains("校验码", wrappedPin);
        permanent(wrappedPin);

        Throwable missingPin = new javax.net.ssl.SSLHandshakeException("Trust anchor for certification path not found");
        contains("未被信任", missingPin);
        permanent(missingPin);

        Throwable opaque = new javax.net.ssl.SSLHandshakeException("Handshake failed");
        contains("SSLHandshakeException", opaque);
        contains("Handshake failed", opaque);
        rejected(opaque);

        Throwable androidHostname = new CertificateException("No subjectAltNames on the certificate match");
        contains("地址不一致", androidHostname);
        permanent(androidHostname);

        System.out.println("ConnectionFailure: " + checks + " checks passed");
    }
}
