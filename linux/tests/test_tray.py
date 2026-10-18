"""
The tray icon, over a real session bus, against a stand-in panel.

The test plays both other parties of the protocol: the StatusNotifierWatcher
the panel provides, and the host that reads the icon and the menu and clicks
on it. Runs only where a session bus exists (dbus-run-session provides one).
"""

import os
import threading
import time
import unittest

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    HAVE_BUS = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
except (ImportError, ValueError):
    HAVE_BUS = False

WATCHER_XML = """
<node>
  <interface name="org.kde.StatusNotifierWatcher">
    <method name="RegisterStatusNotifierItem"><arg name="service" type="s" direction="in"/></method>
    <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
    <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
  </interface>
</node>
"""


@unittest.skipUnless(HAVE_BUS, "needs a D-Bus session bus")
class TrayTests(unittest.TestCase):
    def setUp(self):
        from nextvpn.ui.tray import TrayIcon
        self.TrayIcon = TrayIcon
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.registered = []
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0]

        def call(conn, sender, path, iface, method, params, invocation):
            self.registered.append((sender, params.unpack()[0]))
            invocation.return_value(None)

        def prop(conn, sender, path, iface, name):
            if name == "IsStatusNotifierHostRegistered":
                return GLib.Variant("b", True)
            return GLib.Variant("as", [r[1] for r in self.registered])

        self.watcher_reg = self.bus.register_object("/StatusNotifierWatcher", info, call, prop, None)
        self.owner = Gio.bus_own_name_on_connection(self.bus, "org.kde.StatusNotifierWatcher",
                                                     Gio.BusNameOwnerFlags.NONE, None, None)
        self.spin_until(lambda: self.name_has_owner("org.kde.StatusNotifierWatcher"))

    def tearDown(self):
        Gio.bus_unown_name(self.owner)
        self.bus.unregister_object(self.watcher_reg)

    # ------------------------------------------------------------ helpers

    def spin(self, seconds):
        deadline = time.monotonic() + seconds
        ctx = GLib.MainContext.default()
        while time.monotonic() < deadline:
            ctx.iteration(False)
            time.sleep(0.01)

    def spin_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        ctx = GLib.MainContext.default()
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("timed out")
            ctx.iteration(False)
            time.sleep(0.01)

    def name_has_owner(self, name):
        return self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                  "NameHasOwner", GLib.Variant("(s)", (name,)), None,
                                  Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]

    def as_host(self, work):
        """Runs work on a separate connection and thread, as a panel would."""
        result = {}

        def run():
            address = os.environ["DBUS_SESSION_BUS_ADDRESS"]
            conn = Gio.DBusConnection.new_for_address_sync(
                address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
                Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
            try:
                result["value"] = work(conn)
            except Exception as ex:  # noqa: BLE001
                result["error"] = ex
            finally:
                conn.close_sync(None)

        thread = threading.Thread(target=run)
        thread.start()
        self.spin_until(lambda: not thread.is_alive(), timeout=10)
        if "error" in result:
            raise result["error"]
        return result["value"]

    def prop(self, conn, service, name):
        return conn.call_sync(service, "/StatusNotifierItem", "org.freedesktop.DBus.Properties", "Get",
                              GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", name)), None,
                              Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]

    def layout(self, conn, service):
        return conn.call_sync(service, "/MenuBar", "com.canonical.dbusmenu", "GetLayout",
                              GLib.Variant("(iias)", (0, -1, [])), None,
                              Gio.DBusCallFlags.NONE, 3000, None).unpack()

    # -------------------------------------------------------------- tests

    def test_the_icon_registers_and_reports_itself(self):
        from nextvpn.core.status import TunnelState
        tray = self.TrayIcon()
        try:
            self.spin_until(lambda: self.registered)
            self.spin_until(lambda: tray.available)
            service = self.registered[0][1]
            self.assertTrue(service.startswith("org.kde.StatusNotifierItem-"))

            tray.set_state(TunnelState.CONNECTED, "Traffic is exiting through Germany")
            values = self.as_host(lambda c: {n: self.prop(c, service, n)
                                             for n in ("IconName", "ToolTip", "Menu", "Title", "IconPixmap")})
            self.assertEqual("nextvpn-tray-connected", values["IconName"])
            self.assertEqual("/MenuBar", values["Menu"])
            self.assertEqual("NextVPN", values["Title"])
            self.assertEqual("Traffic is exiting through Germany", values["ToolTip"][3])
            sizes = [(w, h, len(data)) for w, h, data in values["IconPixmap"]]
            self.assertIn((22, 22, 22 * 22 * 4), sizes)
        finally:
            tray.dispose()

    def test_the_menu_says_what_a_click_will_do_and_clicks_reach_the_app(self):
        from nextvpn.core.status import TunnelState
        from nextvpn.ui import tray as tray_module
        tray = self.TrayIcon()
        fired = []
        tray.connect("toggle-connection", lambda *_: fired.append("toggle"))
        tray.connect("quit", lambda *_: fired.append("quit"))
        try:
            self.spin_until(lambda: self.registered)
            service = self.registered[0][1]

            tray.set_state(TunnelState.DISCONNECTED, "")
            revision, (root_id, root_props, children) = self.as_host(lambda c: self.layout(c, service))
            labels = {item[0]: item[1].get("label") for item in children}
            self.assertEqual(0, root_id)
            self.assertEqual("submenu", root_props["children-display"])
            self.assertEqual("Connect", labels[tray_module.ID_TOGGLE])
            self.assertEqual("Quit", labels[tray_module.ID_QUIT])

            tray.set_state(TunnelState.CONNECTED, "Germany")
            revision2, (_r, _p, children) = self.as_host(lambda c: self.layout(c, service))
            self.assertGreater(revision2, revision)
            labels = {item[0]: item[1].get("label") for item in children}
            self.assertEqual("Disconnect", labels[tray_module.ID_TOGGLE])

            def click(conn, item):
                conn.call_sync(service, "/MenuBar", "com.canonical.dbusmenu", "Event",
                               GLib.Variant("(isvu)", (item, "clicked", GLib.Variant("s", ""), 0)), None,
                               Gio.DBusCallFlags.NONE, 3000, None)
                return True

            self.as_host(lambda c: click(c, tray_module.ID_TOGGLE))
            self.as_host(lambda c: click(c, tray_module.ID_QUIT))
            self.spin_until(lambda: len(fired) == 2)
            self.assertEqual(["toggle", "quit"], fired)
        finally:
            tray.dispose()

    def test_without_a_panel_the_tray_reports_itself_unavailable(self):
        Gio.bus_unown_name(self.owner)
        self.spin_until(lambda: not self.name_has_owner("org.kde.StatusNotifierWatcher"))
        tray = self.TrayIcon()
        try:
            self.spin(0.3)
            self.assertFalse(tray.available)
        finally:
            tray.dispose()
        self.owner = Gio.bus_own_name_on_connection(self.bus, "org.kde.StatusNotifierWatcher",
                                                     Gio.BusNameOwnerFlags.NONE, None, None)


if __name__ == "__main__":
    unittest.main()
