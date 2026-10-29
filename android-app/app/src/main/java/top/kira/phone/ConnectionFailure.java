package top.kira.phone;

import java.util.Locale;

/** Translate transport failures into an actionable phone-side message. */
final class ConnectionFailure {
    private ConnectionFailure() { }

    static String message(Throwable failure) {
        String detail = detail(failure);
        String text = detail.toLowerCase(Locale.ROOT);
        if (text.contains("fingerprint mismatch")) {
            return "服务器校验码与证书不一致。请回到插件页面重新复制校验码；更换公网 IP 后旧校验码会失效。";
        }
        if (text.contains("notvalid") || text.contains("notyetvalid") || text.contains("not valid") || text.contains("expired")) {
            return "服务器证书已过期，或手机时间不准确。请先校准手机时间；仍然失败就在插件页重新保存设置并复制新校验码。";
        }
        if (text.contains("unknownhost") || text.contains("unable to resolve")) {
            return "找不到服务器地址。请检查地址是否复制完整，以及手机能否正常上网。正在重试…";
        }
        if (text.contains("subject alternative") || text.contains("subjectaltnames") || text.contains("no name matching")) {
            return "服务器证书和填写的地址不一致。请整行复制插件页的服务器地址和校验码。";
        }
        if (text.contains("trust anchor") || text.contains("unable to find valid certification path")) {
            return "服务器证书未被信任。内置连接服务需要填写插件页的校验码；使用反向代理时请核对实际入口证书。";
        }
        if (certificateFailure(failure)) {
            return "服务器证书验证失败。请检查证书、地址、校验码和两端时间。原因：" + detail;
        }
        if (wrongProtocol(text)) {
            return "端口可能接到了普通 HTTP 或其他非 TLS 服务。请核对加密入口的映射；共用入口通常为公网 5267 → 容器 8443，不能仍接到容器内的普通 HTTP 5267。原因：" + detail;
        }
        if (text.contains("503") || text.contains("service unavailable")) {
            return "服务器暂时拒绝连接：可能已有另一台手机在线，或连接数已满。正在重试…";
        }
        if (text.contains("1013") || text.contains("already connected")) {
            return "服务器显示已有一台手机在线。请先在原手机停止连接，或等待旧连接超时。正在重试…";
        }
        if (text.contains("timed out") || text.contains("timeout")) {
            return "连接服务器超时。请确认公网 IP 和端口已在安全组、防火墙及 Docker 中放行。正在重试…";
        }
        if ((text.contains("ssl") || text.contains("tls")) && (text.contains("reset")
                || text.contains("closed") || text.contains("terminated") || text.contains("aborted") || text.contains("eof"))) {
            return "加密握手被中断，并不代表密码或校验码填错。请检查端口映射和 VPN/代理。原因：" + detail + "。正在重试…";
        }
        if (text.contains("refused") || text.contains("reset") || text.contains("unreachable")) {
            return "服务器端口拒绝连接。请确认插件页的地址和端口与实际开放端口一致。正在重试…";
        }
        if (text.contains("socket closed")) {
            return "服务器在连接建立时关闭了连接。请确认插件页显示连接服务正常、端口转发完整，并查看 KiraAI 日志。正在重试…";
        }
        if (failure instanceof IllegalArgumentException) {
            return "连接配置无效：" + detail;
        }
        if (text.contains("ssl") || text.contains("tls") || text.contains("certificate")) {
            return "无法完成加密握手（TLS）。请检查端口是否指向插件的加密服务，并对比关闭 VPN/代理后的连接。原因：" + detail
                + (permanent(failure) ? "。请修正证书或连接设置后重试。" : "。正在重试…");
        }
        return "连接失败（" + detail + "）。正在重试…";
    }

    static boolean permanent(Throwable failure) {
        String text = detail(failure).toLowerCase(Locale.ROOT);
        return failure instanceof IllegalArgumentException
            || text.contains("fingerprint mismatch")
            || text.contains("notvalid") || text.contains("notyetvalid") || text.contains("not valid") || text.contains("expired")
            || text.contains("subject alternative") || text.contains("subjectaltnames") || text.contains("no name matching")
            || text.contains("trust anchor") || text.contains("unable to find valid certification path")
            || wrongProtocol(text) || certificateFailure(failure);
    }

    private static boolean wrongProtocol(String text) {
        return text.contains("wrong version number") || text.contains("unrecognized ssl message")
            || text.contains("not an ssl/tls record");
    }

    private static boolean certificateFailure(Throwable failure) {
        for (int depth = 0; failure != null && depth < 6; depth++, failure = failure.getCause())
            if (failure instanceof java.security.cert.CertificateException) return true;
        return false;
    }

    private static String detail(Throwable failure) {
        StringBuilder value = new StringBuilder();
        for (int depth = 0; failure != null && depth < 6; depth++, failure = failure.getCause()) {
            String message = failure.getMessage();
            String name = failure.getClass().getSimpleName();
            if (value.length() > 0) value.append(" → ");
            value.append(name);
            if (message != null && !message.trim().isEmpty())
                value.append(": ").append(message.replaceAll("[\\p{Cntrl}]", " ").trim());
        }
        return value.length() == 0 ? "未知错误" : value.toString();
    }
}
