package top.kira.phone;

import java.util.Random;

public final class VirtualMicSignalTest {
    private static int checks;
    private static void check(boolean value, String label) {
        checks++;
        if (!value) throw new AssertionError(label);
    }
    public static void main(String[] args) {
        short[] signal = VirtualMicSignal.samples();
        VirtualMicSignal.Result clean = VirtualMicSignal.detect(signal, signal.length);
        check(clean.detected, "complete injected signal");
        check(Math.abs(clean.offsetSamples - VirtualMicSignal.LEAD) < 16, "clean timing");
        short[] delayed = new short[VirtualMicSignal.RATE * 3];
        int delay = 7824;
        Random noise = new Random(138);
        for (int i = 0; i < delayed.length; i++) delayed[i] = (short) (noise.nextGaussian() * 250);
        for (int i = 0; i < signal.length; i++) delayed[i + delay] += (short) (-signal[i] * .55);
        VirtualMicSignal.Result noisy = VirtualMicSignal.detect(delayed, delayed.length);
        check(noisy.detected, "gain, inverted polarity and background noise");
        check(Math.abs(noisy.offsetSamples - VirtualMicSignal.LEAD - delay) < 16, "delayed timing");
        check(!VirtualMicSignal.detect(new short[signal.length], signal.length).detected, "silence cannot pass");
        short[] other = new short[signal.length];
        for (int i = 0; i < other.length; i++) other[i] = (short) (6000 * Math.sin(2 * Math.PI * 1000 * i / VirtualMicSignal.RATE));
        check(!VirtualMicSignal.detect(other, other.length).detected, "ordinary tone cannot pass");
        for (int i = 0; i < other.length; i++) other[i] = (short) (noise.nextGaussian() * 3000);
        check(!VirtualMicSignal.detect(other, other.length).detected, "random microphone noise cannot pass");
        short[] partial = signal.clone();
        java.util.Arrays.fill(partial, VirtualMicSignal.RATE / 2, partial.length, (short) 0);
        check(!VirtualMicSignal.detect(partial, partial.length).detected, "first chirp alone cannot pass");
        check(!VirtualMicSignal.detect(signal, 1000).detected, "short capture cannot pass");
        check(!VirtualMicSignal.detect(signal, VirtualMicSignal.RATE / 2).detected, "incomplete supplied length cannot pass");
        System.out.println("VirtualMicSignal: " + checks + " checks passed");
    }
}
