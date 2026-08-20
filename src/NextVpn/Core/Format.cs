using System.Globalization;

namespace NextVpn.Core;

/// <summary>
/// Every number the interface shows a user. Kept away from the view model so the
/// rounding and unit rules can be tested without a UI thread.
///
/// Formatting is invariant rather than locale-driven, so a value never comes out
/// as "1,5 MB" beside English labels on a machine with a comma decimal separator.
/// </summary>
public static class Format
{
    private static readonly string[] ByteUnits = ["B", "KB", "MB", "GB", "TB"];
    private static readonly string[] RateUnits = ["B/s", "KB/s", "MB/s", "GB/s"];

    private static readonly CultureInfo Fixed = CultureInfo.InvariantCulture;

    /// <summary>Placeholder for a value that does not exist yet. One em dash, everywhere.</summary>
    public const string Empty = "—";

    public static string Bytes(long bytes)
    {
        if (bytes <= 0) return "0 B";

        double v = bytes;
        var i = 0;
        while (v >= 1024 && i < ByteUnits.Length - 1) { v /= 1024; i++; }

        // Bytes are whole things; everything above them reads better with one decimal.
        return i == 0
            ? ((long)v).ToString(Fixed) + " " + ByteUnits[i]
            : v.ToString("0.#", Fixed) + " " + ByteUnits[i];
    }

    public static string Rate(double bytesPerSecond)
    {
        if (double.IsNaN(bytesPerSecond) || bytesPerSecond < 1) return "0 B/s";

        var v = bytesPerSecond;
        var i = 0;
        while (v >= 1024 && i < RateUnits.Length - 1) { v /= 1024; i++; }

        return i == 0
            ? ((long)v).ToString(Fixed) + " " + RateUnits[i]
            : v.ToString("0.#", Fixed) + " " + RateUnits[i];
    }

    /// <summary>
    /// Session length. Minutes and seconds until the first hour, then hours as well,
    /// so the field only ever changes width once in a session.
    /// </summary>
    public static string Duration(TimeSpan t)
    {
        if (t <= TimeSpan.Zero) return Empty;

        return t.TotalHours >= 1
            ? string.Format(Fixed, "{0}:{1:00}:{2:00}", (int)t.TotalHours, t.Minutes, t.Seconds)
            : string.Format(Fixed, "{0:00}:{1:00}", t.Minutes, t.Seconds);
    }

    /// <summary>"Germany (DE)", or the placeholder when the engine has not said yet.</summary>
    public static string Country(string? code) =>
        code is { Length: > 0 } c ? $"{Regions.NameOf(c)} ({c.ToUpperInvariant()})" : Empty;

    /// <summary>Local listener ports, or the placeholder before either one is open.</summary>
    public static string Ports(int httpPort, int socksPort)
    {
        if (httpPort <= 0 && socksPort <= 0) return Empty;
        if (httpPort <= 0) return $"SOCKS {socksPort}";
        if (socksPort <= 0) return $"HTTP {httpPort}";
        return $"HTTP {httpPort} · SOCKS {socksPort}";
    }
}
