"""
The notice stream is the entire interface between this client and the tunnel
engine. A parser that throws, or that quietly accepts a malformed line, would
take the connection state with it.
"""

import unittest
from datetime import date, datetime, timezone

from nextvpn.core.notice import Notice, NoticeType
from nextvpn.core.policy import NoticeLevel, NoticePolicy


class NoticeTests(unittest.TestCase):
    def parse(self, line):
        n = Notice.parse(line)
        self.assertIsNotNone(n, line)
        return n

    def test_parses_a_real_notice_line(self):
        line = '{"data":{"count":1},"noticeType":"Tunnels","timestamp":"2026-08-18T19:04:11.123456789+03:00"}'
        n = self.parse(line)
        self.assertEqual("Tunnels", n.type)
        self.assertEqual(1, n.int("count"))
        self.assertEqual(line, n.raw)
        # Go writes nanoseconds, finer than a datetime carries. It must parse anyway.
        self.assertEqual(date(2026, 8, 18), n.timestamp.date())

    def test_parses_the_utc_shape_the_linux_engine_writes(self):
        n = self.parse('{"data":{"port":36249},"noticeType":"ListeningHttpProxyPort","timestamp":"2026-10-18T13:37:35.697Z"}')
        self.assertEqual(datetime(2026, 10, 18, 13, 37, 35, 697000, tzinfo=timezone.utc), n.timestamp)

    def test_refuses_anything_that_is_not_a_notice_object(self):
        # The engine also writes plain diagnostics, and Go panics, to stderr.
        for line in ("", "   ", "\t", "not json at all", "{ unterminated", "[1,2,3]",
                     '"a bare string"', "42", "null", "panic: runtime error"):
            with self.subTest(line=line):
                self.assertIsNone(Notice.parse(line))

    def test_refuses_a_line_with_no_notice_type(self):
        for line in ('{"data":{},"timestamp":"2026-01-01T00:00:00Z"}', '{"noticeType":"","data":{}}',
                     '{"noticeType":5}'):
            self.assertIsNone(Notice.parse(line))

    def test_accepts_a_notice_with_no_data_block(self):
        n = self.parse('{"noticeType":"Exiting"}')
        self.assertEqual("Exiting", n.type)
        self.assertIsNone(n.string("anything"))
        self.assertIsNone(n.int("anything"))
        self.assertEqual([], n.string_array("anything"))

    def test_falls_back_to_now_when_the_timestamp_is_unusable(self):
        n = self.parse('{"noticeType":"Info","data":{},"timestamp":"yesterday"}')
        self.assertLess(abs((datetime.now(timezone.utc) - n.timestamp).total_seconds()), 60)

    def test_reads_numbers_written_as_numbers_or_as_strings(self):
        n = self.parse('{"noticeType":"X","data":{"a":57104,"b":"57105","c":true,"d":1.5}}')
        self.assertEqual(57104, n.int("a"))
        self.assertEqual(57105, n.int("b"))
        self.assertIsNone(n.int("c"))
        self.assertIsNone(n.int("d"))
        self.assertIsNone(n.int("missing"))

    def test_byte_counters_do_not_overflow_an_int(self):
        n = self.parse('{"noticeType":"BytesTransferred","data":{"received":5000000000}}')
        self.assertEqual(5_000_000_000, n.long("received"))
        self.assertIsNone(n.int("received"))

    def test_reads_the_egress_region_list(self):
        n = self.parse('{"noticeType":"AvailableEgressRegions","data":{"regions":["DE","NL","US"]}}')
        self.assertEqual(["DE", "NL", "US"], n.string_array("regions"))

    def test_an_absent_or_wrongly_typed_array_reads_as_empty(self):
        n = self.parse('{"noticeType":"X","data":{"regions":"DE"}}')
        self.assertEqual([], n.string_array("regions"))

    def test_message_prefers_the_engines_own_wording(self):
        n = self.parse('{"noticeType":"Warning","data":{"message":"upstream proxy unreachable"}}')
        self.assertEqual("upstream proxy unreachable", n.message)

    def test_message_falls_back_to_the_data_block_so_a_line_is_never_blank(self):
        n = self.parse('{"noticeType":"ActiveTunnel","data":{"protocol":"OSSH"}}')
        self.assertIn("OSSH", n.message)

    def test_handles_the_notices_this_client_acts_on(self):
        lines = [
            ('{"noticeType":"ListeningHttpProxyPort","data":{"port":57104}}', NoticeType.LISTENING_HTTP_PROXY_PORT),
            ('{"noticeType":"ListeningSocksProxyPort","data":{"port":57105}}', NoticeType.LISTENING_SOCKS_PROXY_PORT),
            ('{"noticeType":"ConnectedServerRegion","data":{"serverRegion":"DE"}}', NoticeType.CONNECTED_SERVER_REGION),
            ('{"noticeType":"ClientRegion","data":{"region":"RU"}}', NoticeType.CLIENT_REGION),
            ('{"noticeType":"Homepage","data":{"url":"https://example.invalid/"}}', NoticeType.HOMEPAGE),
            ('{"noticeType":"ActiveTunnel","data":{"protocol":"INPROXY-WEBRTC-QUIC-OSSH"}}', NoticeType.ACTIVE_TUNNEL),
        ]
        for line, expected in lines:
            self.assertEqual(expected, self.parse(line).type)


class NoticePolicyTests(unittest.TestCase):
    """
    What reaches the activity log, and what is allowed to wake the main loop.
    The engine emits hundreds of notices per connection attempt.
    """

    def test_severity_follows_the_notice_type(self):
        cases = [(NoticeType.ERROR, NoticeLevel.ERROR), (NoticeType.WARNING, NoticeLevel.WARNING),
                 (NoticeType.INFO, NoticeLevel.INFO), (NoticeType.TUNNELS, NoticeLevel.INFO),
                 ("AnythingElse", NoticeLevel.INFO)]
        for kind, expected in cases:
            self.assertEqual(expected, NoticePolicy.level_of(kind))

    def test_problems_are_always_logged(self):
        for kind in (NoticeType.ERROR, NoticeType.WARNING):
            self.assertTrue(NoticePolicy.should_log(kind, verbose=False))
            self.assertTrue(NoticePolicy.should_log(kind, verbose=True))

    def test_milestones_are_logged_without_turning_diagnostics_on(self):
        for kind in (NoticeType.TUNNELS, NoticeType.CONNECTED_SERVER, NoticeType.ACTIVE_TUNNEL,
                     NoticeType.CONNECTED_SERVER_REGION, NoticeType.CLIENT_REGION,
                     NoticeType.LISTENING_HTTP_PROXY_PORT, NoticeType.LISTENING_SOCKS_PROXY_PORT,
                     NoticeType.HOMEPAGE, NoticeType.SERVER_ALERT, NoticeType.UNTUNNELED,
                     NoticeType.CLIENT_UPGRADE_AVAILABLE, NoticeType.UPSTREAM_PROXY_ERROR):
            with self.subTest(kind=kind):
                self.assertTrue(NoticePolicy.should_log(kind, verbose=False))

    def test_routine_chatter_is_held_back_until_diagnostics_are_on(self):
        for kind in (NoticeType.INFO, NoticeType.CONNECTING_SERVER, NoticeType.TRAFFIC_RATE_LIMITS,
                     "CandidateServers"):
            with self.subTest(kind=kind):
                self.assertFalse(NoticePolicy.should_log(kind, verbose=False))
                self.assertTrue(NoticePolicy.should_log(kind, verbose=True))

    def test_throughput_never_reaches_the_log_unless_it_is_asked_for(self):
        self.assertFalse(NoticePolicy.should_log(NoticeType.BYTES_TRANSFERRED, verbose=False))
        self.assertTrue(NoticePolicy.should_log(NoticeType.BYTES_TRANSFERRED, verbose=True))

    def test_throughput_still_reaches_the_graph(self):
        self.assertTrue(NoticePolicy.changes_visible_state(NoticeType.BYTES_TRANSFERRED))
        self.assertTrue(NoticePolicy.needs_ui(NoticeType.BYTES_TRANSFERRED, verbose=False))

    def test_notices_that_move_something_visible_are_marked_as_such(self):
        for kind in (NoticeType.CLIENT_REGION, NoticeType.ACTIVE_TUNNEL, NoticeType.CONNECTED_SERVER_REGION,
                     NoticeType.LISTENING_HTTP_PROXY_PORT, NoticeType.LISTENING_SOCKS_PROXY_PORT):
            self.assertTrue(NoticePolicy.changes_visible_state(kind))

    def test_landing_pages_and_upgrade_offers_are_logged_but_never_shown(self):
        for kind in (NoticeType.HOMEPAGE, NoticeType.CLIENT_UPGRADE_AVAILABLE):
            self.assertFalse(NoticePolicy.changes_visible_state(kind))
            self.assertTrue(NoticePolicy.should_log(kind, verbose=False))

    def test_everything_else_stays_off_the_main_loop_by_default(self):
        for kind in (NoticeType.CONNECTING_SERVER, NoticeType.TRAFFIC_RATE_LIMITS, "CandidateServers"):
            self.assertFalse(NoticePolicy.needs_ui(kind, verbose=False))
            self.assertTrue(NoticePolicy.needs_ui(kind, verbose=True))


if __name__ == "__main__":
    unittest.main()
