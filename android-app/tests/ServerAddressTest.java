package top.kira.phone;

public class ServerAddressTest {
    private static int checks;
    private static void equal(String expected, String actual) {
        checks++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    private static void rejected(String value) {
        checks++;
        try { ServerAddress.normalize(value); throw new AssertionError("Invalid address accepted: " + value); }
        catch (IllegalArgumentException expected) { }
    }
    public static void main(String[] args) {
        String suffix = ServerAddress.DEVICE_PATH;
        equal("wss://203.0.113.10:8443" + suffix, ServerAddress.normalize(" 203.0.113.10:8443 "));
        equal("wss://203.0.113.10:8443" + suffix, ServerAddress.normalize("203.0.113.10:8443/"));
        equal("wss://203.0.113.10:8443" + suffix, ServerAddress.normalize("wss://203.0.113.10:8443"));
        equal("wss://203.0.113.10:8443" + suffix, ServerAddress.normalize("wss://203.0.113.10:8443" + suffix));
        equal("wss://example.org:8443" + suffix, ServerAddress.normalize("example.org:8443"));
        equal("wss://[2001:db8::1]:8443" + suffix, ServerAddress.normalize("[2001:db8::1]:8443"));
        equal("wss://example.org/phone/custom", ServerAddress.normalize("wss://example.org/phone/custom"));
        equal("wss://example.org/phone%20custom", ServerAddress.normalize("wss://example.org/phone%20custom"));
        equal("203.0.113.10:8443", ServerAddress.display("wss://203.0.113.10:8443" + suffix));
        equal("[2001:db8::1]:8443", ServerAddress.display("wss://[2001:db8::1]:8443" + suffix));
        equal("example.org:443", ServerAddress.display("wss://example.org" + suffix));
        equal("wss://example.org/phone/custom", ServerAddress.display("wss://example.org/phone/custom"));
        for (String value : new String[]{"", "203.0.113.10", "203.0.113.10:", "203.0.113.10:0", "203.0.113.10:65536",
            "203.0.113.10:abc", "http://203.0.113.10:8443", "ws://203.0.113.10:8443", "https://example.org",
            "user:password@203.0.113.10:8443", "203.0.113.10:8443?token=abc", "203.0.113.10:8443#section",
            "203.0.113.10:8443\nother", "2001:db8::1:8443"}) rejected(value);
        System.out.println("ServerAddress: " + checks + " checks passed");
    }
}
