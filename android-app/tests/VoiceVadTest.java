package top.kira.phone;

import java.util.Arrays;

public final class VoiceVadTest {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("Check " + checks); }
    public static void main(String[] args) {
        VoiceVad vad = new VoiceVad();
        short[] quiet = new short[320], speech = new short[320];
        Arrays.fill(speech, (short) 2400);
        for (int i = 0; i < 100; i++) check(vad.accept(quiet) == VoiceVad.QUIET);
        check(vad.accept(speech) == VoiceVad.QUIET);
        check(vad.accept(quiet) == VoiceVad.QUIET); // one transient must not start a turn
        check(vad.accept(speech) == VoiceVad.QUIET);
        check(vad.accept(speech) == VoiceVad.QUIET);
        check(vad.accept(speech) == VoiceVad.START);
        for (int i = 0; i < 34; i++) check(vad.accept(quiet) == VoiceVad.CONTINUE);
        check(vad.accept(quiet) == VoiceVad.END);
        check(vad.accept(quiet) == VoiceVad.QUIET);
        for (int i = 0; i < 3; i++) vad.accept(speech);
        int duration = 3;
        while (vad.accept(speech) != VoiceVad.END) { if (++duration > 1500) throw new AssertionError("unbounded speech"); }
        check(duration < 1500);
        vad.accept(speech); vad.reset();
        check(vad.accept(speech) == VoiceVad.QUIET);
        check(vad.level() > 0 && vad.level() <= 1);
        boolean rejected = false;
        try { vad.accept(new short[1]); } catch (IllegalArgumentException expected) { rejected = true; }
        check(rejected);
        System.out.println("VoiceVad: " + checks + " checks passed");
    }
}
