using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace NextVpn.Core;

/// <summary>
/// Builds the JSON configuration handed to psiphon-tunnel-core.
///
/// The base config carries the opaque sponsor identity and crypto material
/// (PropagationChannelId, SponsorId, signature public keys, AdditionalParameters).
/// Those fields are passed through byte-for-byte and never interpreted here.
/// Only the runtime fields this client actually owns are overridden.
/// </summary>
public static class TunnelConfig
{
    /// <summary>
    /// Fields that make the stock client rewrite files outside its own directory,
    /// or replace its own binary. They are stripped unconditionally.
    /// </summary>
    private static readonly string[] StrippedFields =
    {
        "MigrateDataStoreDirectory",
        "MigrateObfuscatedServerListDownloadDirectory",
        "MigrateRemoteServerListDownloadFilename",
        "MigrateUpgradeDownloadFilename",
        "UpgradeDownloadURLs",
        "UpgradeDownloadClientVersionHeader",
        "UpgradeDownloadFilename",
    };

    /// <summary>UTF-8 with no byte order mark. The engine's JSON parser rejects a BOM.</summary>
    private static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);

    public static bool BaseConfigExists => File.Exists(Paths.BaseConfigFile);

    /// <summary>
    /// Writes the runtime config and returns its path.
    /// </summary>
    public static string Write(AppSettings settings)
    {
        Directory.CreateDirectory(Paths.TunnelDataDirectory);
        return WriteTo(Paths.RuntimeConfigFile, ReadBaseConfig(), settings, Paths.TunnelDataDirectory);
    }

    /// <summary>
    /// Builds the config and writes it to an explicit path.
    ///
    /// Always BOM-less UTF-8: the engine JSON parser treats a byte order mark as
    /// content and fails with "invalid character looking for beginning of value".
    /// </summary>
    public static string WriteTo(string path, string baseConfigJson, AppSettings settings, string dataRootDirectory)
    {
        var json = Build(baseConfigJson, settings, dataRootDirectory);

        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

        File.WriteAllText(path, json, Utf8NoBom);
        return path;
    }

    /// <summary>
    /// Produces the runtime config text from a base config, without touching disk.
    ///
    /// Everything the client decides is applied here and nowhere else, so the rules
    /// about what is stripped, forced or overridden can be verified directly.
    /// </summary>
    public static string Build(string baseConfigJson, AppSettings settings, string dataRootDirectory)
    {
        var root = Parse(baseConfigJson);

        // --- Hard-disabled behaviour ------------------------------------
        // The stock Windows client downloads a replacement .exe, renames the
        // running binary to *.orig on next launch and swaps itself out. This
        // client never does that, so the engine is told not to fetch upgrades.
        foreach (var field in StrippedFields)
            root.Remove(field);

        root["EnableUpgradeDownload"] = false;

        // --- Storage -----------------------------------------------------
        root["DataRootDirectory"] = dataRootDirectory;

        // --- Exit selection ----------------------------------------------
        root["EgressRegion"] = settings.EgressRegion ?? "";

        // --- Local proxies -------------------------------------------------
        root["LocalHttpProxyPort"] = settings.LocalHttpProxyPort;
        root["LocalSocksProxyPort"] = settings.LocalSocksProxyPort;

        // --- Transport restrictions ----------------------------------------
        if (settings.LimitTunnelProtocols.Count > 0)
        {
            var arr = new JsonArray();
            foreach (var p in settings.LimitTunnelProtocols) arr.Add(p);
            root["LimitTunnelProtocols"] = arr;
        }
        else
        {
            root.Remove("LimitTunnelProtocols");
        }

        root["UpstreamProxyUrl"] = settings.UpstreamProxyUrl ?? "";

        // Split tunnelling. The engine resolves the client's own country itself, so
        // this needs no region argument from us.
        if (settings.SplitTunnelOwnRegion)
            root["SplitTunnelOwnRegion"] = true;
        else
            root.Remove("SplitTunnelOwnRegion");

        // "Relax timeouts" widens the engine's latency budget and removes the overall
        // establishment deadline. Both field names are verified against the engine
        // binary; NetworkLatencyMultiplierLambda, used previously, controls the random
        // distribution of the multiplier rather than its size, and was the wrong knob.
        if (settings.DisableTimeouts)
        {
            root["NetworkLatencyMultiplier"] = 3.0;
            root["EstablishTunnelTimeoutSeconds"] = 0;
        }
        else
        {
            root.Remove("NetworkLatencyMultiplier");
            root.Remove("EstablishTunnelTimeoutSeconds");
        }

        // --- Telemetry the UI depends on ------------------------------------
        root["EmitBytesTransferred"] = true;
        root["EmitDiagnosticNotices"] = true;
        root["EmitDiagnosticNetworkParameters"] = true;
        root["EmitServerAlerts"] = true;

        root["ClientPlatform"] = ClientPlatform();

        return root.ToJsonString(new JsonSerializerOptions { WriteIndented = false });
    }

    private static string ReadBaseConfig()
    {
        if (!File.Exists(Paths.BaseConfigFile))
            throw new FileNotFoundException(
                $"Tunnel base configuration is missing: {Paths.BaseConfigFile}", Paths.BaseConfigFile);

        return File.ReadAllText(Paths.BaseConfigFile);
    }

    private static JsonObject Parse(string json)
    {
        // File.ReadAllText strips a byte order mark, but a config handed over as text
        // may still carry one, and the JSON reader treats it as content.
        if (json.Length > 0 && json[0] == '\uFEFF') json = json[1..];

        JsonNode? node;
        try
        {
            node = JsonNode.Parse(json);
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("Tunnel base configuration is not valid JSON.", ex);
        }

        if (node is not JsonObject obj)
            throw new InvalidDataException("Tunnel base configuration is not a JSON object.");

        return obj;
    }

    /// <summary>
    /// Mirrors the platform string shape the engine expects: Windows_&lt;version&gt;_&lt;product&gt;.
    /// Must not contain spaces or underscores beyond the separators.
    /// </summary>
    private static string ClientPlatform()
    {
        var v = Environment.OSVersion.Version;
        var build = $"{v.Major}.{v.Minor}.{v.Build}";
        return $"Windows_{build}_NextVPN";
    }
}
