using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// The words on the connection panel. These are the only sentences most users will
/// ever read from this application, so every state has to produce one.
/// </summary>
public class StatusPresenterTests
{
    [Theory]
    [InlineData(TunnelState.Disconnected, "Not connected")]
    [InlineData(TunnelState.Connecting, "Connecting")]
    [InlineData(TunnelState.Connected, "Connected")]
    [InlineData(TunnelState.Disconnecting, "Disconnecting")]
    [InlineData(TunnelState.Faulted, "Connection failed")]
    public void Every_state_has_a_heading(TunnelState state, string expected) =>
        Assert.Equal(expected, StatusPresenter.Heading(state));

    [Fact]
    public void Connected_subtitle_names_the_exit_country()
    {
        Assert.Equal("Traffic is exiting through Germany",
            StatusPresenter.Subtitle(TunnelState.Connected, "DE", null));
    }

    [Fact]
    public void Connected_subtitle_still_says_something_before_the_region_arrives()
    {
        // ConnectedServerRegion can land after Tunnels, so there is a window where
        // the app is connected and does not yet know where the exit is.
        Assert.Equal("Your traffic is protected",
            StatusPresenter.Subtitle(TunnelState.Connected, null, null));
        Assert.Equal("Your traffic is protected",
            StatusPresenter.Subtitle(TunnelState.Connected, "", null));
    }

    [Fact]
    public void Fault_subtitle_prefers_the_reported_reason()
    {
        Assert.Equal("Tunnel engine not found",
            StatusPresenter.Subtitle(TunnelState.Faulted, null, "Tunnel engine not found"));
    }

    [Fact]
    public void Fault_subtitle_falls_back_when_nothing_was_reported()
    {
        Assert.Equal("Something went wrong", StatusPresenter.Subtitle(TunnelState.Faulted, null, null));
        Assert.Equal("Something went wrong", StatusPresenter.Subtitle(TunnelState.Faulted, null, ""));
    }

    [Fact]
    public void Idle_subtitle_does_not_pretend_anything_is_protected() =>
        Assert.Equal("Your traffic is going out unprotected",
            StatusPresenter.Subtitle(TunnelState.Disconnected, "DE", null));

    [Theory]
    [InlineData(TunnelState.Disconnected, "Connect")]
    [InlineData(TunnelState.Faulted, "Connect")]
    [InlineData(TunnelState.Connecting, "Cancel")]
    [InlineData(TunnelState.Connected, "Disconnect")]
    [InlineData(TunnelState.Disconnecting, "Disconnecting")]
    public void Action_label_says_what_the_press_will_do(TunnelState state, string expected) =>
        Assert.Equal(expected, StatusPresenter.ActionLabel(state));

    [Theory]
    [InlineData(TunnelState.Disconnected, true)]
    [InlineData(TunnelState.Connecting, true)]
    [InlineData(TunnelState.Connected, true)]
    [InlineData(TunnelState.Faulted, true)]
    [InlineData(TunnelState.Disconnecting, false)]
    public void The_control_is_only_dead_while_the_engine_is_being_torn_down(TunnelState state, bool expected) =>
        Assert.Equal(expected, StatusPresenter.CanToggle(state));

    [Theory]
    [InlineData(TunnelState.Connected, true)]
    [InlineData(TunnelState.Connecting, true)]
    [InlineData(TunnelState.Disconnecting, false)]
    [InlineData(TunnelState.Disconnected, false)]
    [InlineData(TunnelState.Faulted, false)]
    public void Live_means_up_or_on_its_way_up(TunnelState state, bool expected) =>
        Assert.Equal(expected, StatusPresenter.IsLive(state));
}
