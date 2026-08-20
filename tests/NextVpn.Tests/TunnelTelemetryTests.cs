using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// The session state machine, driven by the same notice lines the engine emits.
/// This is what decides whether the application believes it is connected, so it is
/// exercised here with recorded streams rather than by watching a real tunnel.
/// </summary>
public class TunnelTelemetryTests
{
    private static Notice N(string json)
    {
        Assert.True(Notice.TryParse(json, out var notice), json);
        return notice;
    }

    private static TelemetrySignal Feed(TunnelTelemetry t, params string[] lines)
    {
        var last = TelemetrySignal.None;
        foreach (var line in lines) last = t.Apply(N(line));
        return last;
    }

    // ------------------------------------------------------------------ ports

    [Fact]
    public void Listener_ports_are_picked_up_separately()
    {
        var t = new TunnelTelemetry();

        Assert.Equal(TelemetrySignal.PortsChanged,
            t.Apply(N("""{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}""")));
        Assert.Equal(TelemetrySignal.PortsChanged,
            t.Apply(N("""{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}""")));

        Assert.Equal(57104, t.HttpPort);
        Assert.Equal(57105, t.SocksPort);
    }

    // ---------------------------------------------------------------- tunnels

    [Fact]
    public void The_first_tunnel_starts_the_session_clock()
    {
        var t = new TunnelTelemetry();

        var signal = t.Apply(N("""{"noticeType":"Tunnels","data":{"count":1}}"""));

        Assert.Equal(TelemetrySignal.TunnelUp, signal);
        Assert.NotNull(t.Stats.ConnectedAt);
        Assert.Equal(1, t.TunnelCount);
    }

    [Fact]
    public void A_second_tunnel_does_not_restart_the_clock()
    {
        var t = new TunnelTelemetry();
        Feed(t, """{"noticeType":"Tunnels","data":{"count":1}}""");
        var started = t.Stats.ConnectedAt;

        Feed(t, """{"noticeType":"Tunnels","data":{"count":2}}""");

        Assert.Equal(started, t.Stats.ConnectedAt);
    }

    [Fact]
    public void Losing_the_last_tunnel_stops_the_clock_and_reports_it()
    {
        var t = new TunnelTelemetry();
        Feed(t, """{"noticeType":"Tunnels","data":{"count":1}}""");

        var signal = t.Apply(N("""{"noticeType":"Tunnels","data":{"count":0}}"""));

        Assert.Equal(TelemetrySignal.TunnelDown, signal);
        Assert.Null(t.Stats.ConnectedAt);
        Assert.Equal(0, t.TunnelCount);
    }

    [Fact]
    public void A_zero_count_before_anything_connected_is_not_a_disconnection()
    {
        // The engine reports Tunnels 0 while it is still dialling. Treating that as a
        // drop would flip the interface back and forth during a normal connect.
        var t = new TunnelTelemetry();

        Assert.Equal(TelemetrySignal.None, t.Apply(N("""{"noticeType":"Tunnels","data":{"count":0}}""")));
        Assert.Null(t.Stats.ConnectedAt);
    }

    [Fact]
    public void A_missing_or_negative_count_is_treated_as_no_tunnel()
    {
        var t = new TunnelTelemetry();

        Assert.Equal(TelemetrySignal.None, t.Apply(N("""{"noticeType":"Tunnels","data":{}}""")));
        Assert.Equal(TelemetrySignal.None, t.Apply(N("""{"noticeType":"Tunnels","data":{"count":-1}}""")));
        Assert.Equal(0, t.TunnelCount);
    }

    // ------------------------------------------------------------------ bytes

    [Fact]
    public void Byte_counters_accumulate_across_notices()
    {
        var t = new TunnelTelemetry();

        var signal = Feed(t,
            """{"noticeType":"BytesTransferred","data":{"sent":100,"received":900}}""",
            """{"noticeType":"BytesTransferred","data":{"sent":50,"received":1000}}""");

        Assert.Equal(TelemetrySignal.StatsChanged, signal);
        Assert.Equal(150, t.Stats.BytesSent);
        Assert.Equal(1900, t.Stats.BytesReceived);
    }

    [Fact]
    public void A_nonsense_byte_delta_cannot_run_the_totals_backwards()
    {
        var t = new TunnelTelemetry();

        Feed(t,
            """{"noticeType":"BytesTransferred","data":{"sent":100,"received":100}}""",
            """{"noticeType":"BytesTransferred","data":{"sent":-500,"received":-500}}""");

        Assert.Equal(100, t.Stats.BytesSent);
        Assert.Equal(100, t.Stats.BytesReceived);
    }

    // ---------------------------------------------------------------- details

    [Fact]
    public void Session_details_are_recorded_without_disturbing_the_connection_state()
    {
        var t = new TunnelTelemetry();

        var signal = Feed(t,
            """{"noticeType":"ActiveTunnel","data":{"protocol":"INPROXY-WEBRTC-QUIC-OSSH"}}""",
            """{"noticeType":"ConnectedServerRegion","data":{"serverRegion":"DE"}}""",
            """{"noticeType":"ClientRegion","data":{"region":"RU"}}""",
            """{"noticeType":"Homepage","data":{"url":"https://example.invalid/"}}""");

        Assert.Equal(TelemetrySignal.None, signal);
        Assert.Equal("INPROXY-WEBRTC-QUIC-OSSH", t.ActiveProtocol);
        Assert.Equal("DE", t.ConnectedRegion);
        Assert.Equal("RU", t.ClientRegion);
        Assert.Equal("https://example.invalid/", t.HomepageUrl);
    }

    [Fact]
    public void An_available_upgrade_is_recorded_and_nothing_else_happens()
    {
        var t = new TunnelTelemetry();

        var signal = t.Apply(N("""{"noticeType":"ClientUpgradeAvailable","data":{"version":"181"}}"""));

        Assert.Equal(TelemetrySignal.None, signal);
        Assert.Equal("181", t.UpgradeAvailableVersion);
    }

    [Fact]
    public void The_egress_region_list_is_replaced_wholesale()
    {
        var t = new TunnelTelemetry();

        var signal = Feed(t,
            """{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL"]}}""",
            """{"noticeType":"AvailableEgressRegions","data":{"regions":["US"]}}""");

        Assert.Equal(TelemetrySignal.RegionsChanged, signal);
        Assert.Equal(new[] { "US" }, t.AvailableRegions);
    }

    [Fact]
    public void An_unrecognised_notice_changes_nothing()
    {
        var t = new TunnelTelemetry();

        Assert.Equal(TelemetrySignal.None,
            t.Apply(N("""{"noticeType":"SomethingNewUpstream","data":{"whatever":1}}""")));
    }

    // ------------------------------------------------------------------ reset

    [Fact]
    public void Starting_a_new_run_clears_the_session_but_keeps_the_region_list()
    {
        var t = new TunnelTelemetry();
        Feed(t,
            """{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL"]}}""",
            """{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}""",
            """{"noticeType":"Tunnels","data":{"count":1}}""",
            """{"noticeType":"BytesTransferred","data":{"sent":1,"received":2}}""",
            """{"noticeType":"ActiveTunnel","data":{"protocol":"OSSH"}}""");

        t.Reset();

        Assert.Equal(0, t.HttpPort);
        Assert.Equal(0, t.TunnelCount);
        Assert.Equal(0, t.Stats.BytesSent);
        Assert.Equal(0, t.Stats.BytesReceived);
        Assert.Null(t.Stats.ConnectedAt);
        Assert.Null(t.ActiveProtocol);

        // The picker would otherwise go empty every time the tunnel restarts.
        Assert.Equal(new[] { "DE", "NL" }, t.AvailableRegions);
    }

    [Fact]
    public void When_the_engine_exits_the_listeners_go_but_the_totals_stay()
    {
        var t = new TunnelTelemetry();
        Feed(t,
            """{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}""",
            """{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}""",
            """{"noticeType":"Tunnels","data":{"count":1}}""",
            """{"noticeType":"BytesTransferred","data":{"sent":10,"received":20}}""");

        t.ClearListeners();

        Assert.Equal(0, t.HttpPort);
        Assert.Equal(0, t.SocksPort);
        Assert.Null(t.Stats.ConnectedAt);

        // The last screenful of numbers should not blank out the moment you disconnect.
        Assert.Equal(10, t.Stats.BytesSent);
        Assert.Equal(20, t.Stats.BytesReceived);
    }

    // --------------------------------------------------------------- sequence

    [Fact]
    public void A_full_connect_sequence_ends_up_connected()
    {
        // The order below is the one a real establishment produces.
        var t = new TunnelTelemetry();

        Feed(t,
            """{"noticeType":"ClientRegion","data":{"region":"RU"}}""",
            """{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL","US"]}}""",
            """{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}""",
            """{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}""",
            """{"noticeType":"ConnectingServer","data":{"ipAddress":"203.0.113.1"}}""",
            """{"noticeType":"ConnectedServer","data":{"ipAddress":"203.0.113.1"}}""",
            """{"noticeType":"ActiveTunnel","data":{"protocol":"OSSH"}}""",
            """{"noticeType":"ConnectedServerRegion","data":{"serverRegion":"DE"}}""",
            """{"noticeType":"Tunnels","data":{"count":1}}""",
            """{"noticeType":"BytesTransferred","data":{"sent":512,"received":8192}}""");

        Assert.Equal(1, t.TunnelCount);
        Assert.Equal(57104, t.HttpPort);
        Assert.Equal(57105, t.SocksPort);
        Assert.Equal("DE", t.ConnectedRegion);
        Assert.Equal("RU", t.ClientRegion);
        Assert.Equal("OSSH", t.ActiveProtocol);
        Assert.Equal(3, t.AvailableRegions.Count);
        Assert.Equal(8192, t.Stats.BytesReceived);
        Assert.NotNull(t.Stats.ConnectedAt);
        Assert.True(t.Stats.Uptime >= TimeSpan.Zero);
    }

    [Fact]
    public void A_mid_session_redial_keeps_the_totals_and_only_pauses_the_clock()
    {
        var t = new TunnelTelemetry();
        Feed(t,
            """{"noticeType":"Tunnels","data":{"count":1}}""",
            """{"noticeType":"BytesTransferred","data":{"sent":10,"received":20}}""",
            """{"noticeType":"Tunnels","data":{"count":0}}""");

        Assert.Null(t.Stats.ConnectedAt);
        Assert.Equal(20, t.Stats.BytesReceived);

        Feed(t, """{"noticeType":"Tunnels","data":{"count":1}}""");

        Assert.NotNull(t.Stats.ConnectedAt);
        Assert.Equal(20, t.Stats.BytesReceived);
    }
}
