import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.*;
import java.util.Arrays;
import java.util.zip.Inflater;

/** Convert only Nano's DE preview copy from RetroArch RASTATE to libretro bytes.
 * Format reference: libretro/RetroArch, tasks/task_save.c and rzip_stream.c.
 * The original CE save is never opened for writing. Unknown formats stay intact.
 */
public final class ClassicStateCompat {
    private static final int LIMIT = 64 * 1024 * 1024;

    private static long le(byte[] data, int offset, int count) throws IOException {
        if (offset < 0 || count > data.length - offset) throw new IOException("Truncated header");
        long n = 0;
        for (int i = 0; i < count; i++) n |= (data[offset + i] & 255L) << (8 * i);
        return n;
    }

    private static boolean magic(byte[] b, int offset, String text) {
        byte[] s = text.getBytes(StandardCharsets.US_ASCII);
        if (offset < 0 || s.length > b.length - offset) return false;
        for (int i = 0; i < s.length; i++) if (b[offset + i] != s[i]) return false;
        return true;
    }

    static byte[] coreState(byte[] input) throws Exception {
        byte[] data = input;
        if (magic(data, 0, "#RZIPv")) {
            if (data.length < 20 || data[6] != 1 || data[7] != '#')
                throw new IOException("Unsupported RZIP version");
            long chunk = le(data, 8, 4), size = le(data, 12, 8);
            if (chunk <= 0 || chunk > LIMIT || size <= 0 || size > LIMIT)
                throw new IOException("Invalid RZIP allocation size");
            byte[] output = new byte[(int)size];
            int position = 20, filled = 0;
            while (filled < output.length) {
                long compressed = le(data, position, 4); position += 4;
                if (compressed <= 0 || compressed > data.length - position)
                    throw new IOException("Truncated RZIP chunk");
                int expected = (int)Math.min(chunk, output.length - filled);
                Inflater inflater = new Inflater();
                try {
                    inflater.setInput(data, position, (int)compressed);
                    int done = 0;
                    while (done < expected) {
                        int n = inflater.inflate(output, filled + done, expected - done);
                        if (n == 0) throw new IOException("Incomplete RZIP deflate stream");
                        done += n;
                    }
                    if (!inflater.finished() || inflater.getRemaining() != 0)
                        throw new IOException("RZIP chunk length mismatch");
                } finally { inflater.end(); }
                position += (int)compressed; filled += expected;
            }
            if (position != data.length) throw new IOException("Trailing RZIP bytes");
            data = output;
        }
        // Raw states (including RZIP-compressed raw states) already work upstream.
        if (!magic(data, 0, "RASTATE")) return null;
        if (data.length < 8 || data[7] != 1) throw new IOException("Unsupported RASTATE version");
        int position = 8, memoryStart = -1, memoryLength = 0;
        boolean ended = false;
        while (position < data.length) {
            long length = le(data, position + 4, 4);
            long padded = (length + 7) & ~7L;
            if (padded > data.length - position - 8) throw new IOException("Truncated RASTATE block");
            if (magic(data, position, "END ")) {
                if (length != 0 || position + 8 != data.length) throw new IOException("Invalid RASTATE end");
                ended = true; break;
            }
            if (magic(data, position, "MEM ")) {
                if (memoryStart >= 0 || length == 0) throw new IOException("Invalid RASTATE memory block");
                memoryStart = position + 8; memoryLength = (int)length;
            }
            position += 8 + (int)padded;
        }
        if (!ended || memoryStart < 0) throw new IOException("Missing RASTATE memory/end");
        return Arrays.copyOfRange(data, memoryStart, memoryStart + memoryLength);
    }

    private static void normalize(Path path) throws Exception {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) return;
        long size = Files.size(path);
        if (size <= 0 || size > LIMIT) throw new IOException("State exceeds limit");
        PosixFileAttributes attrs = Files.readAttributes(path, PosixFileAttributes.class,
                LinkOption.NOFOLLOW_LINKS);
        byte[] original = Files.readAllBytes(path);
        byte[] raw = coreState(original);
        if (raw == null) return;
        Path temp = Files.createTempFile(path.getParent(), ".classic-state-", ".tmp");
        try {
            Files.write(temp, raw);
            Files.setOwner(temp, attrs.owner());
            Files.getFileAttributeView(temp, PosixFileAttributeView.class).setGroup(attrs.group());
            Files.setPosixFilePermissions(temp, attrs.permissions());
            Files.setLastModifiedTime(temp, attrs.lastModifiedTime());
            // Do not replace a save modified by another writer during decoding.
            if (!Arrays.equals(original, Files.readAllBytes(path))) throw new IOException("State changed during conversion");
            Files.move(temp, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            System.out.println("ClassicStateCompat: " + path + ": " + original.length + " -> " + raw.length);
        } finally { Files.deleteIfExists(temp); }
    }

    public static void main(String[] args) throws Exception {
        // A single fixed DE cache; never accept caller-supplied writable paths.
        Path cache = Paths.get("/data/system/nano_cache");
        String basename = null;
        for (String line : Files.readAllLines(cache.resolve("manifest"), StandardCharsets.UTF_8))
            if (line.startsWith("rom_basename=")) basename = line.substring(13);
        if (basename == null || basename.isEmpty() || basename.contains("/") || basename.contains("\n"))
            throw new IOException("Invalid cache ROM basename");
        for (String folder : new String[]{"states", "rom"}) {
            Path parent = cache.resolve(folder);
            if (!parent.toRealPath().equals(parent)) throw new IOException("Cache directory is a symlink");
            normalize(parent.resolve(basename + ".state.auto"));
        }
    }
}
