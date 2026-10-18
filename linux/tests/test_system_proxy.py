"""
The system proxy is what the whole desktop is pointed at while a tunnel is up.
Getting it wrong on the way in leaks traffic; getting it wrong on the way out
leaves the machine with no network. Both stores are exercised for real here,
GSettings through an in-memory backend and kioslaverc as a file in a temporary
directory, so nothing on the machine running the tests is touched.
"""

import json
import tempfile
import unittest
from pathlib import Path

from nextvpn.core import system_proxy
from nextvpn.core.settings import DEFAULT_BYPASS_LIST
from nextvpn.core.system_proxy import (GnomeBackend, KdeBackend, ProxyTarget, SystemProxy,
                                       get_kconfig_values, set_kconfig_values)

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    HAVE_GNOME_SCHEMA = (Gio.SettingsSchemaSource.get_default() is not None and
                         Gio.SettingsSchemaSource.get_default().lookup(GnomeBackend.SCHEMA, True) is not None)
except (ImportError, ValueError):
    HAVE_GNOME_SCHEMA = False


class FakeBackend:
    def __init__(self, name="fake", fail_apply=False):
        self.name = name
        self.label = name
        self.store = {"mode": "none", "port": 0}
        self.fail_apply = fail_apply
        self.applied = []

    def available(self):
        return True

    def capture(self):
        return dict(self.store)

    def apply(self, target):
        if self.fail_apply:
            raise RuntimeError("refused")
        self.applied.append(target)
        self.store = {"mode": "manual", "port": target.http_port}

    def restore(self, saved):
        self.store = dict(saved)

    def is_ours(self, target):
        return self.store == {"mode": "manual", "port": target.http_port}


class Temp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="nextvpn-proxy")
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class ManagerTests(Temp):
    def manager(self, *backends):
        return SystemProxy(self.dir / "proxy-backup.json", list(backends))

    def test_applying_nothing_is_refused_rather_than_pointing_the_machine_at_port_zero(self):
        fake = FakeBackend()
        result = self.manager(fake).apply(0, 1080, "localhost")
        self.assertFalse(result.ok)
        self.assertEqual([], fake.applied)
        self.assertFalse((self.dir / "proxy-backup.json").exists())

    def test_a_round_trip_puts_the_original_settings_back(self):
        fake = FakeBackend()
        proxy = self.manager(fake)
        self.assertTrue(proxy.apply(8080, 1080, "localhost").ok)
        self.assertEqual({"mode": "manual", "port": 8080}, fake.store)
        self.assertTrue(proxy.is_applied)

        self.assertTrue(proxy.revert())
        self.assertEqual({"mode": "none", "port": 0}, fake.store)
        self.assertFalse(proxy.is_applied)

    def test_the_backup_is_on_disk_before_anything_is_changed(self):
        class Watching(FakeBackend):
            def apply(inner, target):
                self.assertTrue((self.dir / "proxy-backup.json").is_file())
                super().apply(target)
        self.manager(Watching()).apply(8080, 0, "")

    def test_reapplying_with_new_ports_never_overwrites_the_real_original(self):
        fake = FakeBackend()
        proxy = self.manager(fake)
        proxy.apply(8080, 1080, "")
        proxy.apply(9090, 1081, "")   # a reconnect picked new ports
        self.assertEqual({"mode": "manual", "port": 9090}, fake.store)
        proxy.revert()
        self.assertEqual({"mode": "none", "port": 0}, fake.store)

    def test_a_crashed_session_is_repaired_on_the_next_start(self):
        fake = FakeBackend()
        self.manager(fake).apply(8080, 1080, "")
        # A new process, nothing in memory: only the backup file survives.
        self.assertTrue(self.manager(fake).recover_if_stale())
        self.assertEqual({"mode": "none", "port": 0}, fake.store)

    def test_a_change_the_user_made_while_connected_is_left_alone(self):
        fake = FakeBackend()
        proxy = self.manager(fake)
        proxy.apply(8080, 1080, "")
        fake.store = {"mode": "auto", "port": 0}   # pointed somewhere else by hand
        proxy.revert()
        self.assertEqual({"mode": "auto", "port": 0}, fake.store)
        self.assertFalse(proxy.is_applied)

    def test_one_failing_store_does_not_stop_the_others(self):
        good, bad = FakeBackend("good"), FakeBackend("bad", fail_apply=True)
        result = self.manager(good, bad).apply(8080, 0, "")
        self.assertEqual(["good"], result.applied)
        self.assertEqual(1, len(result.errors))

    def test_no_store_at_all_is_reported_as_not_applied(self):
        result = self.manager().apply(8080, 1080, "")
        self.assertFalse(result.ok)

    def test_a_corrupt_backup_does_not_stop_the_app(self):
        (self.dir / "proxy-backup.json").write_text("{ nope")
        self.assertFalse(self.manager(FakeBackend()).recover_if_stale())

    def test_the_bypass_list_reaches_the_store_parsed(self):
        fake = FakeBackend()
        self.manager(fake).apply(8080, 0, "localhost, 10.0.0.0/8;*.local")
        self.assertEqual(("localhost", "10.0.0.0/8", "*.local"), fake.applied[0].bypass)


class TextTests(unittest.TestCase):
    def test_everything_points_at_loopback_only(self):
        self.assertEqual("HTTP(S) 127.0.0.1:57104, SOCKS 127.0.0.1:57105", system_proxy.describe(57104, 57105))
        exports = system_proxy.shell_exports(57104, 57105)
        self.assertIn("https_proxy=http://127.0.0.1:57104", exports)
        self.assertIn("all_proxy=socks5h://127.0.0.1:57105", exports)
        self.assertEqual("", system_proxy.shell_exports(0, 0))


class KConfigFileTests(unittest.TestCase):
    ORIGINAL = (
        "[$Version]\nupdate_info=kioslave.upd:esc-remove\n\n"
        "[Proxy Settings]\nProxyType=0\nhttpProxy=\nNoProxyFor=\nAuthMode=0\n\n"
        "[Notification Messages]\nWarnOnLeaveSSLMode=false\n"
    )

    def test_only_the_named_group_changes(self):
        lines = set_kconfig_values(self.ORIGINAL.splitlines(True), "Proxy Settings",
                                   {"ProxyType": "1", "httpProxy": "http://127.0.0.1 8080", "socksProxy": "x"})
        text = "".join(lines)
        self.assertIn("[Notification Messages]\nWarnOnLeaveSSLMode=false\n", text)
        self.assertIn("[$Version]\nupdate_info=kioslave.upd:esc-remove\n", text)
        self.assertIn("AuthMode=0", text)
        values = get_kconfig_values(lines, "Proxy Settings", ["ProxyType", "httpProxy", "socksProxy"])
        self.assertEqual({"ProxyType": "1", "httpProxy": "http://127.0.0.1 8080", "socksProxy": "x"}, values)

    def test_a_key_set_to_none_is_removed(self):
        lines = set_kconfig_values(self.ORIGINAL.splitlines(True), "Proxy Settings", {"httpProxy": None})
        self.assertIsNone(get_kconfig_values(lines, "Proxy Settings", ["httpProxy"])["httpProxy"])

    def test_a_missing_group_is_added_at_the_end(self):
        lines = set_kconfig_values(["[Other]\n", "a=b\n"], "Proxy Settings", {"ProxyType": "1"})
        self.assertEqual("[Other]\na=b\n\n[Proxy Settings]\nProxyType=1\n", "".join(lines))

    def test_a_lookalike_key_in_another_group_is_not_touched(self):
        text = "[Elsewhere]\nProxyType=7\n"
        lines = set_kconfig_values(text.splitlines(True), "Proxy Settings", {"ProxyType": "1"})
        self.assertIn("[Elsewhere]\nProxyType=7\n", "".join(lines))


class KdeBackendTests(Temp):
    def backend(self, kde=True):
        environ = {"XDG_CURRENT_DESKTOP": "KDE"} if kde else {}
        return KdeBackend(self.dir / "kioslaverc", environ=environ, notify=False)

    def test_it_is_used_in_a_plasma_session_or_where_the_file_exists(self):
        self.assertTrue(self.backend(kde=True).available())
        self.assertFalse(self.backend(kde=False).available())
        (self.dir / "kioslaverc").write_text("")
        self.assertTrue(self.backend(kde=False).available())

    def test_apply_writes_what_plasma_itself_writes(self):
        kde = self.backend()
        kde.apply(ProxyTarget(57104, 57105, ("localhost", "10.0.0.0/8")))
        values = get_kconfig_values((self.dir / "kioslaverc").read_text().splitlines(True),
                                    "Proxy Settings", KdeBackend.KEYS)
        self.assertEqual("1", values["ProxyType"])
        self.assertEqual("http://127.0.0.1 57104", values["httpProxy"])
        self.assertEqual("http://127.0.0.1 57104", values["httpsProxy"])
        self.assertEqual("socks://127.0.0.1 57105", values["socksProxy"])
        self.assertEqual("localhost,10.0.0.0/8", values["NoProxyFor"])
        self.assertTrue(kde.is_ours(ProxyTarget(57104, 57105)))
        self.assertFalse(kde.is_ours(ProxyTarget(1, 57105)))

    def test_restore_gives_back_the_file_byte_for_byte(self):
        path = self.dir / "kioslaverc"
        path.write_text(KConfigFileTests.ORIGINAL)
        kde = self.backend()
        saved = kde.capture()
        kde.apply(ProxyTarget(8080, 1080, ("localhost",)))
        self.assertNotEqual(KConfigFileTests.ORIGINAL, path.read_text())
        kde.restore(json.loads(json.dumps(saved)))   # as it comes back from the backup file
        self.assertEqual(KConfigFileTests.ORIGINAL, path.read_text())

    def test_restoring_a_machine_that_had_no_settings_removes_ours(self):
        kde = self.backend()
        saved = kde.capture()
        kde.apply(ProxyTarget(8080, 1080, ()))
        kde.restore(saved)
        values = get_kconfig_values((self.dir / "kioslaverc").read_text().splitlines(True),
                                    "Proxy Settings", KdeBackend.KEYS)
        self.assertTrue(all(v is None for v in values.values()), values)


@unittest.skipUnless(HAVE_GNOME_SCHEMA, "org.gnome.system.proxy schema not installed")
class GnomeBackendTests(unittest.TestCase):
    def setUp(self):
        self.store = Gio.memory_settings_backend_new()
        self.gnome = GnomeBackend(settings_backend=self.store)

    def settings(self, child=""):
        schema = GnomeBackend.SCHEMA + (f".{child}" if child else "")
        return Gio.Settings.new_with_backend(schema, self.store)

    def test_apply_sets_manual_mode_on_loopback(self):
        self.assertTrue(self.gnome.available())
        self.gnome.apply(ProxyTarget(57104, 57105, ("localhost", "*.local")))
        self.assertEqual("manual", self.settings().get_string("mode"))
        self.assertEqual(["localhost", "*.local"], self.settings().get_strv("ignore-hosts"))
        for child in ("http", "https"):
            self.assertEqual("127.0.0.1", self.settings(child).get_string("host"))
            self.assertEqual(57104, self.settings(child).get_int("port"))
        self.assertEqual("127.0.0.1", self.settings("socks").get_string("host"))
        self.assertEqual(57105, self.settings("socks").get_int("port"))
        self.assertTrue(self.gnome.is_ours(ProxyTarget(57104, 57105)))

    def test_without_socks_no_socks_proxy_is_advertised(self):
        self.gnome.apply(ProxyTarget(57104, 0))
        self.assertEqual("", self.settings("socks").get_string("host"))

    def test_restore_gives_back_every_value_it_changed(self):
        self.settings().set_string("mode", "auto")
        self.settings().set_string("autoconfig-url", "http://wpad.example/proxy.pac")
        self.settings("http").set_string("host", "corp-proxy")
        self.settings("http").set_int("port", 3128)
        self.settings("http").set_boolean("use-authentication", True)

        saved = json.loads(json.dumps(self.gnome.capture()))   # via the backup file
        self.gnome.apply(ProxyTarget(57104, 57105, ("localhost",)))
        self.gnome.restore(saved)

        self.assertEqual("auto", self.settings().get_string("mode"))
        self.assertEqual("http://wpad.example/proxy.pac", self.settings().get_string("autoconfig-url"))
        self.assertEqual("corp-proxy", self.settings("http").get_string("host"))
        self.assertEqual(3128, self.settings("http").get_int("port"))
        self.assertTrue(self.settings("http").get_boolean("use-authentication"))
        self.assertEqual(["localhost", "127.0.0.0/8", "::1"], self.settings().get_strv("ignore-hosts"))
        self.assertFalse(self.gnome.is_ours(ProxyTarget(57104, 57105)))

    def test_the_default_bypass_list_is_accepted_by_gsettings(self):
        from nextvpn.core.settings import parse_bypass_list
        self.gnome.apply(ProxyTarget(1, 0, tuple(parse_bypass_list(DEFAULT_BYPASS_LIST))))
        self.assertIn("192.168.0.0/16", self.settings().get_strv("ignore-hosts"))


if __name__ == "__main__":
    unittest.main()
