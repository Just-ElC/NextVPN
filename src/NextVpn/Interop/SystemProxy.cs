using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Win32;
using NextVpn.Core;

namespace NextVpn.Interop;

/// <summary>
/// Points WinINet at the tunnel's local HTTP proxy and puts the previous
/// settings back afterwards.
///
/// The previous settings are also written to disk before being changed, so that
/// a crash or a power cut cannot leave the machine pointing at a dead local
/// port with no way back. <see cref="RecoverIfStale"/> repairs that on startup.
/// </summary>
public static class SystemProxy
{
    private const string InternetSettingsKey =
        @"Software\Microsoft\Windows\CurrentVersion\Internet Settings";

    private static string BackupPath => Path.Combine(Paths.DataDirectory, "proxy-backup.json");

    private sealed record ProxyBackup(
        bool Enabled,
        string Server,
        string Bypass,
        string AutoConfigUrl,
        string AppliedByUs);

    // ------------------------------------------------------------ public API

    /// <summary>
    /// Builds the per-protocol proxy string. Declaring http, https and socks
    /// separately lets SOCKS-aware applications use the SOCKS listener directly
    /// instead of forcing everything through the HTTP CONNECT proxy.
    /// </summary>
    public static string BuildProxyString(int httpPort, int socksPort)
    {
        var parts = new List<string>(3);
        if (httpPort > 0)
        {
            parts.Add($"http=127.0.0.1:{httpPort}");
            parts.Add($"https=127.0.0.1:{httpPort}");
        }
        if (socksPort > 0) parts.Add($"socks=127.0.0.1:{socksPort}");
        return string.Join(";", parts);
    }

    public static bool Apply(int httpPort, int socksPort, string bypassList)
    {
        if (httpPort <= 0) return false;

        var target = BuildProxyString(httpPort, socksPort);

        // Only capture a backup if we are not already the active proxy, so that
        // reconnecting twice cannot overwrite the user's real settings.
        if (ReadBackup() is null)
            WriteBackup(CaptureCurrent(target));

        var ok = SetWinInetProxy(enabled: true, server: target, bypass: bypassList, autoConfigUrl: null);
        return ok;
    }

    public static void Revert()
    {
        var backup = ReadBackup();
        if (backup is null) return;

        SetWinInetProxy(
            enabled: backup.Enabled,
            server: backup.Server,
            bypass: backup.Bypass,
            autoConfigUrl: string.IsNullOrEmpty(backup.AutoConfigUrl) ? null : backup.AutoConfigUrl);

        TryDelete(BackupPath);
    }

    /// <summary>
    /// Called at startup. If a previous run left the system proxy pointing at one
    /// of our local ports, restore the saved settings so the network works again.
    /// </summary>
    public static void RecoverIfStale()
    {
        var backup = ReadBackup();
        if (backup is null) return;

        var current = CurrentProxyServer();
        var weAreStillSet = !string.IsNullOrEmpty(current) &&
                            current.Equals(backup.AppliedByUs, StringComparison.OrdinalIgnoreCase);

        if (weAreStillSet)
            Revert();
        else
            TryDelete(BackupPath);
    }

    // ------------------------------------------------------------- registry

    private static ProxyBackup CaptureCurrent(string appliedByUs)
    {
        using var key = Registry.CurrentUser.OpenSubKey(InternetSettingsKey, writable: false);
        var enabled = (key?.GetValue("ProxyEnable") as int?) == 1;
        var server = key?.GetValue("ProxyServer") as string ?? "";
        var bypass = key?.GetValue("ProxyOverride") as string ?? "";
        var pac = key?.GetValue("AutoConfigURL") as string ?? "";
        return new ProxyBackup(enabled, server, bypass, pac, appliedByUs);
    }

    private static string CurrentProxyServer()
    {
        using var key = Registry.CurrentUser.OpenSubKey(InternetSettingsKey, writable: false);
        if ((key?.GetValue("ProxyEnable") as int?) != 1) return "";
        return key?.GetValue("ProxyServer") as string ?? "";
    }

    private static void WriteBackup(ProxyBackup backup)
    {
        try
        {
            Directory.CreateDirectory(Paths.DataDirectory);
            File.WriteAllText(BackupPath, JsonSerializer.Serialize(backup));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }

    private static ProxyBackup? ReadBackup()
    {
        try
        {
            if (!File.Exists(BackupPath)) return null;
            return JsonSerializer.Deserialize<ProxyBackup>(File.ReadAllText(BackupPath));
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
    }

    // --------------------------------------------------------------- WinINet

    private static bool SetWinInetProxy(bool enabled, string? server, string? bypass, string? autoConfigUrl)
    {
        // The registry is written as well as the API being called: some
        // applications read these values directly rather than asking WinINet.
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(InternetSettingsKey, writable: true);
            if (key is not null)
            {
                key.SetValue("ProxyEnable", enabled ? 1 : 0, RegistryValueKind.DWord);

                if (enabled && !string.IsNullOrEmpty(server))
                {
                    key.SetValue("ProxyServer", server, RegistryValueKind.String);
                    key.SetValue("ProxyOverride", bypass ?? "", RegistryValueKind.String);
                }
                else if (!enabled)
                {
                    if (string.IsNullOrEmpty(server)) key.DeleteValue("ProxyServer", throwOnMissingValue: false);
                    else key.SetValue("ProxyServer", server, RegistryValueKind.String);
                }

                if (string.IsNullOrEmpty(autoConfigUrl))
                    key.DeleteValue("AutoConfigURL", throwOnMissingValue: false);
                else
                    key.SetValue("AutoConfigURL", autoConfigUrl, RegistryValueKind.String);
            }
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or System.Security.SecurityException or IOException)
        {
            return false;
        }

        return PushToWinInet(enabled, server, bypass, autoConfigUrl);
    }

    private static bool PushToWinInet(bool enabled, string? server, string? bypass, string? autoConfigUrl)
    {
        var options = new List<(int Option, int? IntValue, string? StringValue)>();

        var flags = PROXY_TYPE_DIRECT;
        if (enabled && !string.IsNullOrEmpty(server)) flags |= PROXY_TYPE_PROXY;
        if (!string.IsNullOrEmpty(autoConfigUrl)) flags |= PROXY_TYPE_AUTO_PROXY_URL;

        options.Add((INTERNET_PER_CONN_FLAGS, flags, null));
        options.Add((INTERNET_PER_CONN_PROXY_SERVER, null, server ?? ""));
        options.Add((INTERNET_PER_CONN_PROXY_BYPASS, null, bypass ?? ""));
        options.Add((INTERNET_PER_CONN_AUTOCONFIG_URL, null, autoConfigUrl ?? ""));

        var optionSize = Marshal.SizeOf<InternetPerConnOption>();
        var buffer = Marshal.AllocHGlobal(optionSize * options.Count);
        var strings = new List<IntPtr>();

        try
        {
            for (var i = 0; i < options.Count; i++)
            {
                var (option, intValue, stringValue) = options[i];
                var entry = new InternetPerConnOption { Option = option };

                if (stringValue is not null)
                {
                    var ptr = Marshal.StringToHGlobalUni(stringValue);
                    strings.Add(ptr);
                    entry.Value = ptr;
                }
                else
                {
                    entry.Value = new IntPtr(intValue ?? 0);
                }

                Marshal.StructureToPtr(entry, buffer + (i * optionSize), fDeleteOld: false);
            }

            var list = new InternetPerConnOptionList
            {
                Size = Marshal.SizeOf<InternetPerConnOptionList>(),
                Connection = IntPtr.Zero,
                OptionCount = options.Count,
                OptionError = 0,
                Options = buffer
            };

            var listSize = Marshal.SizeOf<InternetPerConnOptionList>();
            var listPtr = Marshal.AllocHGlobal(listSize);
            try
            {
                Marshal.StructureToPtr(list, listPtr, fDeleteOld: false);
                var applied = InternetSetOption(IntPtr.Zero, INTERNET_OPTION_PER_CONNECTION_OPTION, listPtr, listSize);

                // Make every already-running WinINet consumer pick the change up.
                InternetSetOption(IntPtr.Zero, INTERNET_OPTION_SETTINGS_CHANGED, IntPtr.Zero, 0);
                InternetSetOption(IntPtr.Zero, INTERNET_OPTION_REFRESH, IntPtr.Zero, 0);

                return applied;
            }
            finally
            {
                Marshal.FreeHGlobal(listPtr);
            }
        }
        finally
        {
            foreach (var ptr in strings) Marshal.FreeHGlobal(ptr);
            Marshal.FreeHGlobal(buffer);
        }
    }

    private const int INTERNET_OPTION_PER_CONNECTION_OPTION = 75;
    private const int INTERNET_OPTION_SETTINGS_CHANGED = 39;
    private const int INTERNET_OPTION_REFRESH = 37;

    private const int INTERNET_PER_CONN_FLAGS = 1;
    private const int INTERNET_PER_CONN_PROXY_SERVER = 2;
    private const int INTERNET_PER_CONN_PROXY_BYPASS = 3;
    private const int INTERNET_PER_CONN_AUTOCONFIG_URL = 4;

    private const int PROXY_TYPE_DIRECT = 1;
    private const int PROXY_TYPE_PROXY = 2;
    private const int PROXY_TYPE_AUTO_PROXY_URL = 4;

    [StructLayout(LayoutKind.Sequential)]
    private struct InternetPerConnOptionList
    {
        public int Size;
        public IntPtr Connection;
        public int OptionCount;
        public int OptionError;
        public IntPtr Options;
    }

    // x64 layout: a 4-byte option id, 4 bytes of padding, then an 8-byte union.
    [StructLayout(LayoutKind.Explicit)]
    private struct InternetPerConnOption
    {
        [FieldOffset(0)] public int Option;
        [FieldOffset(8)] public IntPtr Value;
    }

    [DllImport("wininet.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);
}
