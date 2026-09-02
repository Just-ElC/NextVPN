namespace NextVpn.Core;

/// <summary>
/// Decides what the activity log does with each notice.
///
/// The engine emits hundreds of notices while a tunnel is being established and
/// most of them mean nothing to a user, so this runs on the engine's reader thread
/// and keeps the UI thread out of it entirely unless something is worth showing.
/// </summary>
public static class NoticePolicy
{
    public static NoticeLevel LevelOf(string type) => type switch
    {
        NoticeType.Error   => NoticeLevel.Error,
        NoticeType.Warning => NoticeLevel.Warning,
        _                  => NoticeLevel.Info
    };

    /// <summary>Info notices a user benefits from seeing even with diagnostics off.</summary>
    public static bool IsInteresting(string type) => type is
        NoticeType.Tunnels or NoticeType.ConnectedServer or NoticeType.ActiveTunnel or
        NoticeType.ConnectedServerRegion or NoticeType.ClientRegion or
        NoticeType.ListeningHttpProxyPort or NoticeType.ListeningSocksProxyPort or
        NoticeType.Homepage or NoticeType.ServerAlert or NoticeType.Untunneled or
        NoticeType.ClientUpgradeAvailable;

    /// <summary>Notices that move something visible, whether or not they are logged.</summary>
    public static bool ChangesVisibleState(string type) => type is
        NoticeType.ClientRegion or NoticeType.ActiveTunnel or NoticeType.ConnectedServerRegion or
        NoticeType.ListeningHttpProxyPort or NoticeType.ListeningSocksProxyPort or
        NoticeType.Homepage or NoticeType.ClientUpgradeAvailable or NoticeType.BytesTransferred;

    public static bool ShouldLog(string type, bool verbose)
    {
        // Throughput belongs in the graph. In the log it would be one line per second
        // forever, pushing everything that matters out of the buffer.
        if (type == NoticeType.BytesTransferred) return verbose;

        return LevelOf(type) != NoticeLevel.Info || verbose || IsInteresting(type);
    }

    /// <summary>True when the notice is worth waking the UI thread for at all.</summary>
    public static bool NeedsUi(string type, bool verbose) =>
        ShouldLog(type, verbose) || ChangesVisibleState(type);
}

/// <summary>Severity of a log line. Mirrors the three levels the engine reports.</summary>
public enum NoticeLevel { Info, Warning, Error }
