using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// Every number on the connection panel goes through here, so the rounding rules
/// are pinned down rather than rediscovered by looking at a running tunnel.
/// </summary>
public class FormatTests
{
    [Theory]
    [InlineData(0, "0 B")]
    [InlineData(-1, "0 B")]
    [InlineData(long.MinValue, "0 B")]
    [InlineData(1, "1 B")]
    [InlineData(999, "999 B")]
    [InlineData(1023, "1023 B")]
    [InlineData(1024, "1 KB")]
    [InlineData(1536, "1.5 KB")]
    [InlineData(1126, "1.1 KB")]
    [InlineData(1048576, "1 MB")]
    [InlineData(1073741824, "1 GB")]
    [InlineData(1099511627776, "1 TB")]
    public void Bytes_uses_binary_units(long input, string expected) =>
        Assert.Equal(expected, Format.Bytes(input));

    [Fact]
    public void Bytes_stops_at_terabytes_rather_than_inventing_a_unit()
    {
        // 1024 TB. The unit table ends here, so the number keeps growing instead.
        Assert.Equal("1024 TB", Format.Bytes(1024L * 1024 * 1024 * 1024 * 1024));
    }

    [Theory]
    [InlineData(0, "0 B/s")]
    [InlineData(0.99, "0 B/s")]
    [InlineData(-500, "0 B/s")]
    [InlineData(1, "1 B/s")]
    [InlineData(1023.9, "1023 B/s")]
    [InlineData(1024, "1 KB/s")]
    [InlineData(2560, "2.5 KB/s")]
    [InlineData(5368709120, "5 GB/s")]
    public void Rate_uses_per_second_units(double input, string expected) =>
        Assert.Equal(expected, Format.Rate(input));

    [Fact]
    public void Rate_survives_a_division_that_produced_nothing()
    {
        // A zero-length sampling window would divide by zero upstream; the display
        // must not then show "NaN B/s".
        Assert.Equal("0 B/s", Format.Rate(double.NaN));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-5)]
    public void Duration_shows_the_placeholder_when_there_is_no_session(int seconds) =>
        Assert.Equal(Format.Empty, Format.Duration(TimeSpan.FromSeconds(seconds)));

    [Theory]
    [InlineData(5, "00:05")]
    [InlineData(65, "01:05")]
    [InlineData(3599, "59:59")]
    [InlineData(3600, "1:00:00")]
    [InlineData(3661, "1:01:01")]
    [InlineData(90062, "25:01:02")]
    public void Duration_grows_a_field_only_at_the_first_hour(int seconds, string expected) =>
        Assert.Equal(expected, Format.Duration(TimeSpan.FromSeconds(seconds)));

    [Theory]
    [InlineData(null, "—")]
    [InlineData("", "—")]
    [InlineData("de", "Germany (DE)")]
    [InlineData("DE", "Germany (DE)")]
    [InlineData("gb", "United Kingdom (GB)")]
    public void Country_pairs_the_name_with_the_code(string? code, string expected) =>
        Assert.Equal(expected, Format.Country(code));

    [Fact]
    public void Country_falls_back_to_the_code_when_the_region_is_unknown()
    {
        // The engine can add an egress region this client has never heard of.
        Assert.Equal("ZZ (ZZ)", Format.Country("zz"));
    }

    [Theory]
    [InlineData(0, 0, "—")]
    [InlineData(8080, 0, "HTTP 8080")]
    [InlineData(0, 1080, "SOCKS 1080")]
    [InlineData(8080, 1080, "HTTP 8080 · SOCKS 1080")]
    public void Ports_names_only_the_listeners_that_are_open(int http, int socks, string expected) =>
        Assert.Equal(expected, Format.Ports(http, socks));
}
