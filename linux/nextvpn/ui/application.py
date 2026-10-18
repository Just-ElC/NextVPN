"""
The application: one instance per user, which owns the tunnel and the system
proxy. A second launch hands its command line to the running one instead of
dying silently, which is what a user clicking the icon again expects.
"""

from __future__ import annotations

import signal
import sys

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_ID, APP_NAME, VERSION
from ..core import autostart, paths
from ..core.i18n import _
from ..core.settings import AppSettings
from ..core.status import TunnelState
from ..core.system_proxy import SystemProxy
from . import theme
from .notify import Notifier
from .tray import TrayIcon
from .viewmodel import MainViewModel
from .window import MainWindow

#: How long a hidden start waits for the panel's tray to appear before giving up
#: and showing the window. Sign-in starts apps and the panel at the same time.
TRAY_WAIT_SECONDS = 8


class NextVpnApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name(APP_NAME)

        self.vm: MainViewModel | None = None
        self.window: MainWindow | None = None
        self.tray: TrayIcon | None = None
        self.notifier: Notifier | None = None
        self._quitting = False
        self._held = False

        option = GLib.OptionFlags.NONE
        none = GLib.OptionArg.NONE
        self.add_main_option("minimised", ord("m"), option, none, _("Start in the notification area"), None)
        self.add_main_option("minimized", 0, GLib.OptionFlags.HIDDEN, none, "", None)
        self.add_main_option("connect", ord("c"), option, none, _("Connect the tunnel"), None)
        self.add_main_option("disconnect", ord("d"), option, none, _("Disconnect the tunnel"), None)
        self.add_main_option("toggle", ord("t"), option, none, _("Connect or disconnect"), None)
        self.add_main_option("quit", ord("q"), option, none, _("Disconnect and quit the running instance"), None)
        self.add_main_option("version", ord("v"), option, none, _("Print the version and exit"), None)
        self.connect("handle-local-options", self._on_local_options)

    # ------------------------------------------------------------ startup

    def _on_local_options(self, _app, options: GLib.VariantDict) -> int:
        if options.contains("version"):
            print(f"{APP_NAME} {VERSION}")
            return 0
        return -1

    def do_startup(self):
        Adw.Application.do_startup(self)
        theme.install()

        icons = paths.icons_dir()
        if icons is not None:
            Gtk.IconTheme.get_for_display(self._display()).add_search_path(str(icons))
        Gtk.Window.set_default_icon_name(APP_ID)

        settings = AppSettings.load()
        theme.apply(settings.theme)
        settings.start_at_login = autostart.is_enabled()

        # If a previous run was killed while connected, put the proxy back first.
        proxy = SystemProxy()
        proxy.recover_if_stale()

        self.vm = MainViewModel(settings, proxy=proxy)
        self.notifier = Notifier(self)
        self.tray = TrayIcon()
        self.tray.connect("activate", lambda *_: self._toggle_window())
        self.tray.connect("show-window", lambda *_: self._show_window())
        self.tray.connect("toggle-connection", lambda *_: self.vm.toggle())
        self.tray.connect("quit", lambda *_: self.quit_app())
        self.vm.connect("changed", lambda *_: self._update_tray())
        self.vm.connect("state-changed", self._on_state_changed)
        self._update_tray()

        self._action("about", self._show_about)
        self._action("quit", lambda *_: self.quit_app(), ["<Control>q"])
        self._action("toggle", lambda *_: self.vm.toggle())
        self.set_accels_for_action("window.close", ["<Control>w"])

        # Logging out, a shutdown or Ctrl+C in a terminal: the proxy has to be
        # handed back before the process goes.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, self._on_unix_signal)

        # Stays alive with the window hidden; released by quit_app().
        self.hold()
        self._held = True

    @staticmethod
    def _display():
        from gi.repository import Gdk
        return Gdk.Display.get_default()

    def _action(self, name, callback, accels=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    # ------------------------------------------------------- command line

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict().end().unpack()
        first_run = self.window is None

        if options.get("quit"):
            self.quit_app()
            return 0

        if first_run:
            self.window = MainWindow(self, self.vm, self.tray)

        if options.get("connect"):
            self.vm.connect_tunnel()
        elif options.get("disconnect"):
            self.vm.disconnect_tunnel()
        elif options.get("toggle"):
            self.vm.toggle()

        hidden = bool(options.get("minimised") or options.get("minimized"))
        acted = any(options.get(k) for k in ("connect", "disconnect", "toggle"))

        if first_run:
            if hidden or self.vm.settings.start_minimised:
                self._start_hidden()
            else:
                self.window.present()
            if self.vm.settings.connect_on_launch and not acted:
                self.vm.connect_tunnel()
        elif not hidden and not acted:
            # Launched again from the menu: surface the window that is already there.
            self._show_window()
        return 0

    def do_activate(self):
        self._show_window()

    def _start_hidden(self) -> None:
        """
        Parks the app in the tray, but only if there is a tray to park in: an app
        with no window and no icon would be running with no way to reach it.
        """
        if not self.vm.settings.minimise_to_tray:
            self.window.present()
            return
        if self.tray.available:
            return

        waited = {"seconds": 0}

        def check():
            if self.tray.available:
                return GLib.SOURCE_REMOVE
            waited["seconds"] += 1
            if waited["seconds"] >= TRAY_WAIT_SECONDS:
                self.window.present()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add_seconds(1, check)

    # ------------------------------------------------------------- window

    def _show_window(self) -> None:
        if self.window is None:
            self.window = MainWindow(self, self.vm, self.tray)
        self.window.present_from_tray()

    def _toggle_window(self) -> None:
        if self.window is not None and self.window.get_visible() and self.window.is_active():
            if self.window.keeps_running_when_closed():
                self.window.save_geometry()
                self.window.set_visible(False)
                return
        self._show_window()

    def _update_tray(self) -> None:
        if self.tray is not None:
            self.tray.set_state(self.vm.state, self.vm.status_subtitle)

    def _on_state_changed(self, _vm, previous, state) -> None:
        # Only tell the user about a change they cannot already see.
        if self.window is not None and self.window.get_visible():
            return
        if state == TunnelState.CONNECTED:
            self.notifier.send(APP_NAME, self.vm.status_subtitle)
        elif state == TunnelState.FAULTED:
            self.notifier.send(APP_NAME, _("The tunnel stopped unexpectedly."))

    def _show_about(self, *_):
        details = dict(
            application_name=APP_NAME, application_icon=APP_ID, version=VERSION, developer_name="NextOS",
            website="https://github.com/Just-ElC/NextVPN",
            issue_url="https://github.com/Just-ElC/NextVPN/issues",
            comments=_("Free internet in one click. Runs on the open psiphon-tunnel-core engine (GPLv3) and "
                       "uses the same server network as NextVPN for Windows. NextVPN is an independent "
                       "application and is not affiliated with Psiphon Inc."))
        if hasattr(Adw, "AboutDialog"):          # libadwaita 1.5+
            Adw.AboutDialog(**details).present(self.window)
        else:                                    # pragma: no cover
            Adw.AboutWindow(transient_for=self.window, **details).present()

    # --------------------------------------------------------------- quit

    def _on_unix_signal(self) -> bool:
        self.quit_app()
        return GLib.SOURCE_REMOVE

    def quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        if self.window is not None:
            self.window.really_closing = True
            self.window.save_geometry()
        self._teardown()
        if self._held:
            self._held = False
            self.release()
        self.quit()

    def _teardown(self) -> None:
        try:
            if self.vm is not None:
                self.vm.shutdown()
        finally:
            if self.tray is not None:
                self.tray.dispose()

    def do_shutdown(self):
        # Reached by quit() and by the main loop ending any other way. The work is
        # idempotent, so a crash path that skipped quit_app still cleans up.
        if not self._quitting:
            self._quitting = True
            self._teardown()
        Adw.Application.do_shutdown(self)


def run(argv=None) -> int:
    app = NextVpnApplication()
    return app.run(argv if argv is not None else sys.argv)
