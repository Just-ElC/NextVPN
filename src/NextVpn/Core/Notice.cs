using System.Text.Json;
using System.Text.Json.Nodes;

namespace NextVpn.Core;

/// <summary>
/// One line of psiphon-tunnel-core's notice stream.
/// The engine emits newline-delimited JSON objects shaped as
/// { "noticeType": "...", "data": { ... }, "timestamp": "..." }.
/// </summary>
public sealed record Notice(string Type, JsonObject Data, DateTimeOffset Timestamp, string Raw)
{
    public static bool TryParse(string line, out Notice notice)
    {
        notice = default!;
        if (string.IsNullOrWhiteSpace(line)) return false;

        try
        {
            if (JsonNode.Parse(line) is not JsonObject root) return false;

            var type = root["noticeType"]?.GetValue<string>();
            if (string.IsNullOrEmpty(type)) return false;

            var data = root["data"] as JsonObject ?? new JsonObject();
            var ts = root["timestamp"]?.GetValue<string>();
            var when = DateTimeOffset.TryParse(ts, out var parsed) ? parsed : DateTimeOffset.Now;

            notice = new Notice(type, data, when, line);
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    public string? String(string key) =>
        Data.TryGetPropertyValue(key, out var n) && n is not null ? n.ToString() : null;

    // Numbers are read without ever throwing: a value too large for the type, or a
    // type nobody expected, has to read as "absent" rather than take down the reader
    // loop that the whole connection state depends on.

    public int? Int(string key)
    {
        if (!Data.TryGetPropertyValue(key, out var n) || n is null) return null;
        return n.GetValueKind() switch
        {
            JsonValueKind.Number => n.AsValue().TryGetValue<int>(out var v) ? v : null,
            JsonValueKind.String => int.TryParse(n.GetValue<string>(), out var v) ? v : null,
            _ => null
        };
    }

    public long? Long(string key)
    {
        if (!Data.TryGetPropertyValue(key, out var n) || n is null) return null;
        return n.GetValueKind() switch
        {
            JsonValueKind.Number => n.AsValue().TryGetValue<long>(out var v) ? v : null,
            JsonValueKind.String => long.TryParse(n.GetValue<string>(), out var v) ? v : null,
            _ => null
        };
    }

    public IReadOnlyList<string> StringArray(string key)
    {
        if (!Data.TryGetPropertyValue(key, out var n) || n is not JsonArray arr) return Array.Empty<string>();
        return arr.Where(x => x is not null).Select(x => x!.ToString()).ToList();
    }

    /// <summary>Human-readable single-line rendering, used by the log view.</summary>
    public string Message =>
        String("message") ?? Data.ToJsonString();
}

/// <summary>Notice type names emitted by psiphon-tunnel-core that this client acts on.</summary>
public static class NoticeType
{
    public const string Tunnels                 = "Tunnels";
    public const string ListeningSocksProxyPort = "ListeningSocksProxyPort";
    public const string ListeningHttpProxyPort  = "ListeningHttpProxyPort";
    public const string ConnectingServer        = "ConnectingServer";
    public const string ConnectedServer         = "ConnectedServer";
    public const string ActiveTunnel            = "ActiveTunnel";
    public const string ConnectedServerRegion   = "ConnectedServerRegion";
    public const string ClientRegion            = "ClientRegion";
    public const string AvailableEgressRegions  = "AvailableEgressRegions";
    public const string Homepage                = "Homepage";
    public const string BytesTransferred        = "BytesTransferred";
    public const string ClientUpgradeAvailable  = "ClientUpgradeAvailable";
    public const string ServerAlert             = "ServerAlert";
    public const string SocksProxyPortInUse     = "SocksProxyPortInUse";
    public const string HttpProxyPortInUse      = "HttpProxyPortInUse";
    public const string Untunneled              = "Untunneled";
    public const string TrafficRateLimits       = "TrafficRateLimits";
    public const string Exiting                 = "Exiting";
    public const string Info                    = "Info";
    public const string Warning                 = "Warning";
    public const string Error                   = "Error";
}
