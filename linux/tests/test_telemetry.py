"""
The session state machine, driven by the same notice lines the engine emits.
This is what decides whether the application believes it is connected, so it is
exercised with recorded streams rather than by watching a real tunnel.
"""

import unittest

from nextvpn.core.notice import Notice
from nextvpn.core.telemetry import TelemetrySignal, TunnelTelemetry


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def N(line):
    n = Notice.parse(line)
    assert n is not None, line
    return n


def feed(t, *lines):
    last = TelemetrySignal.NONE
    for line in lines:
        last = t.apply(N(line))
    return last


class TunnelTelemetryTests(unittest.TestCase):
    def test_listener_ports_are_picked_up_separately(self):
        t = TunnelTelemetry()
        self.assertEqual(TelemetrySignal.PORTS_CHANGED,
                         t.apply(N('{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}')))
        self.assertEqual(TelemetrySignal.PORTS_CHANGED,
                         t.apply(N('{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}')))
        self.assertEqual(57104, t.http_port)
        self.assertEqual(57105, t.socks_port)

    def test_the_first_tunnel_starts_the_session_clock(self):
        t = TunnelTelemetry()
        self.assertEqual(TelemetrySignal.TUNNEL_UP, t.apply(N('{"noticeType":"Tunnels","data":{"count":1}}')))
        self.assertIsNotNone(t.stats.connected_at)
        self.assertEqual(1, t.tunnel_count)

    def test_a_second_tunnel_does_not_restart_the_clock(self):
        clock = Clock()
        t = TunnelTelemetry(clock)
        feed(t, '{"noticeType":"Tunnels","data":{"count":1}}')
        started = t.stats.connected_at
        clock.now += 30
        feed(t, '{"noticeType":"Tunnels","data":{"count":2}}')
        self.assertEqual(started, t.stats.connected_at)
        self.assertEqual(30, t.stats.uptime.total_seconds())

    def test_losing_the_last_tunnel_stops_the_clock_and_reports_it(self):
        t = TunnelTelemetry()
        feed(t, '{"noticeType":"Tunnels","data":{"count":1}}')
        self.assertEqual(TelemetrySignal.TUNNEL_DOWN, t.apply(N('{"noticeType":"Tunnels","data":{"count":0}}')))
        self.assertIsNone(t.stats.connected_at)
        self.assertEqual(0, t.tunnel_count)

    def test_a_zero_count_before_anything_connected_is_not_a_disconnection(self):
        t = TunnelTelemetry()
        self.assertEqual(TelemetrySignal.NONE, t.apply(N('{"noticeType":"Tunnels","data":{"count":0}}')))
        self.assertIsNone(t.stats.connected_at)

    def test_a_missing_or_negative_count_is_treated_as_no_tunnel(self):
        t = TunnelTelemetry()
        self.assertEqual(TelemetrySignal.NONE, t.apply(N('{"noticeType":"Tunnels","data":{}}')))
        self.assertEqual(TelemetrySignal.NONE, t.apply(N('{"noticeType":"Tunnels","data":{"count":-1}}')))
        self.assertEqual(0, t.tunnel_count)

    def test_byte_counters_accumulate_across_notices(self):
        t = TunnelTelemetry()
        signal = feed(t, '{"noticeType":"BytesTransferred","data":{"sent":100,"received":900}}',
                      '{"noticeType":"BytesTransferred","data":{"sent":50,"received":1000}}')
        self.assertEqual(TelemetrySignal.STATS_CHANGED, signal)
        self.assertEqual(150, t.stats.bytes_sent)
        self.assertEqual(1900, t.stats.bytes_received)

    def test_a_nonsense_byte_delta_cannot_run_the_totals_backwards(self):
        t = TunnelTelemetry()
        feed(t, '{"noticeType":"BytesTransferred","data":{"sent":100,"received":100}}',
             '{"noticeType":"BytesTransferred","data":{"sent":-500,"received":-500}}')
        self.assertEqual(100, t.stats.bytes_sent)
        self.assertEqual(100, t.stats.bytes_received)

    def test_session_details_are_recorded_without_disturbing_the_connection_state(self):
        t = TunnelTelemetry()
        signal = feed(t,
                      '{"noticeType":"ActiveTunnel","data":{"protocol":"INPROXY-WEBRTC-QUIC-OSSH"}}',
                      '{"noticeType":"ConnectedServerRegion","data":{"serverRegion":"DE"}}',
                      '{"noticeType":"ClientRegion","data":{"region":"RU"}}',
                      '{"noticeType":"Homepage","data":{"url":"https://example.invalid/"}}')
        self.assertEqual(TelemetrySignal.NONE, signal)
        self.assertEqual("INPROXY-WEBRTC-QUIC-OSSH", t.active_protocol)
        self.assertEqual("DE", t.connected_region)
        self.assertEqual("RU", t.client_region)
        self.assertEqual("https://example.invalid/", t.homepage_url)

    def test_an_available_upgrade_is_recorded_and_nothing_else_happens(self):
        t = TunnelTelemetry()
        self.assertEqual(TelemetrySignal.NONE,
                         t.apply(N('{"noticeType":"ClientUpgradeAvailable","data":{"version":"181"}}')))
        self.assertEqual("181", t.upgrade_available_version)

    def test_the_egress_region_list_is_replaced_wholesale(self):
        t = TunnelTelemetry()
        signal = feed(t, '{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL"]}}',
                      '{"noticeType":"AvailableEgressRegions","data":{"regions":["US"]}}')
        self.assertEqual(TelemetrySignal.REGIONS_CHANGED, signal)
        self.assertEqual(["US"], t.available_regions)

    def test_an_unrecognised_notice_changes_nothing(self):
        t = TunnelTelemetry()
        self.assertEqual(TelemetrySignal.NONE,
                         t.apply(N('{"noticeType":"SomethingNewUpstream","data":{"whatever":1}}')))

    def test_every_type_apply_acts_on_is_forwarded_by_the_reader(self):
        # A tracked type the reader filtered out would never reach apply().
        for kind in ("ListeningSocksProxyPort", "ListeningHttpProxyPort", "Tunnels", "ActiveTunnel",
                     "ConnectedServerRegion", "ClientRegion", "AvailableEgressRegions", "Homepage",
                     "ClientUpgradeAvailable", "BytesTransferred"):
            self.assertIn(kind, TunnelTelemetry.TRACKED_TYPES)

    def test_starting_a_new_run_clears_the_session_but_keeps_the_region_list(self):
        t = TunnelTelemetry()
        feed(t, '{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL"]}}',
             '{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}',
             '{"noticeType":"Tunnels","data":{"count":1}}',
             '{"noticeType":"BytesTransferred","data":{"sent":1,"received":2}}',
             '{"noticeType":"ActiveTunnel","data":{"protocol":"OSSH"}}')
        t.reset()
        self.assertEqual(0, t.http_port)
        self.assertEqual(0, t.tunnel_count)
        self.assertEqual(0, t.stats.bytes_sent)
        self.assertEqual(0, t.stats.bytes_received)
        self.assertIsNone(t.stats.connected_at)
        self.assertIsNone(t.active_protocol)
        self.assertEqual(["DE", "NL"], t.available_regions)

    def test_when_the_engine_exits_the_listeners_go_but_the_totals_stay(self):
        t = TunnelTelemetry()
        feed(t, '{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}',
             '{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}',
             '{"noticeType":"Tunnels","data":{"count":1}}',
             '{"noticeType":"BytesTransferred","data":{"sent":10,"received":20}}')
        t.clear_listeners()
        self.assertEqual(0, t.http_port)
        self.assertEqual(0, t.socks_port)
        self.assertIsNone(t.stats.connected_at)
        self.assertEqual(10, t.stats.bytes_sent)
        self.assertEqual(20, t.stats.bytes_received)

    def test_a_full_connect_sequence_ends_up_connected(self):
        t = TunnelTelemetry()
        feed(t,
             '{"noticeType":"ClientRegion","data":{"region":"RU"}}',
             '{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL","US"]}}',
             '{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}',
             '{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}',
             '{"noticeType":"ConnectingServer","data":{"ipAddress":"203.0.113.1"}}',
             '{"noticeType":"ConnectedServer","data":{"ipAddress":"203.0.113.1"}}',
             '{"noticeType":"ActiveTunnel","data":{"protocol":"OSSH"}}',
             '{"noticeType":"ConnectedServerRegion","data":{"serverRegion":"DE"}}',
             '{"noticeType":"Tunnels","data":{"count":1}}',
             '{"noticeType":"BytesTransferred","data":{"sent":512,"received":8192}}')
        self.assertEqual(1, t.tunnel_count)
        self.assertEqual(57104, t.http_port)
        self.assertEqual(57105, t.socks_port)
        self.assertEqual("DE", t.connected_region)
        self.assertEqual("RU", t.client_region)
        self.assertEqual("OSSH", t.active_protocol)
        self.assertEqual(3, len(t.available_regions))
        self.assertEqual(8192, t.stats.bytes_received)
        self.assertIsNotNone(t.stats.connected_at)
        self.assertGreaterEqual(t.stats.uptime.total_seconds(), 0)

    def test_a_mid_session_redial_keeps_the_totals_and_only_pauses_the_clock(self):
        t = TunnelTelemetry()
        feed(t, '{"noticeType":"Tunnels","data":{"count":1}}',
             '{"noticeType":"BytesTransferred","data":{"sent":10,"received":20}}',
             '{"noticeType":"Tunnels","data":{"count":0}}')
        self.assertIsNone(t.stats.connected_at)
        self.assertEqual(20, t.stats.bytes_received)
        feed(t, '{"noticeType":"Tunnels","data":{"count":1}}')
        self.assertIsNotNone(t.stats.connected_at)
        self.assertEqual(20, t.stats.bytes_received)


if __name__ == "__main__":
    unittest.main()
