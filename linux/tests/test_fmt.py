"""
Every number on the connection panel goes through here, so the rounding rules
are pinned down rather than rediscovered by looking at a running tunnel.
"""

import math
import unittest
from datetime import timedelta

from nextvpn.core import fmt


class FormatTests(unittest.TestCase):
    def test_bytes_uses_binary_units(self):
        cases = [
            (0, "0 B"), (-1, "0 B"), (-(2**63), "0 B"), (1, "1 B"), (999, "999 B"),
            (1023, "1023 B"), (1024, "1 KB"), (1536, "1.5 KB"), (1126, "1.1 KB"),
            (1048576, "1 MB"), (1073741824, "1 GB"), (1099511627776, "1 TB"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, fmt.bytes_(value))

    def test_bytes_stops_at_terabytes_rather_than_inventing_a_unit(self):
        self.assertEqual("1024 TB", fmt.bytes_(1024 ** 5))

    def test_rate_uses_per_second_units(self):
        cases = [
            (0, "0 B/s"), (0.99, "0 B/s"), (-500, "0 B/s"), (1, "1 B/s"),
            (1023.9, "1023 B/s"), (1024, "1 KB/s"), (2560, "2.5 KB/s"),
            (5368709120, "5 GB/s"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, fmt.rate(value))

    def test_rate_survives_a_division_that_produced_nothing(self):
        self.assertEqual("0 B/s", fmt.rate(math.nan))

    def test_duration_shows_the_placeholder_when_there_is_no_session(self):
        for seconds in (0, -5):
            self.assertEqual(fmt.EMPTY, fmt.duration(timedelta(seconds=seconds)))

    def test_duration_grows_a_field_only_at_the_first_hour(self):
        cases = [(5, "00:05"), (65, "01:05"), (3599, "59:59"), (3600, "1:00:00"),
                 (3661, "1:01:01"), (90062, "25:01:02")]
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(expected, fmt.duration(timedelta(seconds=seconds)))

    def test_country_pairs_the_name_with_the_code(self):
        cases = [(None, "—"), ("", "—"), ("de", "Germany (DE)"), ("DE", "Germany (DE)"),
                 ("gb", "United Kingdom (GB)")]
        for code, expected in cases:
            with self.subTest(code=code):
                self.assertEqual(expected, fmt.country(code))

    def test_country_falls_back_to_the_code_when_the_region_is_unknown(self):
        self.assertEqual("ZZ (ZZ)", fmt.country("zz"))

    def test_ports_names_only_the_listeners_that_are_open(self):
        cases = [(0, 0, "—"), (8080, 0, "HTTP 8080"), (0, 1080, "SOCKS 1080"),
                 (8080, 1080, "HTTP 8080 · SOCKS 1080")]
        for http, socks, expected in cases:
            with self.subTest(http=http, socks=socks):
                self.assertEqual(expected, fmt.ports(http, socks))


if __name__ == "__main__":
    unittest.main()
