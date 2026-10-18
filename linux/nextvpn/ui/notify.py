"""
Desktop notifications, sent straight to org.freedesktop.Notifications.

GNotification would route through GNOME Shell's own API on GNOME, which only
shows notifications for applications it can find a desktop file for. The
freedesktop interface works on every desktop, installed or run from a checkout,
and lets each new notice replace the previous one instead of piling up.
"""

from __future__ import annotations

from gi.repository import Gio, GLib

from .. import APP_ID, APP_NAME
from ..core import paths


class Notifier:
    def __init__(self, application: Gio.Application | None = None):
        self._app = application
        self._last_id = 0
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self._bus = None

    @staticmethod
    def _icon() -> str:
        icons = paths.icons_dir()
        if icons is not None and paths.is_source_checkout():
            candidate = icons / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
            if candidate.is_file():
                return str(candidate)
        return APP_ID

    def send(self, title: str, body: str) -> None:
        if self._bus is None:
            self._fallback(title, body)
            return

        hints = {"desktop-entry": GLib.Variant("s", APP_ID), "urgency": GLib.Variant("y", 1)}
        params = GLib.Variant("(susssasa{sv}i)",
                              (APP_NAME, self._last_id, self._icon(), title, body, [], hints, 5000))

        def done(bus, result):
            try:
                self._last_id = bus.call_finish(result).unpack()[0]
            except GLib.Error:
                self._fallback(title, body)

        self._bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                       "org.freedesktop.Notifications", "Notify", params, GLib.VariantType("(u)"),
                       Gio.DBusCallFlags.NONE, 3000, None, done)

    def _fallback(self, title: str, body: str) -> None:
        if self._app is None:
            return
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        self._app.send_notification("state", notification)
