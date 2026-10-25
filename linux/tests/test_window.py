"""
Closing the main window, with the real application and window on a display
(Xvfb in CI) and a session bus, against the fake engine and, where a test asks
for one, a stand-in panel with a tray.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, Gio, GLib, Gtk
    # init_check() reports success even with nowhere to draw; the display tells.
    HAVE_DESKTOP = (bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")) and Gtk.init_check()
                    and Gdk.Display.get_default() is not None)
except (ImportError, ValueError):
    HAVE_DESKTOP = False

from tests.test_tray import WATCHER_XML

HERE = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 20
#: Set in CI, where a missing display must fail the run rather than skip these.
REQUIRED = os.environ.get("NEXTVPN_DESKTOP_TESTS") == "1"


@unittest.skipUnless(HAVE_DESKTOP or REQUIRED, "needs a display and a D-Bus session bus")
class CloseWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAVE_DESKTOP:
            raise AssertionError("NEXTVPN_DESKTOP_TESTS=1, but there is no display or no session bus")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        engine_dir = self.dir / "engine"
        engine_dir.mkdir()
        binary = engine_dir / "psiphon-tunnel-core"
        binary.write_text(f"#!{sys.executable}\nimport runpy\n"
                          f"runpy.run_path({str(HERE / 'fake_engine.py')!r}, run_name='__main__')\n")
        binary.chmod(0o755)
        (engine_dir / "base.config").write_text('{"SponsorId":"S","PropagationChannelId":"P"}')
        (engine_dir / "server_list.dat").write_text("00")
        self.record = self.dir / "record.txt"

        env = mock.patch.dict(os.environ, {
            "HOME": str(self.dir),
            "XDG_CONFIG_HOME": str(self.dir / "config"),
            "XDG_DATA_HOME": str(self.dir / "data"),
            "XDG_CACHE_HOME": str(self.dir / "cache"),
            "NEXTVPN_ENGINE": str(binary),
            "NEXTVPN_ENGINE_DIR": str(engine_dir),
            "FAKE_ENGINE_SCENARIO": "connect",
            "FAKE_ENGINE_RECORD": str(self.record),
        })
        env.start()
        self.addCleanup(env.stop)

    def settings(self, **values):
        # Proxy mode without touching the system proxy: nothing here may reach
        # the machine's own network settings.
        data = {"connection_mode": "proxy", "set_system_proxy": False, **values}
        path = self.dir / "config" / "nextvpn" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def panel(self):
        """A stand-in StatusNotifierWatcher, as KDE Plasma or waybar provide."""
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0]

        def call(conn, sender, path, iface, method, params, invocation):
            invocation.return_value(None)

        def prop(conn, sender, path, iface, name):
            return GLib.Variant("b", True) if name == "IsStatusNotifierHostRegistered" else GLib.Variant("as", [])

        registration = bus.register_object("/StatusNotifierWatcher", info, call, prop, None)
        owner = Gio.bus_own_name_on_connection(bus, "org.kde.StatusNotifierWatcher",
                                               Gio.BusNameOwnerFlags.NONE, None, None)
        self.addCleanup(bus.unregister_object, registration)
        self.addCleanup(Gio.bus_unown_name, owner)

    def run_app(self, script):
        """
        Runs the application until it quits by itself. script(app) is a generator
        that yields conditions to wait for between its steps.
        """
        from nextvpn.ui.application import NextVpnApplication
        app = NextVpnApplication()
        # Unique per test, not per bus: tests run one after another in a process.
        app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        steps = script(app)
        waiting = [lambda: app.window is not None and app.window.get_mapped()]
        deadline = time.monotonic() + TIMEOUT_SECONDS
        timed_out = []

        def tick():
            if time.monotonic() > deadline:
                timed_out.append(True)
                app.quit()
                return GLib.SOURCE_REMOVE
            if waiting[0]():
                waiting[0] = next(steps, None) or (lambda: False)
            return GLib.SOURCE_CONTINUE

        source = GLib.timeout_add(50, tick)
        app.run(["nextvpn", "--connect"])
        if not timed_out:
            GLib.source_remove(source)
        return app, bool(timed_out)

    def connected(self, app):
        from nextvpn.core.status import TunnelState
        return app.vm.state == TunnelState.CONNECTED

    def engine_stopped(self):
        return "SIGTERM" in self.record.read_text().split()

    def close_and_check_it_quits(self):
        seen = {}

        def script(app):
            yield lambda: self.connected(app)
            app.window.close()
            seen["visible after close"] = app.window.get_visible()

        started = time.monotonic()
        app, timed_out = self.run_app(script)
        self.assertFalse(timed_out, "the app kept running after its window was closed")
        self.assertFalse(seen["visible after close"])
        self.assertLess(time.monotonic() - started, TIMEOUT_SECONDS)
        self.assertTrue(self.engine_stopped())
        self.assertFalse(app.vm.engine.is_running)

    def test_the_close_button_quits_where_there_is_a_tray(self):
        # KDE Plasma on CachyOS and Arch: a tray is there, the user did not ask
        # to stay in it.
        self.settings()
        self.panel()
        self.close_and_check_it_quits()

    def test_the_close_button_quits_where_there_is_no_tray(self):
        self.settings()
        self.close_and_check_it_quits()

    def test_asked_to_stay_in_the_tray_the_close_button_only_hides_the_window(self):
        self.settings(close_to_tray=True)
        self.panel()
        seen = {}

        def script(app):
            yield lambda: self.connected(app) and app.tray.available
            app.window.close()
            closed_at = time.monotonic()
            yield lambda: time.monotonic() - closed_at > 1
            seen["visible"] = app.window.get_visible()
            seen["connected"] = self.connected(app)
            app.quit_app()

        _app, timed_out = self.run_app(script)
        self.assertFalse(timed_out, "the app did not quit when asked to")
        self.assertEqual({"visible": False, "connected": True}, seen)
        self.assertTrue(self.engine_stopped())


if __name__ == "__main__":
    unittest.main()
