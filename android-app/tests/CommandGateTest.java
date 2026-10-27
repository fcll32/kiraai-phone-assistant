package top.kira.phone;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

public class CommandGateTest {
    private static void rejected(CommandGate gate) {
        try { gate.check(); throw new AssertionError("Cancelled command was allowed"); }
        catch (IllegalStateException expected) { }
    }
    public static void main(String[] args) {
        AtomicLong clock = new AtomicLong(1000);
        AtomicBoolean connected = new AtomicBoolean(true);
        CommandGate gate = new CommandGate(connected::get, clock::get, 500);
        gate.check();
        connected.set(false); rejected(gate);
        connected.set(true); clock.set(1500); rejected(gate);
        clock.set(1000); Thread.currentThread().interrupt(); rejected(gate); Thread.interrupted();
        try { new CommandGate(connected::get, clock::get, 0); throw new AssertionError("Invalid TTL accepted"); }
        catch (IllegalArgumentException expected) { }
        System.out.println("CommandGate: 5 checks passed");
    }
}
