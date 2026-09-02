namespace NextVpn.Core;

/// <summary>
/// A selectable exit country. Kept as a plain class with settable properties
/// because the XAML type provider generates setters for every x:DataType it sees.
/// </summary>
public sealed class RegionInfo
{
    public RegionInfo() { }

    public RegionInfo(string code, string name)
    {
        Code = code;
        Name = name;
    }

    public string Code { get; set; } = "";
    public string Name { get; set; } = "";

    /// <summary>The pseudo-region meaning "let the engine pick the fastest exit".</summary>
    public static RegionInfo Best => new("", "Best performance");

    public bool IsBest => Code.Length == 0;
    public bool IsCountry => Code.Length > 0;
    public string Display => IsBest ? Name : $"{Name} ({Code})";
}

public static class Regions
{
    // The engine reports egress regions as ISO-3166-1 alpha-2 codes via the
    // AvailableEgressRegions notice. Unknown codes fall back to the raw code
    // plus a generated flag, so a new region never renders as blank.
    private static readonly Dictionary<string, string> Names = new(StringComparer.OrdinalIgnoreCase)
    {
        ["AE"] = "United Arab Emirates",
        ["AM"] = "Armenia",       ["AR"] = "Argentina",     ["AT"] = "Austria",
        ["AU"] = "Australia",     ["BE"] = "Belgium",       ["BG"] = "Bulgaria",
        ["BR"] = "Brazil",        ["BY"] = "Belarus",       ["CA"] = "Canada",
        ["CH"] = "Switzerland",   ["CL"] = "Chile",         ["CN"] = "China",
        ["CZ"] = "Czechia",       ["DE"] = "Germany",       ["DK"] = "Denmark",
        ["EE"] = "Estonia",       ["ES"] = "Spain",         ["FI"] = "Finland",
        ["FR"] = "France",        ["GB"] = "United Kingdom",["GE"] = "Georgia",
        ["HK"] = "Hong Kong",     ["HU"] = "Hungary",       ["ID"] = "Indonesia",
        ["IE"] = "Ireland",       ["IL"] = "Israel",        ["IN"] = "India",
        ["IR"] = "Iran",          ["IS"] = "Iceland",       ["IT"] = "Italy",
        ["JP"] = "Japan",         ["KR"] = "South Korea",   ["KZ"] = "Kazakhstan",
        ["LT"] = "Lithuania",     ["LV"] = "Latvia",        ["MD"] = "Moldova",
        ["MX"] = "Mexico",        ["MY"] = "Malaysia",      ["NL"] = "Netherlands",
        ["NO"] = "Norway",        ["NZ"] = "New Zealand",   ["PL"] = "Poland",
        ["PT"] = "Portugal",      ["RO"] = "Romania",       ["RS"] = "Serbia",
        ["RU"] = "Russia",        ["SE"] = "Sweden",        ["SG"] = "Singapore",
        ["SK"] = "Slovakia",      ["TM"] = "Turkmenistan",  ["TR"] = "Turkiye",
        ["UA"] = "Ukraine",       ["US"] = "United States", ["UZ"] = "Uzbekistan",
        ["ZA"] = "South Africa",
    };

    public static string NameOf(string code) =>
        Names.TryGetValue(code, out var n) ? n : code.ToUpperInvariant();

    // Deliberately no flag emoji: Windows ships no glyphs for regional indicator
    // pairs, so they render as bare letters. The UI draws a country-code badge instead.

    public static RegionInfo Describe(string code) =>
        string.IsNullOrEmpty(code)
            ? RegionInfo.Best
            : new RegionInfo(code.ToUpperInvariant(), NameOf(code));
}

/// <summary>
/// Tunnel protocols the engine can be limited to. Names must match the engine's
/// LimitTunnelProtocols vocabulary exactly.
/// </summary>
public sealed record TunnelProtocol(string Id, string Name, string Description)
{
    public static readonly IReadOnlyList<TunnelProtocol> All = new[]
    {
        new TunnelProtocol("OSSH", "OSSH",
            "Obfuscated SSH. Fastest, works on most networks."),
        new TunnelProtocol("SSH", "SSH",
            "Plain SSH. Lowest overhead, most easily fingerprinted."),
        new TunnelProtocol("QUIC-OSSH", "QUIC",
            "UDP based. Good on lossy or mobile links."),
        new TunnelProtocol("TLS-OSSH", "TLS",
            "Wrapped in TLS so it resembles ordinary HTTPS."),
        new TunnelProtocol("UNFRONTED-MEEK-HTTPS-OSSH", "Meek HTTPS",
            "HTTPS-shaped transport for restrictive networks."),
        new TunnelProtocol("FRONTED-MEEK-OSSH", "Meek (fronted)",
            "Routes via a CDN. Slower but very hard to block."),
        new TunnelProtocol("INPROXY-WEBRTC-OSSH", "In-proxy WebRTC",
            "Peer-assisted WebRTC relay. Best under heavy censorship."),
        new TunnelProtocol("CONJURE-OSSH", "Conjure",
            "Refraction networking via decoy hosts."),
        new TunnelProtocol("SHADOWSOCKS-OSSH", "Shadowsocks",
            "Shadowsocks-shaped transport."),
    };
}
