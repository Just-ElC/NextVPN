using NextVpn.Interop;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// The proxy string is what the whole machine is pointed at while a tunnel is up.
/// Only the string building is exercised here: applying it writes to the registry
/// and to WinINet, which a test has no business doing to the machine it runs on.
/// </summary>
public class SystemProxyTests
{
    [Fact]
    public void Http_covers_both_http_and_https()
    {
        // WinINet needs the https scheme named explicitly; without it, secure
        // traffic bypasses the tunnel entirely.
        Assert.Equal("http=127.0.0.1:8080;https=127.0.0.1:8080", SystemProxy.BuildProxyString(8080, 0));
    }

    [Fact]
    public void Socks_is_declared_separately_so_socks_aware_apps_can_use_it_directly()
    {
        Assert.Equal("http=127.0.0.1:8080;https=127.0.0.1:8080;socks=127.0.0.1:1080",
            SystemProxy.BuildProxyString(8080, 1080));
    }

    [Fact]
    public void A_listener_that_is_not_open_is_not_advertised()
    {
        Assert.Equal("socks=127.0.0.1:1080", SystemProxy.BuildProxyString(0, 1080));
        Assert.Equal("", SystemProxy.BuildProxyString(0, 0));
    }

    [Fact]
    public void Everything_points_at_loopback_only()
    {
        var proxy = SystemProxy.BuildProxyString(57104, 57105);

        foreach (var part in proxy.Split(';'))
            Assert.Contains("=127.0.0.1:", part);
    }

    [Fact]
    public void Applying_nothing_is_refused_rather_than_pointing_the_machine_at_port_zero()
    {
        // Guards the case where Tunnels arrives before ListeningHttpProxyPort.
        Assert.False(SystemProxy.Apply(0, 1080, "<local>"));
    }
}
