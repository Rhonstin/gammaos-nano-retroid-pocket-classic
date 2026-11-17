import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.charset.StandardCharsets;

/** Invoke the stock RPSettings PServerBinder command protocol from app_process. */
public final class ClassicRoot {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Expected command-file path");
        String command = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
        Class<?> sm = Class.forName("android.os.ServiceManager");
        Class<?> binderClass = Class.forName("android.os.IBinder");
        Class<?> parcelClass = Class.forName("android.os.Parcel");
        Object binder = sm.getMethod("getService", String.class).invoke(null, "PServerBinder");
        if (binder == null) throw new IllegalStateException("PServerBinder unavailable");
        Object request = parcelClass.getMethod("obtain").invoke(null);
        Object reply = parcelClass.getMethod("obtain").invoke(null);
        Method recycle = parcelClass.getMethod("recycle");
        try {
            parcelClass.getMethod("writeStringArray", String[].class)
                .invoke(request, (Object) new String[] {command, "1"});
            Object accepted = binderClass.getMethod("transact", int.class, parcelClass, parcelClass, int.class)
                .invoke(binder, 0, request, reply, 0);
            if (!Boolean.TRUE.equals(accepted)) throw new IllegalStateException("Transaction rejected");
            byte[] output = (byte[]) parcelClass.getMethod("createByteArray").invoke(reply);
            if (output == null) throw new IllegalStateException("No command reply");
            System.out.write(output);
            System.out.flush();
        } finally {
            recycle.invoke(request);
            recycle.invoke(reply);
        }
    }
}
