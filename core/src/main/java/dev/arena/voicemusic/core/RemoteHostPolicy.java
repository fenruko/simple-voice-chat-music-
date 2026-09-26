package dev.arena.voicemusic.core;

import java.net.Inet4Address;
import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;

/** Blocks obvious SSRF destinations before an arbitrary media URL reaches a source extractor. */
public final class RemoteHostPolicy {
    private RemoteHostPolicy() { }

    public static boolean isTrustedMediaProviderUrl(String rawUrl) {
        try {
            String host = URI.create(rawUrl).getHost();
            if (host == null) return false;
            host = host.toLowerCase(java.util.Locale.ROOT);
            return host.equals("youtu.be") || host.equals("youtube.com") || host.endsWith(".youtube.com")
                    || host.equals("soundcloud.com") || host.endsWith(".soundcloud.com");
        } catch (IllegalArgumentException ex) { return false; }
    }

    public static void requirePublicHttpTarget(String rawUrl) {
        final URI uri;
        try { uri = URI.create(rawUrl); }
        catch (IllegalArgumentException ex) { throw new IllegalArgumentException("Invalid media URL."); }
        String host = uri.getHost();
        if (host == null || host.isBlank()) throw new IllegalArgumentException("Media URL must include a public host.");
        if (uri.getPort() != -1 && uri.getPort() != 80 && uri.getPort() != 443) {
            throw new IllegalArgumentException("Custom ports are not allowed for media URLs.");
        }
        if (host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".internal") || host.equalsIgnoreCase("localhost")) {
            throw new IllegalArgumentException("Private network media URLs are not allowed.");
        }
        try {
            for (InetAddress address : InetAddress.getAllByName(host)) {
                if (!isPublic(address)) throw new IllegalArgumentException("Private or reserved network addresses are not allowed.");
            }
        } catch (UnknownHostException ex) {
            throw new IllegalArgumentException("The media host could not be resolved.");
        }
    }

    public static boolean isPublic(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) return false;
        byte[] b = address.getAddress();
        if (address instanceof Inet6Address && isIpv4Mapped(b)) {
            try { return isPublic(InetAddress.getByAddress(new byte[]{b[12], b[13], b[14], b[15]})); }
            catch (UnknownHostException impossible) { return false; }
        }
        if (address instanceof Inet4Address) {
            int a = b[0] & 255, c = b[1] & 255;
            if (a == 0 || a == 10 || a == 127 || a >= 224) return false;
            if (a == 100 && c >= 64 && c <= 127) return false; // carrier-grade NAT
            if (a == 169 && c == 254) return false;
            if (a == 172 && c >= 16 && c <= 31) return false;
            if (a == 192 && (c == 0 || c == 168)) return false;
            if (a == 198 && (c == 18 || c == 19 || c == 51)) return false;
            if (a == 203 && c == 0) return false;
        } else if (address instanceof Inet6Address) {
            int first = b[0] & 255;
            if ((first & 0xfe) == 0xfc) return false; // unique-local fc00::/7
            if (first == 0x20 && (b[1] & 255) == 0x01 && (b[2] & 255) == 0x0d && (b[3] & 255) == 0xb8) return false; // documentation prefix
        }
        return true;
    }

    private static boolean isIpv4Mapped(byte[] b) {
        if (b.length != 16 || (b[10] & 255) != 255 || (b[11] & 255) != 255) return false;
        for (int i = 0; i < 10; i++) if (b[i] != 0) return false;
        return true;
    }
}
