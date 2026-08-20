using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// What reaches the activity log, and what is allowed to wake the UI thread. The
/// engine emits hundreds of notices per connection attempt, so both answers are
/// load-bearing rather than cosmetic.
/// </summary>
public class NoticePolicyTests
{
    [Theory]
    [InlineData(NoticeType.Error, NoticeLevel.Error)]
    [InlineData(NoticeType.Warning, NoticeLevel.Warning)]
    [InlineData(NoticeType.Info, NoticeLevel.Info)]
    [InlineData(NoticeType.Tunnels, NoticeLevel.Info)]
    [InlineData("AnythingElse", NoticeLevel.Info)]
    public void Severity_follows_the_notice_type(string type, NoticeLevel expected) =>
        Assert.Equal(expected, NoticePolicy.LevelOf(type));

    [Theory]
    [InlineData(NoticeType.Error)]
    [InlineData(NoticeType.Warning)]
    public void Problems_are_always_logged(string type)
    {
        Assert.True(NoticePolicy.ShouldLog(type, verbose: false));
        Assert.True(NoticePolicy.ShouldLog(type, verbose: true));
    }

    [Theory]
    [InlineData(NoticeType.Tunnels)]
    [InlineData(NoticeType.ConnectedServer)]
    [InlineData(NoticeType.ActiveTunnel)]
    [InlineData(NoticeType.ConnectedServerRegion)]
    [InlineData(NoticeType.ClientRegion)]
    [InlineData(NoticeType.ListeningHttpProxyPort)]
    [InlineData(NoticeType.ListeningSocksProxyPort)]
    [InlineData(NoticeType.Homepage)]
    [InlineData(NoticeType.ServerAlert)]
    [InlineData(NoticeType.Untunneled)]
    [InlineData(NoticeType.ClientUpgradeAvailable)]
    public void Milestones_are_logged_without_turning_diagnostics_on(string type) =>
        Assert.True(NoticePolicy.ShouldLog(type, verbose: false));

    [Theory]
    [InlineData(NoticeType.Info)]
    [InlineData(NoticeType.ConnectingServer)]
    [InlineData(NoticeType.TrafficRateLimits)]
    [InlineData("CandidateServers")]
    public void Routine_chatter_is_held_back_until_diagnostics_are_on(string type)
    {
        Assert.False(NoticePolicy.ShouldLog(type, verbose: false));
        Assert.True(NoticePolicy.ShouldLog(type, verbose: true));
    }

    [Fact]
    public void Throughput_never_reaches_the_log_unless_it_is_asked_for()
    {
        // One line per second would push everything that matters out of the buffer.
        Assert.False(NoticePolicy.ShouldLog(NoticeType.BytesTransferred, verbose: false));
        Assert.True(NoticePolicy.ShouldLog(NoticeType.BytesTransferred, verbose: true));
    }

    [Fact]
    public void Throughput_still_reaches_the_graph()
    {
        // Not logged, but it does have to cross to the UI thread, or the throughput
        // graph would only move while diagnostics were switched on.
        Assert.True(NoticePolicy.ChangesVisibleState(NoticeType.BytesTransferred));
        Assert.True(NoticePolicy.NeedsUi(NoticeType.BytesTransferred, verbose: false));
    }

    [Theory]
    [InlineData(NoticeType.ClientRegion)]
    [InlineData(NoticeType.ActiveTunnel)]
    [InlineData(NoticeType.ConnectedServerRegion)]
    [InlineData(NoticeType.ListeningHttpProxyPort)]
    [InlineData(NoticeType.ListeningSocksProxyPort)]
    [InlineData(NoticeType.Homepage)]
    [InlineData(NoticeType.ClientUpgradeAvailable)]
    public void Notices_that_move_something_visible_are_marked_as_such(string type) =>
        Assert.True(NoticePolicy.ChangesVisibleState(type));

    [Theory]
    [InlineData(NoticeType.ConnectingServer)]
    [InlineData(NoticeType.TrafficRateLimits)]
    [InlineData("CandidateServers")]
    public void Everything_else_stays_off_the_UI_thread_by_default(string type)
    {
        Assert.False(NoticePolicy.NeedsUi(type, verbose: false));
        Assert.True(NoticePolicy.NeedsUi(type, verbose: true));
    }
}
