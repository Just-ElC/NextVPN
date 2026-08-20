using NextVpn.Core;
using Xunit;

namespace NextVpn.Tests;

/// <summary>
/// The notice stream is the entire interface between this client and the tunnel
/// engine. A parser that throws, or that quietly accepts a malformed line, would
/// take the connection state with it.
/// </summary>
public class NoticeTests
{
    [Fact]
    public void Parses_a_real_notice_line()
    {
        const string line =
            """{"data":{"count":1},"noticeType":"Tunnels","timestamp":"2026-08-18T19:04:11.123456789+03:00"}""";

        Assert.True(Notice.TryParse(line, out var notice));
        Assert.Equal("Tunnels", notice.Type);
        Assert.Equal(1, notice.Int("count"));
        Assert.Equal(line, notice.Raw);
        // Go writes RFC3339 with nanosecond precision, which is finer than a
        // DateTimeOffset carries. It has to parse anyway rather than fall back to now.
        Assert.Equal(new DateOnly(2026, 8, 18), DateOnly.FromDateTime(notice.Timestamp.Date));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("\t")]
    [InlineData("not json at all")]
    [InlineData("{ unterminated")]
    [InlineData("[1,2,3]")]
    [InlineData("\"a bare string\"")]
    [InlineData("42")]
    [InlineData("null")]
    public void Refuses_anything_that_is_not_a_notice_object(string line)
    {
        // The engine also writes plain diagnostics to stderr on occasion. Those must
        // be skipped rather than crash the reader loop.
        Assert.False(Notice.TryParse(line, out _));
    }

    [Theory]
    [InlineData("""{"data":{},"timestamp":"2026-01-01T00:00:00Z"}""")]
    [InlineData("""{"noticeType":"","data":{}}""")]
    public void Refuses_a_line_with_no_notice_type(string line) =>
        Assert.False(Notice.TryParse(line, out _));

    [Fact]
    public void Accepts_a_notice_with_no_data_block()
    {
        Assert.True(Notice.TryParse("""{"noticeType":"Exiting"}""", out var notice));
        Assert.Equal("Exiting", notice.Type);
        Assert.Null(notice.String("anything"));
        Assert.Null(notice.Int("anything"));
        Assert.Empty(notice.StringArray("anything"));
    }

    [Fact]
    public void Falls_back_to_now_when_the_timestamp_is_unusable()
    {
        Assert.True(Notice.TryParse("""{"noticeType":"Info","data":{},"timestamp":"yesterday"}""", out var notice));
        Assert.True((DateTimeOffset.Now - notice.Timestamp).Duration() < TimeSpan.FromMinutes(1));
    }

    [Fact]
    public void Reads_numbers_written_as_numbers_or_as_strings()
    {
        Assert.True(Notice.TryParse("""{"noticeType":"X","data":{"a":57104,"b":"57105","c":true}}""", out var n));

        Assert.Equal(57104, n.Int("a"));
        Assert.Equal(57105, n.Int("b"));
        Assert.Null(n.Int("c"));
        Assert.Null(n.Int("missing"));
    }

    [Fact]
    public void Byte_counters_do_not_overflow_an_int()
    {
        // Five gigabytes in a session is ordinary; int.MaxValue is two.
        Assert.True(Notice.TryParse(
            """{"noticeType":"BytesTransferred","data":{"received":5000000000}}""", out var n));

        Assert.Equal(5_000_000_000L, n.Long("received"));
        Assert.Null(n.Int("received"));
    }

    [Fact]
    public void Reads_the_egress_region_list()
    {
        Assert.True(Notice.TryParse(
            """{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL","US"]}}""", out var n));

        Assert.Equal(new[] { "DE", "NL", "US" }, n.StringArray("regions"));
    }

    [Fact]
    public void An_absent_or_wrongly_typed_array_reads_as_empty()
    {
        Assert.True(Notice.TryParse("""{"noticeType":"X","data":{"regions":"DE"}}""", out var n));
        Assert.Empty(n.StringArray("regions"));
    }

    [Fact]
    public void Message_prefers_the_engines_own_wording()
    {
        Assert.True(Notice.TryParse(
            """{"noticeType":"Warning","data":{"message":"upstream proxy unreachable"}}""", out var n));

        Assert.Equal("upstream proxy unreachable", n.Message);
    }

    [Fact]
    public void Message_falls_back_to_the_data_block_so_a_line_is_never_blank()
    {
        Assert.True(Notice.TryParse("""{"noticeType":"ActiveTunnel","data":{"protocol":"OSSH"}}""", out var n));

        Assert.Contains("OSSH", n.Message);
    }

    [Fact]
    public void Handles_the_notices_this_client_acts_on()
    {
        // One line of each shape the client reacts to, exactly as the engine writes
        // them, so a field rename upstream shows up here rather than in the UI.
        var lines = new[]
        {
            ("""{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}""", NoticeType.ListeningHttpProxyPort),
            ("""{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}""", NoticeType.ListeningSocksProxyPort),
            ("""{"noticeType":"ConnectedServerRegion","data":{"serverRegion":"DE"}}""", NoticeType.ConnectedServerRegion),
            ("""{"noticeType":"ClientRegion","data":{"region":"RU"}}""", NoticeType.ClientRegion),
            ("""{"noticeType":"Homepage","data":{"url":"https://example.invalid/"}}""", NoticeType.Homepage),
            ("""{"noticeType":"ActiveTunnel","data":{"protocol":"INPROXY-WEBRTC-QUIC-OSSH"}}""", NoticeType.ActiveTunnel),
        };

        foreach (var (line, expected) in lines)
        {
            Assert.True(Notice.TryParse(line, out var n), line);
            Assert.Equal(expected, n.Type);
        }
    }
}
