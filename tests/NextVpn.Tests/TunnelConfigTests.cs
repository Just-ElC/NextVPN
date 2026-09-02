using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// The generated engine configuration. Two things matter here: the sponsor and
/// crypto material from the base config has to survive untouched, and every field
/// that would make the engine rewrite files outside its own directory has to be
/// gone whether or not the base config asked for it.
/// </summary>
public class TunnelConfigTests
{
    /// <summary>A base config shaped like the one that ships in engine/.</summary>
    private const string BaseConfig = """
    {
        "PropagationChannelId": "FFFFFFFFFFFFFFFF",
        "SponsorId": "0000000000000000",
        "RemoteServerListUrl": "https://example.invalid/list",
        "RemoteServerListSignaturePublicKey": "abc123",
        "AdditionalParameters": "opaque-blob",
        "EnableUpgradeDownload": true,
        "UpgradeDownloadUrl": "https://example.invalid/upgrade",
        "UpgradeDownloadURLs": ["https://example.invalid/upgrade"],
        "UpgradeDownloadFilename": "psiphon3.exe.upgrade",
        "UpgradeDownloadClientVersionHeader": "x-amz-meta-psiphon-client-version",
        "MigrateDataStoreDirectory": "C:\\Users\\Someone\\AppData\\Roaming\\Psiphon3",
        "MigrateObfuscatedServerListDownloadDirectory": "C:\\Users\\Someone\\AppData\\Roaming\\Psiphon3",
        "MigrateRemoteServerListDownloadFilename": "C:\\Users\\Someone\\remote_server_list",
        "MigrateUpgradeDownloadFilename": "C:\\Users\\Someone\\psiphon3.exe.upgrade",
        "LimitTunnelProtocols": ["FRONTED-MEEK-OSSH"],
        "NetworkLatencyMultiplier": 9.0,
        "EstablishTunnelTimeoutSeconds": 300,
        "SplitTunnelOwnRegion": true
    }
    """;

    private static JsonObject Build(AppSettings settings, string dataRoot = @"C:\data\tunnel") =>
        (JsonObject)JsonNode.Parse(TunnelConfig.Build(BaseConfig, settings, dataRoot))!;

    // ------------------------------------------------------- self-modification

    [Theory]
    [InlineData("UpgradeDownloadURLs")]
    [InlineData("UpgradeDownloadFilename")]
    [InlineData("UpgradeDownloadClientVersionHeader")]
    [InlineData("MigrateDataStoreDirectory")]
    [InlineData("MigrateObfuscatedServerListDownloadDirectory")]
    [InlineData("MigrateRemoteServerListDownloadFilename")]
    [InlineData("MigrateUpgradeDownloadFilename")]
    public void Fields_that_rewrite_files_outside_our_own_directory_are_stripped(string field)
    {
        // This is the promise the whole project is built on: nothing downloads a
        // replacement binary and nothing writes outside the application directory.
        Assert.False(Build(new AppSettings()).ContainsKey(field), field);
    }

    [Fact]
    public void Upgrade_download_is_forced_off_even_when_the_base_config_enables_it()
    {
        Assert.False((bool)Build(new AppSettings())["EnableUpgradeDownload"]!);
    }

    // ------------------------------------------------------------ pass-through

    [Theory]
    [InlineData("PropagationChannelId", "FFFFFFFFFFFFFFFF")]
    [InlineData("SponsorId", "0000000000000000")]
    [InlineData("RemoteServerListSignaturePublicKey", "abc123")]
    [InlineData("AdditionalParameters", "opaque-blob")]
    [InlineData("RemoteServerListUrl", "https://example.invalid/list")]
    public void Sponsor_and_crypto_material_is_passed_through_untouched(string field, string expected)
    {
        Assert.Equal(expected, (string)Build(new AppSettings())[field]!);
    }

    // ------------------------------------------------------------- our fields

    [Fact]
    public void Exit_region_comes_from_the_settings()
    {
        Assert.Equal("DE", (string)Build(new AppSettings { EgressRegion = "DE" })["EgressRegion"]!);
    }

    [Fact]
    public void Best_performance_is_expressed_as_an_empty_region()
    {
        // The engine reads an empty EgressRegion as "anywhere", so the field is
        // always written rather than omitted.
        var config = Build(new AppSettings { EgressRegion = "" });
        Assert.True(config.ContainsKey("EgressRegion"));
        Assert.Equal("", (string)config["EgressRegion"]!);
    }

    [Fact]
    public void Local_proxy_ports_are_written_even_when_zero()
    {
        // Zero is meaningful: it tells the engine to pick a free port.
        var config = Build(new AppSettings { LocalHttpProxyPort = 0, LocalSocksProxyPort = 1080 });

        Assert.Equal(0, (int)config["LocalHttpProxyPort"]!);
        Assert.Equal(1080, (int)config["LocalSocksProxyPort"]!);
    }

    [Fact]
    public void The_data_directory_is_the_one_we_were_given()
    {
        Assert.Equal(@"C:\somewhere\else",
            (string)Build(new AppSettings(), @"C:\somewhere\else")["DataRootDirectory"]!);
    }

    [Fact]
    public void Chosen_transports_replace_whatever_the_base_config_listed()
    {
        var settings = new AppSettings { LimitTunnelProtocols = { "OSSH", "QUIC-OSSH" } };

        var protocols = (JsonArray)Build(settings)["LimitTunnelProtocols"]!;

        Assert.Equal(new[] { "OSSH", "QUIC-OSSH" }, protocols.Select(p => (string)p!));
    }

    [Fact]
    public void No_chosen_transports_means_the_engine_is_left_free_to_choose()
    {
        // The base config restricts protocols; an empty selection has to remove that
        // restriction rather than silently inherit it.
        Assert.False(Build(new AppSettings()).ContainsKey("LimitTunnelProtocols"));
    }

    [Fact]
    public void Split_tunnelling_is_removed_when_it_is_off()
    {
        Assert.False(Build(new AppSettings { SplitTunnelOwnRegion = false }).ContainsKey("SplitTunnelOwnRegion"));
        Assert.True((bool)Build(new AppSettings { SplitTunnelOwnRegion = true })["SplitTunnelOwnRegion"]!);
    }

    [Fact]
    public void Relaxed_timeouts_set_both_knobs_together()
    {
        var config = Build(new AppSettings { DisableTimeouts = true });

        Assert.Equal(3.0, (double)config["NetworkLatencyMultiplier"]!);
        Assert.Equal(0, (int)config["EstablishTunnelTimeoutSeconds"]!);
    }

    [Fact]
    public void Normal_timeouts_clear_the_ones_the_base_config_set()
    {
        var config = Build(new AppSettings { DisableTimeouts = false });

        Assert.False(config.ContainsKey("NetworkLatencyMultiplier"));
        Assert.False(config.ContainsKey("EstablishTunnelTimeoutSeconds"));
    }

    [Fact]
    public void Upstream_proxy_is_always_written_so_clearing_it_takes_effect()
    {
        Assert.Equal("http://user:pass@host:8080",
            (string)Build(new AppSettings { UpstreamProxyUrl = "http://user:pass@host:8080" })["UpstreamProxyUrl"]!);

        Assert.Equal("", (string)Build(new AppSettings())["UpstreamProxyUrl"]!);
    }

    [Theory]
    [InlineData("EmitBytesTransferred")]
    [InlineData("EmitDiagnosticNotices")]
    [InlineData("EmitDiagnosticNetworkParameters")]
    [InlineData("EmitServerAlerts")]
    public void Telemetry_the_interface_depends_on_is_switched_on(string field)
    {
        Assert.True((bool)Build(new AppSettings())[field]!, field);
    }

    [Fact]
    public void Client_platform_matches_the_shape_the_engine_expects()
    {
        var platform = (string)Build(new AppSettings())["ClientPlatform"]!;

        // Windows_<version>_<product>: the engine splits on underscores, so neither
        // spaces nor extra underscores are allowed in the parts.
        var parts = platform.Split('_');
        Assert.Equal(3, parts.Length);
        Assert.Equal("Windows", parts[0]);
        Assert.Equal("NextVPN", parts[2]);
        Assert.DoesNotContain(" ", platform);
    }

    // ------------------------------------------------------------------ shape

    [Fact]
    public void Output_is_one_line_of_json()
    {
        var json = TunnelConfig.Build(BaseConfig, new AppSettings(), @"C:\data");

        Assert.DoesNotContain("\n", json);
        Assert.NotNull(JsonNode.Parse(json));
    }

    [Theory]
    [InlineData("[]")]
    [InlineData("\"text\"")]
    [InlineData("null")]
    public void A_base_config_that_is_not_an_object_is_rejected(string json) =>
        Assert.Throws<InvalidDataException>(() => TunnelConfig.Build(json, new AppSettings(), @"C:\data"));

    [Fact]
    public void A_corrupt_base_config_is_reported_rather_than_thrown_raw()
    {
        var error = Assert.Throws<InvalidDataException>(
            () => TunnelConfig.Build("{ not json", new AppSettings(), @"C:\data"));

        Assert.IsAssignableFrom<JsonException>(error.InnerException);
    }

    // ------------------------------------------------------------------ on disk

    [Fact]
    public void The_written_file_has_no_byte_order_mark()
    {
        // The engine JSON parser treats a BOM as content and refuses to start with
        // "invalid character looking for beginning of value". This is the guard.
        var dir = Directory.CreateTempSubdirectory("nextvpn-config");
        try
        {
            var path = TunnelConfig.WriteTo(
                Path.Combine(dir.FullName, "runtime.config"), BaseConfig, new AppSettings(), dir.FullName);

            var bytes = File.ReadAllBytes(path);

            Assert.NotEqual(new byte[] { 0xEF, 0xBB, 0xBF }, bytes.Take(3).ToArray());
            Assert.Equal((byte)'{', bytes[0]);
            Assert.NotNull(JsonNode.Parse(Encoding.UTF8.GetString(bytes)));
        }
        finally
        {
            dir.Delete(recursive: true);
        }
    }

    [Fact]
    public void A_base_config_that_has_a_byte_order_mark_is_still_accepted()
    {
        // The file in engine/ is not ours to reformat, so reading has to tolerate one.
        var withBom = "\uFEFF" + BaseConfig;

        Assert.Equal("", (string)((JsonObject)JsonNode.Parse(
            TunnelConfig.Build(withBom, new AppSettings(), @"C:\data"))!)["EgressRegion"]!);
    }

    [Fact]
    public void The_written_directory_is_created_if_it_is_missing()
    {
        var dir = Path.Combine(Path.GetTempPath(), "nextvpn-" + Guid.NewGuid().ToString("N"));
        try
        {
            var path = TunnelConfig.WriteTo(
                Path.Combine(dir, "nested", "runtime.config"), BaseConfig, new AppSettings(), dir);

            Assert.True(File.Exists(path));
        }
        finally
        {
            if (Directory.Exists(dir)) Directory.Delete(dir, recursive: true);
        }
    }
}
