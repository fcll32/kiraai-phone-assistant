package top.kira.phone;

/** Energy VAD for fixed 20 ms PCM16 frames. It never retains microphone samples. */
public final class VoiceVad {
    public static final int FRAME_SAMPLES = 320;
    public static final int START = 1, CONTINUE = 2, END = 3, QUIET = 0;
    private int voiced, silent, duration;
    private boolean speaking;
    private double noise = 100;
    private double level;

    public int accept(short[] pcm) {
        if (pcm.length != FRAME_SAMPLES) throw new IllegalArgumentException("A VAD frame must be 20 ms");
        double sum = 0;
        for (short sample : pcm) sum += (double) sample * sample;
        double rms = Math.sqrt(sum / pcm.length);
        level = Math.min(1, rms / 8000.0);
        boolean speech = rms > Math.max(350, Math.min(1800, noise * 3));
        if (!speaking) {
            if (!speech) noise = noise * 0.97 + rms * 0.03;
            voiced = speech ? voiced + 1 : 0;
            if (voiced < 3) return QUIET;
            speaking = true;
            duration = 3;
            silent = 0;
            return START;
        }
        duration++;
        silent = speech ? 0 : silent + 1;
        if ((silent >= 35 && duration >= 20) || duration >= 1450) {
            reset();
            return END;
        }
        return CONTINUE;
    }

    public double level() { return level; }
    public void reset() { voiced = 0; silent = 0; duration = 0; speaking = false; level = 0; }
}
