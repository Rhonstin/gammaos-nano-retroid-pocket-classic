import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;

/**
 * Merge the Classic port's extra game systems into Nano's /data/system/nano_systems.json.
 *
 * Nano 1.4.1 owns that file: it seeds the built-in table on first start, rewrites it from
 * the Game Systems editor and reloads it when another writer changes its mtime. This
 * helper therefore only edits an existing, parseable file and keeps every unknown field.
 *
 * Rules, recorded in a state file so a user's own edits always win:
 *  - a system is added once, when its emulator package or libretro core is installed;
 *    deleting it in Nano is final;
 *  - a system this helper added is refreshed to a newer definition only while it still
 *    equals what the helper last wrote;
 *  - a migration changes one field of a built-in system once, only from its stock value
 *    and only when its precondition files exist.
 *
 * usage: ClassicSystems DEFINITIONS NANO_SYSTEMS STATE PACKAGES_LIST CORE_DIR
 * exit:  0 written or unchanged, 3 Nano has not created its config yet, 1 error
 */
public final class ClassicSystems {
    // ---- minimal JSON (RFC 8259 subset used by Nano and by our definitions) ----
    static final class Parser {
        final String s; int i;
        Parser(String s) { this.s = s; }
        Object parse() throws IOException { Object v = value(); ws(); if (i != s.length()) throw err("trailing data"); return v; }
        IOException err(String m) { return new IOException("JSON " + m + " at " + i); }
        void ws() { while (i < s.length() && " \t\r\n".indexOf(s.charAt(i)) >= 0) i++; }
        Object value() throws IOException {
            ws();
            if (i >= s.length()) throw err("unexpected end");
            char c = s.charAt(i);
            if (c == '{') {
                i++; Map<String, Object> m = new LinkedHashMap<>(); ws();
                if (peek('}')) { i++; return m; }
                while (true) {
                    ws(); if (!peek('"')) throw err("object key");
                    String k = string(); ws(); expect(':'); m.put(k, value()); ws();
                    if (peek(',')) { i++; continue; }
                    expect('}'); return m;
                }
            }
            if (c == '[') {
                i++; List<Object> a = new ArrayList<>(); ws();
                if (peek(']')) { i++; return a; }
                while (true) { a.add(value()); ws(); if (peek(',')) { i++; continue; } expect(']'); return a; }
            }
            if (c == '"') return string();
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            if (s.startsWith("null", i)) { i += 4; return null; }
            int start = i;
            while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
            if (start == i) throw err("value");
            String n = s.substring(start, i);
            try {
                if (n.indexOf('.') < 0 && n.indexOf('e') < 0 && n.indexOf('E') < 0) return Long.parseLong(n);
                return Double.parseDouble(n);
            } catch (NumberFormatException e) { throw err("number"); }
        }
        boolean peek(char c) { return i < s.length() && s.charAt(i) == c; }
        void expect(char c) throws IOException { if (!peek(c)) throw err("expected '" + c + "'"); i++; }
        String string() throws IOException {
            expect('"'); StringBuilder b = new StringBuilder();
            while (true) {
                if (i >= s.length()) throw err("unterminated string");
                char c = s.charAt(i++);
                if (c == '"') return b.toString();
                if (c != '\\') { b.append(c); continue; }
                if (i >= s.length()) throw err("escape");
                char e = s.charAt(i++);
                switch (e) {
                    case '"': case '\\': case '/': b.append(e); break;
                    case 'b': b.append('\b'); break; case 'f': b.append('\f'); break;
                    case 'n': b.append('\n'); break; case 'r': b.append('\r'); break;
                    case 't': b.append('\t'); break;
                    case 'u':
                        if (i + 4 > s.length()) throw err("unicode escape");
                        b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                    default: throw err("escape");
                }
            }
        }
    }

    static void write(StringBuilder b, Object v, int depth) {
        String pad = "  ";
        if (v == null) b.append("null");
        else if (v instanceof String) quote(b, (String) v);
        else if (v instanceof Boolean || v instanceof Long || v instanceof Integer) b.append(v);
        else if (v instanceof Double) {
            double d = (Double) v;
            if (d == Math.rint(d) && Math.abs(d) < 1e15) b.append((long) d); else b.append(d);
        } else if (v instanceof Map) {
            Map<?, ?> m = (Map<?, ?>) v;
            if (m.isEmpty()) { b.append("{}"); return; }
            b.append("{\n"); int n = 0;
            for (Map.Entry<?, ?> e : m.entrySet()) {
                for (int k = 0; k <= depth; k++) b.append(pad);
                quote(b, (String) e.getKey()); b.append(": "); write(b, e.getValue(), depth + 1);
                if (++n < m.size()) b.append(','); b.append('\n');
            }
            for (int k = 0; k < depth; k++) b.append(pad); b.append('}');
        } else if (v instanceof List) {
            List<?> a = (List<?>) v;
            if (a.isEmpty()) { b.append("[]"); return; }
            b.append("[\n");
            for (int n = 0; n < a.size(); n++) {
                for (int k = 0; k <= depth; k++) b.append(pad);
                write(b, a.get(n), depth + 1); if (n + 1 < a.size()) b.append(','); b.append('\n');
            }
            for (int k = 0; k < depth; k++) b.append(pad); b.append(']');
        } else throw new IllegalArgumentException("unsupported JSON value " + v.getClass());
    }

    static void quote(StringBuilder b, String s) {
        b.append('"');
        for (int k = 0; k < s.length(); k++) {
            char c = s.charAt(k);
            switch (c) {
                case '"': b.append("\\\""); break; case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break; case '\r': b.append("\\r"); break; case '\t': b.append("\\t"); break;
                default: if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
            }
        }
        b.append('"');
    }

    static String json(Object v) { StringBuilder b = new StringBuilder(); write(b, v, 0); return b.append('\n').toString(); }

    @SuppressWarnings("unchecked") static Map<String, Object> obj(Object v) throws IOException {
        if (!(v instanceof Map)) throw new IOException("expected object"); return (Map<String, Object>) v;
    }
    @SuppressWarnings("unchecked") static List<Object> arr(Object v) throws IOException {
        if (!(v instanceof List)) throw new IOException("expected array"); return (List<Object>) v;
    }
    static String str(Map<String, Object> m, String k) { Object v = m.get(k); return v instanceof String ? (String) v : ""; }

    static Object read(Path p) throws IOException { return new Parser(new String(Files.readAllBytes(p), StandardCharsets.UTF_8)).parse(); }

    static String digest(Object v) throws Exception {
        byte[] h = MessageDigest.getInstance("SHA-256").digest(json(v).getBytes(StandardCharsets.UTF_8));
        StringBuilder b = new StringBuilder(); for (byte x : h) b.append(String.format("%02x", x)); return b.toString();
    }

    static void atomicWrite(Path target, String text, boolean world) throws IOException {
        Path tmp = target.resolveSibling(target.getFileName() + ".classic.tmp");
        Files.write(tmp, text.getBytes(StandardCharsets.UTF_8));
        Files.setPosixFilePermissions(tmp, PosixFilePermissions.fromString(world ? "rw-r--r--" : "rw-------"));
        Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    }

    static boolean anyExists(Object list) throws IOException {
        if (list == null) return true;
        for (Object p : arr(list)) if (p instanceof String && Files.isRegularFile(Paths.get((String) p))) return true;
        return false;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 5) { System.err.println("usage: ClassicSystems DEFS NANO STATE PACKAGES CORES"); System.exit(1); }
        Path defsPath = Paths.get(args[0]), nanoPath = Paths.get(args[1]), statePath = Paths.get(args[2]);
        Path cores = Paths.get(args[4]);
        if (!Files.isRegularFile(nanoPath)) { System.out.println("nano_systems.json not created yet"); System.exit(3); }
        Map<String, Object> defs = obj(read(defsPath));
        Map<String, Object> nano = obj(read(nanoPath));
        List<Object> systems = arr(nano.get("systems"));
        if (systems.isEmpty()) throw new IOException("Nano systems list is empty");
        Map<String, Object> state = Files.isRegularFile(statePath) ? obj(read(statePath)) : new LinkedHashMap<String, Object>();
        Map<String, Object> written = state.containsKey("written") ? obj(state.get("written")) : new LinkedHashMap<String, Object>();
        Map<String, Object> migrated = state.containsKey("migrated") ? obj(state.get("migrated")) : new LinkedHashMap<String, Object>();
        state.put("written", written); state.put("migrated", migrated);

        Set<String> packages = new HashSet<>();
        for (String line : Files.readAllLines(Paths.get(args[3]), StandardCharsets.UTF_8)) {
            int sp = line.indexOf(' '); if (sp > 0) packages.add(line.substring(0, sp));
        }
        Map<String, Map<String, Object>> byId = new LinkedHashMap<>();
        long maxOrder = 0;
        for (Object o : systems) {
            Map<String, Object> s = obj(o); byId.put(str(s, "id"), s);
            Object order = s.get("order");
            if (order instanceof Number) maxOrder = Math.max(maxOrder, ((Number) order).longValue());
        }
        boolean changed = false;

        for (Object o : arr(defs.get("systems"))) {
            Map<String, Object> def = new LinkedHashMap<>(obj(o));
            String id = str(def, "id");
            String pkg = (String) def.remove("requiresPackage");
            String core = (String) def.remove("requiresCore");
            boolean available = (pkg == null || packages.contains(pkg))
                    && (core == null || Files.isRegularFile(cores.resolve(core)));
            Map<String, Object> current = byId.get(id);
            if (current == null) {
                if (written.containsKey(id)) continue;          // removed by the user: final
                if (!available) continue;                       // retry once the emulator exists
                def.put("order", ++maxOrder);
                systems.add(def); byId.put(id, def);
                written.put(id, digest(def)); changed = true;
                System.out.println("added " + id);
            } else if (written.containsKey(id)) {
                Map<String, Object> refreshed = new LinkedHashMap<>(def);
                refreshed.put("order", current.get("order"));
                refreshed.put("enabled", current.get("enabled"));
                if (digest(current).equals(written.get(id)) && !digest(refreshed).equals(written.get(id))) {
                    systems.set(systems.indexOf(current), refreshed); byId.put(id, refreshed);
                    written.put(id, digest(refreshed)); changed = true;
                    System.out.println("refreshed " + id);
                }
            }
        }

        Object migrations = defs.get("migrations");
        if (migrations != null) for (Object o : arr(migrations)) {
            Map<String, Object> m = obj(o);
            String key = str(m, "id") + "." + str(m, "field") + "=" + str(m, "to");
            if (migrated.containsKey(key)) continue;
            Map<String, Object> s = byId.get(str(m, "id"));
            if (s == null || !anyExists(m.get("whenAnyFile"))) continue;
            if (m.containsKey("whenCore") && !Files.isRegularFile(cores.resolve(str(m, "whenCore")))) continue;
            Object value = s.get(str(m, "field"));
            if (str(m, "from").equals(value)) {
                s.put(str(m, "field"), str(m, "to")); changed = true;
                System.out.println("migrated " + key);
            }
            migrated.put(key, Boolean.TRUE);                    // decided once, also when the user changed it
        }

        if (changed) atomicWrite(nanoPath, json(nano), true);
        atomicWrite(statePath, json(state), false);
        System.out.println(changed ? "nano_systems.json updated" : "nano_systems.json unchanged");
    }
}
