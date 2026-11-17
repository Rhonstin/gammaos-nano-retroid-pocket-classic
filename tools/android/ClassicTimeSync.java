import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.security.SecureRandom;

/** One-shot SNTP client for Nano's minimal boot, which omits Android time services. */
public final class ClassicTimeSync {
    private static final long NTP_EPOCH = 2208988800L;

    private static long timestamp(byte[] packet, int offset) {
        long seconds = 0, fraction = 0;
        for (int i = 0; i < 4; i++) {
            seconds = (seconds << 8) | (packet[offset + i] & 255L);
            fraction = (fraction << 8) | (packet[offset + 4 + i] & 255L);
        }
        return (seconds - NTP_EPOCH) * 1000L + ((fraction * 1000L) >>> 32);
    }

    private static void sync(String host) throws Exception {
        byte[] request = new byte[48];
        request[0] = 0x23; // NTP v4, client mode.
        byte[] nonce = new byte[8];
        new SecureRandom().nextBytes(nonce);
        System.arraycopy(nonce, 0, request, 40, nonce.length);
        try (DatagramSocket socket = new DatagramSocket()) {
            socket.setSoTimeout(4000);
            socket.connect(InetAddress.getByName(host), 123);
            long sent = System.nanoTime();
            socket.send(new DatagramPacket(request, request.length));
            byte[] response = new byte[512];
            DatagramPacket reply = new DatagramPacket(response, response.length);
            socket.receive(reply);
            long elapsed = (System.nanoTime() - sent) / 1000000L;
            int header = response[0] & 255;
            int version = (header >>> 3) & 7;
            if (reply.getLength() < 48 || (header >>> 6) == 3 || (header & 7) != 4
                    || version < 3 || version > 4 || (response[1] & 255) < 1
                    || (response[1] & 255) > 15 || elapsed > 4000) {
                throw new IllegalStateException("Invalid SNTP server response");
            }
            for (int i = 0; i < nonce.length; i++) {
                if (response[24 + i] != nonce[i]) {
                    throw new IllegalStateException("SNTP originate timestamp mismatch");
                }
            }
            long received = timestamp(response, 32);
            long transmitted = timestamp(response, 40);
            if (transmitted < 1735689600000L || transmitted >= 2082758400000L
                    || received > transmitted || transmitted - received > 2000) {
                throw new IllegalStateException("Implausible SNTP timestamps");
            }
            long now = transmitted + Math.max(0, elapsed - (transmitted - received)) / 2;
            if (Math.abs(now - System.currentTimeMillis()) > 1000) {
                Object success = Class.forName("android.os.SystemClock")
                    .getMethod("setCurrentTimeMillis", long.class).invoke(null, now);
                if (!Boolean.TRUE.equals(success)) {
                    throw new IllegalStateException("System clock update failed");
                }
            }
            System.out.println("SNTP synchronized using " + host + ", RTT " + elapsed + " ms");
        }
    }

    public static void main(String[] args) {
        for (String host : new String[]{"time.cloudflare.com", "time.android.com", "pool.ntp.org"}) {
            try {
                sync(host);
                System.exit(0);
            } catch (Exception error) {
                System.err.println(host + ": " + error.getClass().getSimpleName() + ": " + error.getMessage());
            }
        }
        System.exit(1);
    }
}
