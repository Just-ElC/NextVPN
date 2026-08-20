using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// Persisted settings. A settings file that cannot be read, or a half-written one,
/// must never stop the application from starting.
/// </summary>
public class AppSettingsTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("nextvpn-settings").FullName;

    private string Path(string name = "settings.json") => System.IO.Path.Combine(_dir, name);

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch (IOException) { }
    }

    // --------------------------------------------------------------- defaults

    [Fact]
    public void Defaults_are_the_safe_ones()
    {
        var s = new AppSettings();

        Assert.Equal("", s.EgressRegion);            // best performance
        Assert.Empty(s.LimitTunnelProtocols);        // engine picks the transport
        Assert.Equal(0, s.LocalHttpProxyPort);       // engine picks a free port
        Assert.Equal(0, s.LocalSocksProxyPort);
        Assert.True(s.SetSystemProxy);
        Assert.True(s.MinimiseToTray);
        Assert.False(s.StartWithWindows);
        Assert.False(s.ConnectOnLaunch);
        Assert.False(s.SplitTunnelOwnRegion);        // everything through the tunnel
        Assert.False(s.DisableTimeouts);
        Assert.Equal(AppTheme.System, s.Theme);
        Assert.Equal(AppSettings.DefaultBypassList, s.ProxyBypassList);
    }

    [Fact]
    public void The_default_bypass_list_covers_loopback_and_the_private_ranges()
    {
        var list = AppSettings.DefaultBypassList;

        Assert.Contains("<local>", list);
        Assert.Contains("10.*", list);
        Assert.Contains("192.168.*", list);
        Assert.Contains("169.254.*", list);

        // Every RFC1918 172.16/12 subnet, spelled out the way WinINet needs.
        for (var i = 16; i <= 31; i++) Assert.Contains($"172.{i}.*", list);
    }

    // ------------------------------------------------------------ round trips

    [Fact]
    public void Everything_survives_a_save_and_a_load()
    {
        var original = new AppSettings
        {
            EgressRegion = "DE",
            LimitTunnelProtocols = { "OSSH", "QUIC-OSSH" },
            LocalHttpProxyPort = 8080,
            LocalSocksProxyPort = 1080,
            UpstreamProxyUrl = "http://user:pass@host:8080",
            DisableTimeouts = true,
            SplitTunnelOwnRegion = true,
            SetSystemProxy = false,
            ProxyBypassList = "<local>;example.invalid",
            StartWithWindows = true,
            ConnectOnLaunch = true,
            StartMinimised = true,
            MinimiseToTray = false,
            Theme = AppTheme.Dark,
            WindowWidth = 1200,
            WindowHeight = 800,
            WindowLeft = 40,
            WindowTop = 50,
        };

        original.SaveTo(Path());
        var loaded = AppSettings.LoadFrom(Path());

        Assert.Equal("DE", loaded.EgressRegion);
        Assert.Equal(new[] { "OSSH", "QUIC-OSSH" }, loaded.LimitTunnelProtocols);
        Assert.Equal(8080, loaded.LocalHttpProxyPort);
        Assert.Equal(1080, loaded.LocalSocksProxyPort);
        Assert.Equal("http://user:pass@host:8080", loaded.UpstreamProxyUrl);
        Assert.True(loaded.DisableTimeouts);
        Assert.True(loaded.SplitTunnelOwnRegion);
        Assert.False(loaded.SetSystemProxy);
        Assert.Equal("<local>;example.invalid", loaded.ProxyBypassList);
        Assert.True(loaded.StartWithWindows);
        Assert.True(loaded.ConnectOnLaunch);
        Assert.True(loaded.StartMinimised);
        Assert.False(loaded.MinimiseToTray);
        Assert.Equal(AppTheme.Dark, loaded.Theme);
        Assert.Equal(1200, loaded.WindowWidth);
        Assert.Equal(800, loaded.WindowHeight);
        Assert.Equal(40, loaded.WindowLeft);
        Assert.Equal(50, loaded.WindowTop);
    }

    [Fact]
    public void Saving_creates_the_directory_and_leaves_no_temporary_file_behind()
    {
        var nested = System.IO.Path.Combine(_dir, "a", "b", "settings.json");

        new AppSettings().SaveTo(nested);

        Assert.True(File.Exists(nested));
        Assert.False(File.Exists(nested + ".tmp"));
    }

    [Fact]
    public void An_absent_file_yields_defaults()
    {
        var loaded = AppSettings.LoadFrom(Path("never-written.json"));

        Assert.Equal(AppSettings.DefaultBypassList, loaded.ProxyBypassList);
        Assert.True(loaded.SetSystemProxy);
    }

    [Theory]
    [InlineData("")]
    [InlineData("{ this is not json")]
    [InlineData("[]")]
    [InlineData("null")]
    public void A_damaged_file_yields_defaults_instead_of_a_crash(string contents)
    {
        // Losing settings is an inconvenience. Failing to start is not.
        File.WriteAllText(Path(), contents);

        var loaded = AppSettings.LoadFrom(Path());

        Assert.True(loaded.SetSystemProxy);
        Assert.Equal(AppTheme.System, loaded.Theme);
    }

    [Fact]
    public void Unknown_fields_from_a_newer_version_are_ignored()
    {
        File.WriteAllText(Path(), """{"EgressRegion":"NL","SomethingFromTheFuture":42}""");

        Assert.Equal("NL", AppSettings.LoadFrom(Path()).EgressRegion);
    }

    [Fact]
    public void A_partial_file_keeps_the_defaults_for_what_it_omits()
    {
        File.WriteAllText(Path(), """{"Theme":2}""");

        var loaded = AppSettings.LoadFrom(Path());

        Assert.Equal(AppTheme.Dark, loaded.Theme);
        Assert.True(loaded.MinimiseToTray);
        Assert.Equal(AppSettings.DefaultBypassList, loaded.ProxyBypassList);
    }

    [Fact]
    public void Saving_twice_replaces_rather_than_appends()
    {
        var s = new AppSettings { EgressRegion = "DE" };
        s.SaveTo(Path());

        s.EgressRegion = "NL";
        s.SaveTo(Path());

        Assert.Equal("NL", AppSettings.LoadFrom(Path()).EgressRegion);
    }
}
