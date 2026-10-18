"""
Persisted settings. A settings file that cannot be read, or a half-written one,
must never stop the application from starting.
"""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from nextvpn.core.settings import (DEFAULT_BYPASS_LIST, AppSettings, AppTheme, ClientPlatform,
                                   parse_bypass_list)


class AppSettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="nextvpn-settings")
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, name="settings.json"):
        return self.dir / name

    # ------------------------------------------------------------ defaults

    def test_defaults_are_the_safe_ones(self):
        s = AppSettings()
        self.assertEqual("", s.egress_region)            # best performance
        self.assertEqual([], s.limit_tunnel_protocols)   # engine picks the transport
        self.assertEqual(0, s.local_http_proxy_port)     # engine picks a free port
        self.assertEqual(0, s.local_socks_proxy_port)
        self.assertTrue(s.set_system_proxy)
        self.assertTrue(s.minimise_to_tray)
        self.assertFalse(s.start_at_login)
        self.assertFalse(s.connect_on_launch)
        self.assertFalse(s.split_tunnel_own_region)      # everything through the tunnel
        self.assertFalse(s.disable_timeouts)
        self.assertEqual(AppTheme.SYSTEM, s.theme)
        self.assertEqual(DEFAULT_BYPASS_LIST, s.proxy_bypass_list)

    def test_by_default_the_servers_see_the_same_client_as_on_windows(self):
        # The point of the port: the same servers, treated the same way.
        self.assertEqual(ClientPlatform.WINDOWS, AppSettings().client_platform)

    def test_the_default_bypass_list_covers_loopback_and_the_private_ranges(self):
        items = parse_bypass_list(DEFAULT_BYPASS_LIST)
        for expected in ("localhost", "127.0.0.0/8", "::1", "10.0.0.0/8",
                         "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                         "fc00::/7", "fe80::/10"):
            self.assertIn(expected, items)

    def test_bypass_lists_accept_any_separator_and_drop_repeats(self):
        self.assertEqual(["a", "b", "c"], parse_bypass_list("a, b;c\n a  ,,"))
        self.assertEqual([], parse_bypass_list(""))

    # --------------------------------------------------------- round trips

    def test_everything_survives_a_save_and_a_load(self):
        original = AppSettings(
            egress_region="DE",
            limit_tunnel_protocols=["OSSH", "QUIC-OSSH"],
            local_http_proxy_port=8080,
            local_socks_proxy_port=1080,
            upstream_proxy_url="http://user:pass@host:8080",
            disable_timeouts=True,
            split_tunnel_own_region=True,
            client_platform=ClientPlatform.LINUX,
            set_system_proxy=False,
            proxy_bypass_list="localhost, example.invalid",
            start_at_login=True,
            connect_on_launch=True,
            start_minimised=True,
            minimise_to_tray=False,
            theme=AppTheme.DARK,
            window_width=1200,
            window_height=800,
            window_maximised=True,
            known_regions=["DE", "NL"],
        )
        original.save_to(self.path())
        loaded = AppSettings.load_from(self.path())
        self.assertEqual(original, loaded)

    def test_the_file_is_private_to_the_user(self):
        # An upstream proxy URL can carry a password.
        AppSettings(upstream_proxy_url="http://user:secret@host:1").save_to(self.path())
        mode = stat.S_IMODE(os.stat(self.path()).st_mode)
        self.assertEqual(0o600, mode)

    def test_saving_creates_the_directory_and_leaves_no_temporary_file_behind(self):
        nested = self.dir / "a" / "b" / "settings.json"
        AppSettings().save_to(nested)
        self.assertTrue(nested.is_file())
        self.assertFalse(Path(str(nested) + ".tmp").exists())

    def test_an_absent_file_yields_defaults(self):
        loaded = AppSettings.load_from(self.path("never-written.json"))
        self.assertEqual(DEFAULT_BYPASS_LIST, loaded.proxy_bypass_list)
        self.assertTrue(loaded.set_system_proxy)

    def test_a_damaged_file_yields_defaults_instead_of_a_crash(self):
        # Losing settings is an inconvenience. Failing to start is not.
        for contents in ("", "{ this is not json", "[]", "null"):
            with self.subTest(contents=contents):
                self.path().write_text(contents)
                loaded = AppSettings.load_from(self.path())
                self.assertTrue(loaded.set_system_proxy)
                self.assertEqual(AppTheme.SYSTEM, loaded.theme)

    def test_unknown_fields_from_a_newer_version_are_ignored(self):
        self.path().write_text('{"egress_region":"NL","something_from_the_future":42}')
        self.assertEqual("NL", AppSettings.load_from(self.path()).egress_region)

    def test_a_partial_file_keeps_the_defaults_for_what_it_omits(self):
        self.path().write_text('{"theme":2}')
        loaded = AppSettings.load_from(self.path())
        self.assertEqual(AppTheme.DARK, loaded.theme)
        self.assertTrue(loaded.minimise_to_tray)
        self.assertEqual(DEFAULT_BYPASS_LIST, loaded.proxy_bypass_list)

    def test_a_field_of_the_wrong_type_falls_back_alone(self):
        self.path().write_text(json.dumps({
            "egress_region": 7, "set_system_proxy": "yes", "local_http_proxy_port": True,
            "theme": 9, "known_regions": ["DE", 3], "connect_on_launch": True,
            "client_platform": "beos",
        }))
        loaded = AppSettings.load_from(self.path())
        self.assertEqual("", loaded.egress_region)
        self.assertTrue(loaded.set_system_proxy)
        self.assertEqual(0, loaded.local_http_proxy_port)
        self.assertEqual(AppTheme.SYSTEM, loaded.theme)
        self.assertEqual([], loaded.known_regions)
        self.assertEqual(ClientPlatform.WINDOWS, loaded.client_platform)
        self.assertTrue(loaded.connect_on_launch)

    def test_saving_twice_replaces_rather_than_appends(self):
        s = AppSettings(egress_region="DE")
        s.save_to(self.path())
        s.egress_region = "NL"
        s.save_to(self.path())
        self.assertEqual("NL", AppSettings.load_from(self.path()).egress_region)


if __name__ == "__main__":
    unittest.main()
