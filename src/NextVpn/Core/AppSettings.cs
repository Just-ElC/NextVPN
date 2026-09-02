using System.Text.Json;
using System.Text.Json.Serialization;

namespace NextVpn.Core;

public enum AppTheme { System, Light, Dark }

/// <summary>
/// User-facing settings, persisted as JSON in the app's data directory.
/// Everything here maps onto either the generated tunnel-core config or local UI behaviour.
/// </summary>
public sealed class AppSettings
{
    // --- Tunnel ----------------------------------------------------------
    /// <summary>Two-letter egress country code. Empty string means "best available".</summary>
    public string EgressRegion { get; set; } = "";

    /// <summary>Restrict to these tunnel protocols. Empty means "let the engine choose".</summary>
    public List<string> LimitTunnelProtocols { get; set; } = new();

    /// <summary>0 = let the engine pick a free port.</summary>
    public int LocalHttpProxyPort { get; set; }
    public int LocalSocksProxyPort { get; set; }

    /// <summary>Optional upstream proxy, e.g. "http://user:pass@host:port".</summary>
    public string UpstreamProxyUrl { get; set; } = "";

    /// <summary>Relax the engine's dial timeouts, for very slow or lossy links.</summary>
    public bool DisableTimeouts { get; set; }

    /// <summary>
    /// Split tunnelling: let traffic whose destination is in your own country leave
    /// the machine directly instead of going through the tunnel. Keeps local banking
    /// and streaming working, at the cost of revealing those connections.
    /// </summary>
    public bool SplitTunnelOwnRegion { get; set; }

    // --- System integration ----------------------------------------------
    /// <summary>Point WinINet (Edge, Chrome, most desktop apps) at the local HTTP proxy while connected.</summary>
    public bool SetSystemProxy { get; set; } = true;

    /// <summary>Hosts that bypass the tunnel, semicolon separated. Supports * wildcards.</summary>
    public string ProxyBypassList { get; set; } = DefaultBypassList;

    /// <summary>
    /// Loopback, every RFC1918 range, link-local and IPv6 unique-local. Matches the
    /// list the stock client uses, which is well proven against real networks.
    /// </summary>
    public const string DefaultBypassList =
        "<local>;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.20.*;172.21.*;172.22.*;" +
        "172.23.*;172.24.*;172.25.*;172.26.*;172.27.*;172.28.*;172.29.*;172.30.*;172.31.*;" +
        "192.168.*;169.254.*;[fc*];[fd*];[fe8*];[fe9*];[fea*];[feb*]";

    public bool StartWithWindows { get; set; }
    public bool ConnectOnLaunch { get; set; }
    public bool StartMinimised { get; set; }
    public bool MinimiseToTray { get; set; } = true;

    // --- Appearance --------------------------------------------------------
    public AppTheme Theme { get; set; } = AppTheme.System;

    // --- Window geometry ----------------------------------------------------
    public int WindowWidth { get; set; }
    public int WindowHeight { get; set; }
    public int WindowLeft { get; set; } = int.MinValue;
    public int WindowTop { get; set; } = int.MinValue;

    // --- Persistence -------------------------------------------------------
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never
    };

    [JsonIgnore]
    public static string SettingsPath => Path.Combine(Paths.DataDirectory, "settings.json");

    public static AppSettings Load() => LoadFrom(SettingsPath);

    public void Save() => SaveTo(SettingsPath);

    /// <summary>Reads settings from an explicit file. Anything unreadable yields defaults.</summary>
    public static AppSettings LoadFrom(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                var loaded = JsonSerializer.Deserialize<AppSettings>(File.ReadAllText(path), JsonOpts);
                if (loaded is not null) return loaded;
            }
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            // Corrupt or unreadable settings must never stop the app from starting.
        }
        return new AppSettings();
    }

    /// <summary>
    /// Writes to a temporary file and moves it into place, so a settings file is
    /// never left half written if the machine loses power mid-save.
    /// </summary>
    public void SaveTo(string path)
    {
        try
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

            var tmp = path + ".tmp";
            File.WriteAllText(tmp, JsonSerializer.Serialize(this, JsonOpts));
            File.Move(tmp, path, overwrite: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Best effort: losing a settings write is not worth crashing over.
        }
    }
}

/// <summary>
/// Every path the app touches. Deliberately explicit: nothing is written to %TEMP%,
/// and no binary is ever self-extracted, self-replaced or self-deleted.
/// </summary>
public static class Paths
{
    /// <summary>Directory the .exe lives in.</summary>
    public static string AppDirectory { get; } =
        Path.GetDirectoryName(Environment.ProcessPath ?? AppContext.BaseDirectory) ?? AppContext.BaseDirectory;

    /// <summary>Engine binary + embedded server list, shipped next to the app.</summary>
    public static string EngineDirectory => Path.Combine(AppDirectory, "engine");

    public static string TunnelCoreExe => Path.Combine(EngineDirectory, "psiphon-tunnel-core.exe");
    public static string ServerListFile => Path.Combine(EngineDirectory, "server_list.dat");
    public static string BaseConfigFile => Path.Combine(EngineDirectory, "base.config");

    /// <summary>Per-user state: datastore, settings, generated config.</summary>
    public static string DataDirectory { get; } =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "NextVPN");

    public static string TunnelDataDirectory => Path.Combine(DataDirectory, "tunnel");
    public static string RuntimeConfigFile => Path.Combine(DataDirectory, "runtime.config");
}
