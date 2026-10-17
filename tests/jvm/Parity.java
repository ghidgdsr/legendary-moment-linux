import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

import kotlin.Pair;
import xyz.shuncongci.leica.Cancel;
import xyz.shuncongci.leica.Fusion;
import xyz.shuncongci.leica.Gaussian;
import xyz.shuncongci.leica.Lab;
import xyz.shuncongci.leica.LegendaryMath;
import xyz.shuncongci.leica.Planes;
import xyz.shuncongci.leica.Resample;

/** Minimal file-based harness for comparing the Kotlin math with the Python port. */
public final class Parity {
    private static Planes readPlanes(String path) throws IOException {
        try (DataInputStream in = new DataInputStream(new FileInputStream(path))) {
            int w = in.readInt();
            int h = in.readInt();
            byte[] p0 = new byte[w * h];
            byte[] p1 = new byte[w * h];
            byte[] p2 = new byte[w * h];
            in.readFully(p0);
            in.readFully(p1);
            in.readFully(p2);
            return new Planes(w, h, p0, p1, p2);
        }
    }

    private static void writePlanes(String path, Planes p) throws IOException {
        try (DataOutputStream out = new DataOutputStream(new FileOutputStream(path))) {
            out.writeInt(p.getWidth());
            out.writeInt(p.getHeight());
            out.write(p.getP0());
            out.write(p.getP1());
            out.write(p.getP2());
        }
    }

    private static LegendaryMath.Frame readFrame(String path) throws IOException {
        try (DataInputStream in = new DataInputStream(new FileInputStream(path))) {
            int w = in.readInt();
            int h = in.readInt();
            int c = in.readInt();
            float[] data = new float[w * h * c];
            for (int i = 0; i < data.length; i++) {
                data[i] = in.readFloat();
            }
            return new LegendaryMath.Frame(w, h, c, data);
        }
    }

    private static void writeFrame(String path, LegendaryMath.Frame f) throws IOException {
        try (DataOutputStream out = new DataOutputStream(new FileOutputStream(path))) {
            out.writeInt(f.getW());
            out.writeInt(f.getH());
            out.writeInt(f.getChannels());
            for (float v : f.getData()) {
                out.writeFloat(v);
            }
        }
    }

    private static void writeKernel(String path, LegendaryMath.Kernel k) throws IOException {
        try (DataOutputStream out = new DataOutputStream(new FileOutputStream(path))) {
            out.writeInt(k.getHalf());
            out.writeInt(k.getW());
            for (float v : k.getData()) {
                out.writeFloat(v);
            }
        }
    }

    private static void writeNullableFloat(String path, Float value) throws IOException {
        try (DataOutputStream out = new DataOutputStream(new FileOutputStream(path))) {
            out.writeFloat(value == null ? Float.NaN : value.floatValue());
        }
    }

    public static void main(String[] args) throws Exception {
        String mode = args[0];
        switch (mode) {
            case "lab": {
                Planes p = readPlanes(args[1]);
                Lab.INSTANCE.rgbToLabInPlace(p, null);
                writePlanes(args[2], p);
                break;
            }
            case "lab_rgb": {
                Planes p = readPlanes(args[1]);
                Lab.INSTANCE.rgbToLabInPlace(p, null);
                Lab.INSTANCE.labToRgbInPlace(p, null);
                writePlanes(args[2], p);
                break;
            }
            case "fusion": {
                Planes orig = readPlanes(args[1]);
                Planes gan = readPlanes(args[2]);
                Fusion.INSTANCE.fuse(orig, gan, null);
                writePlanes(args[3], orig);
                break;
            }
            case "resample": {
                Planes p = readPlanes(args[1]);
                int w = Integer.parseInt(args[3]);
                int h = Integer.parseInt(args[4]);
                Resample.Filter filter = Resample.Filter.values()[Integer.parseInt(args[5])];
                writePlanes(args[2], Resample.INSTANCE.resize(p, w, h, filter, null));
                break;
            }
            case "gaussian": {
                LegendaryMath.Frame f = readFrame(args[1]);
                float[] data = f.getData().clone();
                Gaussian.INSTANCE.blur(data, f.getW(), f.getH(), Double.parseDouble(args[3]), null);
                writeFrame(args[2], new LegendaryMath.Frame(f.getW(), f.getH(), f.getChannels(), data));
                break;
            }
            case "kernel": {
                int radius = Integer.parseInt(args[2]);
                float aperture = Float.parseFloat(args[3]);
                writeKernel(args[1], LegendaryMath.INSTANCE.kernel$app_debug(radius, aperture));
                break;
            }
            case "frame_resize": {
                LegendaryMath.Frame f = readFrame(args[1]);
                int w = Integer.parseInt(args[3]);
                int h = Integer.parseInt(args[4]);
                boolean cubic = Boolean.parseBoolean(args[5]);
                boolean align = Boolean.parseBoolean(args[6]);
                writeFrame(args[2], LegendaryMath.INSTANCE.resize(f, w, h, cubic, align, null));
                break;
            }
            case "area": {
                LegendaryMath.Frame f = readFrame(args[1]);
                int w = Integer.parseInt(args[3]);
                int h = Integer.parseInt(args[4]);
                writeFrame(args[2], LegendaryMath.INSTANCE.area(f, w, h, new Cancel()));
                break;
            }
            case "normalize": {
                LegendaryMath.Frame f = readFrame(args[1]);
                writeFrame(args[2], LegendaryMath.INSTANCE.normalize(f));
                break;
            }
            case "focus": {
                LegendaryMath.Frame f = readFrame(args[1]);
                float x = Float.parseFloat(args[3]);
                float y = Float.parseFloat(args[4]);
                Float result = LegendaryMath.INSTANCE.focus(f, new LegendaryMath.Point(x, y));
                writeNullableFloat(args[2], result);
                break;
            }
            case "exif": {
                Planes p = readPlanes(args[1]);
                int orientation = Integer.parseInt(args[3]);
                writePlanes(args[2], p.exifTransposed(orientation));
                break;
            }
            case "split": {
                Planes p = readPlanes(args[1]);
                java.lang.reflect.Method m = LegendaryMath.class.getDeclaredMethod("split", Planes.class);
                m.setAccessible(true);
                @SuppressWarnings("unchecked")
                Pair<LegendaryMath.Frame, LegendaryMath.Frame> pair =
                        (Pair<LegendaryMath.Frame, LegendaryMath.Frame>) m.invoke(LegendaryMath.INSTANCE, p);
                writeFrame(args[2], pair.getFirst());
                writeFrame(args[3], pair.getSecond());
                break;
            }
            default:
                throw new IllegalArgumentException("unknown mode " + mode);
        }
    }
}
