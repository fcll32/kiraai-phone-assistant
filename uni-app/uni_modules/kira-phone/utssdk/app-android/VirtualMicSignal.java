package top.kira.phone;

/** A bounded two-chirp signature. Detection does not accept ordinary microphone energy as proof. */
public final class VirtualMicSignal {
    public static final int RATE = 48000;
    public static final int LEAD = RATE / 4;
    private static final int LENGTH = RATE * 120 / 1000;
    private static final int SEPARATION = RATE * 270 / 1000;
    private static final int STEP = 8;
    private VirtualMicSignal() { }

    public static short[] samples() {
        short[] pcm = new short[RATE * 2];
        chirp(pcm, LEAD, 500, 2200);
        chirp(pcm, LEAD + SEPARATION, 1000, 400);
        return pcm;
    }

    private static void chirp(short[] pcm, int start, double low, double high) {
        for (int i = 0; i < LENGTH; i++) {
            double time = (double) i / RATE;
            double fade = Math.min(1, Math.min(i, LENGTH - 1 - i) / (RATE * .005));
            double phase = 2 * Math.PI * (low * time + .5 * (high - low) * time * time / ((double) LENGTH / RATE));
            pcm[start + i] = (short) (6000 * fade * Math.sin(phase));
        }
    }

    public static final class Result {
        public final boolean detected;
        public final double score;
        public final int offsetSamples;
        Result(boolean found, double confidence, int offset) {
            detected = found; score = confidence; offsetSamples = offset;
        }
    }

    public static Result detect(short[] pcm, int count) {
        count = Math.min(count, pcm.length);
        if (count < SEPARATION + LENGTH) return new Result(false, 0, -1);
        short[] expected = samples();
        int width = LENGTH / STEP, gap = SEPARATION / STEP, size = count / STEP;
        double[] input = new double[size], first = new double[width], second = new double[width];
        double[] energy = new double[size + 1];
        double firstEnergy = 0, secondEnergy = 0;
        for (int i = 0; i < size; i++) {
            input[i] = pcm[i * STEP];
            energy[i + 1] = energy[i] + input[i] * input[i];
        }
        for (int i = 0; i < width; i++) {
            first[i] = expected[LEAD + i * STEP];
            second[i] = expected[LEAD + SEPARATION + i * STEP];
            firstEnergy += first[i] * first[i]; secondEnergy += second[i] * second[i];
        }
        double best = 0;
        int offset = -1;
        for (int start = 0; start + gap + width <= size; start++) {
            double e1 = energy[start + width] - energy[start];
            double e2 = energy[start + gap + width] - energy[start + gap];
            if (e1 / width < 10000 || e2 / width < 10000) continue;
            double dot1 = 0;
            for (int i = 0; i < width; i++) dot1 += first[i] * input[start + i];
            double score1 = Math.abs(dot1) / Math.sqrt(e1 * firstEnergy);
            if (score1 < .65 || score1 <= best) continue;
            double dot2 = 0;
            for (int i = 0; i < width; i++) dot2 += second[i] * input[start + gap + i];
            double score = Math.min(score1, Math.abs(dot2) / Math.sqrt(e2 * secondEnergy));
            if (score > best) { best = score; offset = start * STEP; }
        }
        return new Result(best >= .72, best, offset);
    }
}
