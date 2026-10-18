"""
Notification-area icon, built directly on the StatusNotifierItem and DBusMenu
D-Bus protocols.

GTK 4 has no tray icon of its own, and the libraries that provide one pull in
GTK 3. These two protocols are what Plasma, the GNOME AppIndicator extension,
XFCE, Cinnamon, Budgie, LXQt and waybar all speak, so implementing them over
GIO is the whole job: no third-party dependency, and every call arrives on the
main loop.
"""

from __future__ import annotations

import math
import os

import cairo
from gi.repository import Gio, GLib, GObject

from .. import APP_NAME
from ..core import paths
from ..core.i18n import _
from ..core.status import StatusPresenter, TunnelState

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <signal name="NewMenu"/>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg type="i" name="id"/>
      <arg type="u" name="timestamp"/>
    </signal>
  </interface>
</node>
"""

# Menu item ids. 0 is the root.
ID_STATUS, ID_SEP1, ID_TOGGLE, ID_SHOW, ID_SEP2, ID_QUIT = 1, 2, 3, 4, 5, 6

ICON_NAMES = {
    "connected": "nextvpn-tray-connected",
    "busy": "nextvpn-tray-connecting",
    "idle": "nextvpn-tray-disconnected",
}

COLOURS = {
    "connected": ((0x2E, 0xE6, 0xA8), (0x12, 0xB8, 0x86)),
    "busy": ((0xF2, 0xB4, 0x41), (0xD9, 0x96, 0x1E)),
    "idle": ((0x9A, 0x9F, 0xA8), (0x6B, 0x72, 0x80)),
}


def _kind(state: TunnelState) -> str:
    if state == TunnelState.CONNECTED:
        return "connected"
    if state in (TunnelState.CONNECTING, TunnelState.DISCONNECTING):
        return "busy"
    return "idle"


def render_pixmap(kind: str, size: int) -> tuple[int, int, bytes]:
    """
    The tray icon drawn directly: a disc in the state colour with a power glyph.
    Sent alongside the icon name, so the icon shows even where the host cannot
    find our files in its icon theme. ARGB32 in network byte order, not
    premultiplied, as the protocol asks.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    (r1, g1, b1), (r2, g2, b2) = COLOURS[kind]
    # Drawn on the same 64-unit grid as the SVG icons in data/icons.
    cr.scale(size / 64, size / 64)

    gradient = cairo.LinearGradient(0, 0, 64, 64)
    gradient.add_color_stop_rgb(0, r1 / 255, g1 / 255, b1 / 255)
    gradient.add_color_stop_rgb(1, r2 / 255, g2 / 255, b2 / 255)
    cr.set_source(gradient)
    cr.arc(32, 32, 29.5, 0, 2 * math.pi)
    cr.fill()

    cr.set_source_rgb(0x0E / 255, 0x15 / 255, 0x21 / 255)
    cr.set_line_width(5.5)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.arc(32, 35.44, 15, math.radians(-40), math.radians(220))
    cr.stroke()
    cr.move_to(32, 16)
    cr.line_to(32, 31)
    cr.stroke()

    surface.flush()
    data = bytearray(surface.get_data())
    stride = surface.get_stride()
    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            i = y * stride + x * 4
            b, g, r, a = data[i], data[i + 1], data[i + 2], data[i + 3]   # little-endian ARGB32
            if 0 < a < 255:
                r, g, b = (min(255, v * 255 // a) for v in (r, g, b))
            o = (y * size + x) * 4
            out[o:o + 4] = bytes((a, r, g, b))
    return size, size, bytes(out)


class TrayIcon(GObject.Object):
    __gsignals__ = {
        "activate": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "show-window": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "toggle-connection": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "quit": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "availability-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.available = False
        self._state = TunnelState.DISCONNECTED
        self._subtitle = ""
        self._revision = 1
        self._registered_ids: list[int] = []
        self._owner_id = 0
        self._watch_id = 0
        self._bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._pixmaps: dict[str, list] = {}

        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self._bus = None
            return

        try:
            self._export()
        except GLib.Error:
            self._bus = None
            return

        self.available = self._watcher_present()
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._bus, WATCHER, Gio.BusNameWatcherFlags.NONE, self._on_watcher_appeared, self._on_watcher_vanished)

    # ------------------------------------------------------------ public

    def set_state(self, state: TunnelState, subtitle: str) -> None:
        changed_icon = _kind(state) != _kind(self._state)
        self._state = state
        self._subtitle = subtitle
        if self._bus is None:
            return
        if changed_icon:
            self._emit_item("NewIcon")
        self._emit_item("NewToolTip")
        self._revision += 1
        self._emit_menu("LayoutUpdated", GLib.Variant("(ui)", (self._revision, 0)))

    def dispose(self) -> None:
        if self._bus is None:
            return
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        for reg in self._registered_ids:
            self._bus.unregister_object(reg)
        self._registered_ids = []

    # ------------------------------------------------------------- export

    def _export(self) -> None:
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._registered_ids.append(self._bus.register_object(
            ITEM_PATH, sni, self._on_item_call, self._on_item_property, None))
        self._registered_ids.append(self._bus.register_object(
            MENU_PATH, menu, self._on_menu_call, self._on_menu_property, None))
        self._owner_id = Gio.bus_own_name_on_connection(
            self._bus, self._bus_name, Gio.BusNameOwnerFlags.NONE, self._on_name_acquired, None)

    def _on_name_acquired(self, connection, name) -> None:
        self._register_with_watcher()

    def _watcher_present(self) -> bool:
        """Asks the bus daemon, never the watcher itself, so it cannot block on the panel."""
        try:
            return self._bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                       "NameHasOwner", GLib.Variant("(s)", (WATCHER,)), GLib.VariantType("(b)"),
                                       Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        except GLib.Error:
            return False

    def _set_available(self, available: bool) -> None:
        if available != self.available:
            self.available = available
            self.emit("availability-changed")

    def _register_with_watcher(self) -> None:
        def registered(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error:
                self._set_available(False)
                return
            self._set_available(True)
            # A watcher with no host behind it would accept us and show nothing.
            bus.call(WATCHER, "/StatusNotifierWatcher", "org.freedesktop.DBus.Properties", "Get",
                     GLib.Variant("(ss)", (WATCHER, "IsStatusNotifierHostRegistered")), GLib.VariantType("(v)"),
                     Gio.DBusCallFlags.NONE, 3000, None, host_checked)

        def host_checked(bus, result):
            try:
                hosted = bus.call_finish(result).unpack()[0]
            except GLib.Error:
                return  # an older watcher without the property: trust the registration
            if not hosted:
                self._set_available(False)

        self._bus.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                       GLib.Variant("(s)", (self._bus_name,)), None, Gio.DBusCallFlags.NONE, 3000, None, registered)

    def _on_watcher_appeared(self, connection, name, owner) -> None:
        # Also runs when the panel restarts: the new watcher knows nothing of us.
        self._register_with_watcher()

    def _on_watcher_vanished(self, connection, name) -> None:
        self._set_available(False)

    # ---------------------------------------------------------- item side

    def _icon_pixmaps(self, kind: str):
        if kind not in self._pixmaps:
            self._pixmaps[kind] = [render_pixmap(kind, s) for s in (22, 32, 48, 64)]
        return self._pixmaps[kind]

    def _tooltip_body(self) -> str:
        return self._subtitle or StatusPresenter.heading(self._state)

    def _on_item_property(self, connection, sender, path, interface, name):
        kind = _kind(self._state)
        icons = paths.icons_dir()
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "nextvpn"),
            "Title": GLib.Variant("s", APP_NAME),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconThemePath": GLib.Variant("s", str(icons) if icons else ""),
            "IconName": GLib.Variant("s", ICON_NAMES[kind]),
            "IconPixmap": GLib.Variant("a(iiay)", self._icon_pixmaps(kind)),
            "OverlayIconName": GLib.Variant("s", ""),
            "OverlayIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionIconName": GLib.Variant("s", ""),
            "AttentionIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionMovieName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (ICON_NAMES[kind], [], APP_NAME, self._tooltip_body())),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(name)

    def _on_item_call(self, connection, sender, path, interface, method, params, invocation):
        if method == "Activate":
            GLib.idle_add(self._emit_later, "activate")
        elif method == "SecondaryActivate":
            GLib.idle_add(self._emit_later, "toggle-connection")
        elif method == "ContextMenu":
            # Hosts draw the menu themselves from DBusMenu; nothing to do here.
            pass
        elif method != "Scroll":
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
            return
        invocation.return_value(None)

    def _emit_item(self, signal: str, params=None) -> None:
        try:
            self._bus.emit_signal(None, ITEM_PATH, "org.kde.StatusNotifierItem", signal, params)
        except GLib.Error:
            pass

    def _emit_later(self, signal: str) -> bool:
        self.emit(signal)
        return GLib.SOURCE_REMOVE

    # ---------------------------------------------------------- menu side

    def _items(self) -> dict[int, dict]:
        state = self._state
        status = StatusPresenter.heading(state)
        if self._subtitle and state == TunnelState.CONNECTED:
            status = f"{status} · {self._subtitle}"
        return {
            ID_STATUS: {"label": status, "enabled": False},
            ID_SEP1: {"type": "separator"},
            ID_TOGGLE: {"label": StatusPresenter.action_label(state),
                        "enabled": StatusPresenter.can_toggle(state)},
            ID_SHOW: {"label": _("Show NextVPN")},
            ID_SEP2: {"type": "separator"},
            ID_QUIT: {"label": _("Quit")},
        }

    @staticmethod
    def _props(item: dict, names=()) -> dict:
        props = {}
        for key, value in item.items():
            if names and key not in names:
                continue
            props[key] = GLib.Variant("b", value) if isinstance(value, bool) else GLib.Variant("s", value)
        return props

    def _layout(self, parent: int, depth: int, names) -> tuple:
        items = self._items()
        if parent == 0:
            children = []
            if depth != 0:
                children = [GLib.Variant("(ia{sv}av)", (i, self._props(item, names), []))
                            for i, item in items.items()]
            return 0, {"children-display": GLib.Variant("s", "submenu")}, children
        item = items.get(parent, {})
        return parent, self._props(item, names), []

    def _on_menu_property(self, connection, sender, path, interface, name):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(name)

    def _on_menu_call(self, connection, sender, path, interface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            parent, depth, names = args
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self._revision, self._layout(parent, depth, names))))
        elif method == "GetGroupProperties":
            ids, names = args
            items = self._items()
            wanted = ids or list(items)
            result = [(i, self._props(items[i], names)) for i in wanted if i in items]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            item_id, name = args
            value = self._props(self._items().get(item_id, {})).get(name)
            if value is None:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", name)
                return
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event_id, _data, _time = args
            if event_id == "clicked":
                self._activate_item(item_id)
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event_id, _data, _time in args[0]:
                if event_id == "clicked":
                    self._activate_item(item_id)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _activate_item(self, item_id: int) -> None:
        signal = {ID_TOGGLE: "toggle-connection", ID_SHOW: "show-window", ID_QUIT: "quit"}.get(item_id)
        if signal:
            GLib.idle_add(self._emit_later, signal)

    def _emit_menu(self, signal: str, params) -> None:
        try:
            self._bus.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", signal, params)
        except GLib.Error:
            pass
