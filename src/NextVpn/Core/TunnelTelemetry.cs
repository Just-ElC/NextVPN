namespace NextVpn.Core;

/// <summary>What a notice changed, so the engine knows which events to raise.</summary>
[Flags]
public enum TelemetrySignal
{
    None          = 0,
    /// <summary>The engine reports at least one live tunnel.</summary>
    TunnelUp      = 1 << 0,
    /// <summary>The tunnel count fell to zero. The engine redials on its own.</summary>
    TunnelDown    = 1 << 1,
    PortsChanged  = 1 << 2,
    RegionsChanged= 1 << 3,
    StatsChanged  = 1 << 4,
}

/// <summary>
/// Everything the notice stream tells us about the current session.
///
/// Split out of <see cref="TunnelEngine"/> so the protocol handling — which is the
/// part that actually decides whether the app believes it is connected — can be
/// driven by a recorded notice stream in a test, with no child process involved.
/// </summary>
public sealed class TunnelTelemetry
{
    public TunnelStats Stats { get; } = new();

    public int SocksPort { get; private set; }
    public int HttpPort { get; private set; }
    public int TunnelCount { get; private set; }

    public string? ClientRegion { get; private set; }
    public string? ConnectedRegion { get; private set; }
    public string? ActiveProtocol { get; private set; }
    public string? HomepageUrl { get; private set; }
    public string? UpgradeAvailableVersion { get; private set; }

    public IReadOnlyList<string> AvailableRegions { get; private set; } = Array.Empty<string>();

    /// <summary>Applies one notice and reports what it moved.</summary>
    public TelemetrySignal Apply(Notice n)
    {
        switch (n.Type)
        {
            case NoticeType.ListeningSocksProxyPort:
                SocksPort = n.Int("port") ?? 0;
                return TelemetrySignal.PortsChanged;

            case NoticeType.ListeningHttpProxyPort:
                HttpPort = n.Int("port") ?? 0;
                return TelemetrySignal.PortsChanged;

            case NoticeType.Tunnels:
            {
                var previous = TunnelCount;
                TunnelCount = Math.Max(0, n.Int("count") ?? 0);

                if (TunnelCount > 0)
                {
                    // First tunnel of the session starts the clock; later ones do not
                    // restart it, so a mid-session redial does not reset the uptime.
                    Stats.ConnectedAt ??= DateTimeOffset.Now;
                    return TelemetrySignal.TunnelUp;
                }

                if (previous > 0)
                {
                    Stats.ConnectedAt = null;
                    return TelemetrySignal.TunnelDown;
                }
                return TelemetrySignal.None;
            }

            case NoticeType.ActiveTunnel:
                ActiveProtocol = n.String("protocol");
                return TelemetrySignal.None;

            case NoticeType.ConnectedServerRegion:
                ConnectedRegion = n.String("serverRegion");
                return TelemetrySignal.None;

            case NoticeType.ClientRegion:
                ClientRegion = n.String("region");
                return TelemetrySignal.None;

            case NoticeType.AvailableEgressRegions:
                AvailableRegions = n.StringArray("regions");
                return TelemetrySignal.RegionsChanged;

            case NoticeType.Homepage:
                HomepageUrl = n.String("url");
                return TelemetrySignal.None;

            case NoticeType.ClientUpgradeAvailable:
                // Recorded so the interface can mention it. Nothing is downloaded and
                // no file belonging to this application is ever replaced.
                UpgradeAvailableVersion = n.String("version");
                return TelemetrySignal.None;

            case NoticeType.BytesTransferred:
                Stats.BytesSent += Math.Max(0, n.Long("sent") ?? 0);
                Stats.BytesReceived += Math.Max(0, n.Long("received") ?? 0);
                return TelemetrySignal.StatsChanged;

            default:
                return TelemetrySignal.None;
        }
    }

    /// <summary>
    /// Clears everything that belongs to one run of the engine. The available region
    /// list deliberately survives, so the picker is not empty between connections.
    /// </summary>
    public void Reset()
    {
        Stats.Reset();
        SocksPort = 0;
        HttpPort = 0;
        TunnelCount = 0;
        ConnectedRegion = null;
        ActiveProtocol = null;
        HomepageUrl = null;
    }

    /// <summary>Called when the engine process is gone: the listeners went with it.</summary>
    public void ClearListeners()
    {
        SocksPort = 0;
        HttpPort = 0;
        TunnelCount = 0;
        Stats.ConnectedAt = null;
    }
}
