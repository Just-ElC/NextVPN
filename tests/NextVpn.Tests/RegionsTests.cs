using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// Exit locations. The engine names them with ISO country codes and can add one
/// this client has never heard of, which must still be selectable.
/// </summary>
public class RegionsTests
{
    [Theory]
    [InlineData("DE", "Germany")]
    [InlineData("de", "Germany")]
    [InlineData("GB", "United Kingdom")]
    [InlineData("US", "United States")]
    [InlineData("TR", "Turkiye")]
    public void Known_codes_get_a_country_name(string code, string expected) =>
        Assert.Equal(expected, Regions.NameOf(code));

    [Fact]
    public void An_unknown_code_renders_as_the_code_rather_than_as_nothing()
    {
        Assert.Equal("ZZ", Regions.NameOf("zz"));
        Assert.Equal("XK", Regions.NameOf("XK"));
    }

    [Fact]
    public void The_empty_code_is_the_let_the_engine_choose_pseudo_region()
    {
        var best = Regions.Describe("");

        Assert.True(best.IsBest);
        Assert.False(best.IsCountry);
        Assert.Equal("", best.Code);
        Assert.Equal("Best performance", best.Name);
        Assert.Equal("Best performance", best.Display);
    }

    [Fact]
    public void A_country_is_described_by_name_and_uppercase_code()
    {
        var region = Regions.Describe("de");

        Assert.False(region.IsBest);
        Assert.True(region.IsCountry);
        Assert.Equal("DE", region.Code);
        Assert.Equal("Germany", region.Name);
        Assert.Equal("Germany (DE)", region.Display);
    }

    [Fact]
    public void An_unknown_country_is_still_a_selectable_region()
    {
        // A new egress region appearing upstream must not render as a blank row.
        var region = Regions.Describe("zz");

        Assert.True(region.IsCountry);
        Assert.Equal("ZZ", region.Code);
        Assert.Equal("ZZ (ZZ)", region.Display);
    }

    [Fact]
    public void Every_transport_the_settings_page_offers_has_a_name_and_a_reason()
    {
        Assert.NotEmpty(TunnelProtocol.All);

        foreach (var p in TunnelProtocol.All)
        {
            Assert.False(string.IsNullOrWhiteSpace(p.Id), p.Name);
            Assert.False(string.IsNullOrWhiteSpace(p.Name), p.Id);
            Assert.False(string.IsNullOrWhiteSpace(p.Description), p.Id);

            // The engine matches LimitTunnelProtocols entries exactly, so a stray
            // space or lowercase letter would silently restrict it to nothing.
            Assert.Equal(p.Id.Trim().ToUpperInvariant(), p.Id);
        }
    }

    [Fact]
    public void Transport_ids_are_unique()
    {
        var ids = TunnelProtocol.All.Select(p => p.Id).ToList();
        Assert.Equal(ids.Count, ids.Distinct().Count());
    }
}
