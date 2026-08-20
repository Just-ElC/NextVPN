namespace NextVpn.Core;

/// <summary>
/// Every word the connection panel says, derived from the tunnel state alone.
///
/// This is separate from the view model because it is the part a user actually
/// reads, and because a pure function of (state, region, detail) can be tested
/// exhaustively without a dispatcher, a window or an engine process.
/// </summary>
public static class StatusPresenter
{
    public static string Heading(TunnelState state) => state switch
    {
        TunnelState.Connected     => "Connected",
        TunnelState.Connecting    => "Connecting",
        TunnelState.Disconnecting => "Disconnecting",
        TunnelState.Faulted       => "Connection failed",
        _                         => "Not connected"
    };

    public static string Subtitle(TunnelState state, string? connectedRegion, string? detail) => state switch
    {
        TunnelState.Connected when connectedRegion is { Length: > 0 } r =>
            $"Traffic is exiting through {Regions.NameOf(r)}",
        TunnelState.Connected     => "Your traffic is protected",
        TunnelState.Connecting    => "Finding a route that works on this network",
        TunnelState.Disconnecting => "Closing the tunnel",
        TunnelState.Faulted       => detail is { Length: > 0 } d ? d : "Something went wrong",
        _                         => "Your traffic is going out unprotected"
    };

    /// <summary>What pressing the connect control will do next.</summary>
    public static string ActionLabel(TunnelState state) => state switch
    {
        TunnelState.Connected     => "Disconnect",
        TunnelState.Connecting    => "Cancel",
        TunnelState.Disconnecting => "Disconnecting",
        _                         => "Connect"
    };

    /// <summary>
    /// False only while the engine is being torn down. The engine cannot be restarted
    /// until its process has actually gone, so offering the action there would be a
    /// button that silently does nothing.
    /// </summary>
    public static bool CanToggle(TunnelState state) => state != TunnelState.Disconnecting;

    /// <summary>Whether the connect control should read as "on" rather than "off".</summary>
    public static bool IsLive(TunnelState state) =>
        state is TunnelState.Connected or TunnelState.Connecting;
}
