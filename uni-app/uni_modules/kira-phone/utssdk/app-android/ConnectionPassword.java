package top.kira.phone;

/** Shared by setup, control and voice; must match protocol.valid_password. */
public final class ConnectionPassword {
    private ConnectionPassword() {}

    public static boolean valid(String value) {
        if (value == null || value.length() < 8 || value.length() > 128) return false;
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c < 33 || c > 126) return false;
        }
        return true;
    }
}
