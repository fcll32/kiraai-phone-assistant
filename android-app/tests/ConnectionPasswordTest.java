package top.kira.phone;

public class ConnectionPasswordTest {
    public static void main(String[] args) {
        String[] valid = {"MyKira88", "A".repeat(32), "a".repeat(128), "good!pass_9"};
        String[] invalid = {null, "", "1234567", "a".repeat(129), "hello 12", " pass123", "pass123 ", "pass123\n", "中文密码12345678", "pass123\u007f"};
        for (String value : valid) if (!ConnectionPassword.valid(value)) throw new AssertionError("Rejected valid password");
        for (String value : invalid) if (ConnectionPassword.valid(value)) throw new AssertionError("Accepted invalid password");
        System.out.println("ConnectionPassword: 14 checks passed");
    }
}
