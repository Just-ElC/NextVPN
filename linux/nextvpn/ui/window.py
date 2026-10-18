"""The main window: a header with the live status, four pages, and toasts."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_NAME
from ..core.i18n import _
from ..core.status import TunnelState
from .home import HomePage
from .log_page import LogPage
from .regions_page import RegionsPage
from .settings_page import SettingsPage
from .viewmodel import MainViewModel

DEFAULT_SIZE = (1040, 780)
MIN_SIZE = (360, 520)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, vm: MainViewModel, tray):
        super().__init__(application=app, title=APP_NAME)
        self.vm = vm
        self.tray = tray
        self.really_closing = False

        s = vm.settings
        width = s.window_width if s.window_width >= MIN_SIZE[0] else DEFAULT_SIZE[0]
        height = s.window_height if s.window_height >= MIN_SIZE[1] else DEFAULT_SIZE[1]
        self.set_default_size(width, height)
        self.set_size_request(*MIN_SIZE)
        if s.window_maximised:
            self.maximize()

        # ----------------------------------------------------------- pages
        self.stack = Adw.ViewStack(vexpand=True)
        self.home = HomePage(vm, self)
        self.regions = RegionsPage(vm)
        self.settings_page = SettingsPage(vm, self, tray)
        self.log_page = LogPage(vm, self)
        self.stack.add_titled_with_icon(self.home, "home", _("Connection"), "network-vpn-symbolic")
        self.stack.add_titled_with_icon(self.regions, "regions", _("Locations"), "find-location-symbolic")
        self.stack.add_titled_with_icon(self.settings_page, "settings", _("Settings"), "emblem-system-symbolic")
        self.stack.add_titled_with_icon(self.log_page, "log", _("Activity"), "view-list-symbolic")

        # ---------------------------------------------------------- header
        header = Adw.HeaderBar()
        self.switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self.switcher)

        # Live status, always visible whichever page is open.
        status = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        status.add_css_class("status-pill")
        self.status_dot = Gtk.Box(valign=Gtk.Align.CENTER)
        self.status_dot.add_css_class("status-dot")
        self.status_label = Gtk.Label()
        self.status_label.add_css_class("caption-heading")
        status.append(self.status_dot)
        status.append(self.status_label)
        header.pack_start(status)

        menu = Gio.Menu()
        menu.append(_("About NextVPN"), "app.about")
        menu.append(_("Quit"), "app.quit")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                     tooltip_text=_("Main menu"), primary=True)
        header.pack_end(menu_button)

        self.switcher_bar = Adw.ViewSwitcherBar(stack=self.stack)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.stack)
        toolbar.add_bottom_bar(self.switcher_bar)

        self.toasts = Adw.ToastOverlay(child=toolbar)
        self.set_content(self.toasts)

        # ---------------------------------------------------- breakpoints
        # Only the last matching breakpoint is ever applied, so the narrower one
        # comes second and carries everything the wider one does as well.
        stacked = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 860sp"))
        stacked.connect("apply", lambda *_: self.home.set_stacked(True))
        stacked.connect("unapply", lambda *_: self.home.set_stacked(False))
        self.add_breakpoint(stacked)

        # Phone-sized: the page switcher moves to the bottom as well.
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        narrow.connect("apply", lambda *_: (self._set_narrow(True), self.home.set_stacked(True)))
        narrow.connect("unapply", lambda *_: (self._set_narrow(False), self.home.set_stacked(False)))
        self.add_breakpoint(narrow)

        # --------------------------------------------------------- events
        self.connect("close-request", self._on_close_request)
        vm.connect("changed", lambda *_: self._update_status())
        self._update_status()

        shortcuts = Gtk.ShortcutController()
        for key, page in (("<Alt>1", "home"), ("<Alt>2", "regions"), ("<Alt>3", "settings"), ("<Alt>4", "log")):
            shortcuts.add_shortcut(Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string(key),
                Gtk.CallbackAction.new(lambda *_a, p=page: (self.show_page(p), True)[1])))
        shortcuts.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>f"),
            Gtk.CallbackAction.new(lambda *_: (self.show_page("regions"), self.regions.focus_search(), True)[2])))
        self.add_controller(shortcuts)

    # -------------------------------------------------------------- pages

    def show_page(self, name: str) -> None:
        self.stack.set_visible_child_name(name)

    def _set_narrow(self, narrow: bool) -> None:
        self.switcher_bar.set_reveal(narrow)
        self.switcher.set_visible(not narrow)

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(text))

    # ------------------------------------------------------------- status

    def _update_status(self) -> None:
        state = self.vm.state
        self.status_label.set_label(self.vm.status_text)
        for css in ("connected", "busy", "faulted"):
            self.status_dot.remove_css_class(css)
        if state == TunnelState.CONNECTED:
            self.status_dot.add_css_class("connected")
        elif state in (TunnelState.CONNECTING, TunnelState.DISCONNECTING):
            self.status_dot.add_css_class("busy")
        elif state == TunnelState.FAULTED:
            self.status_dot.add_css_class("faulted")

    # ------------------------------------------------------- window state

    def present_from_tray(self) -> None:
        self.set_visible(True)
        self.present()

    def keeps_running_when_closed(self) -> bool:
        return (self.vm.settings.minimise_to_tray and self.tray is not None and self.tray.available)

    def _on_close_request(self, *_):
        self.save_geometry()
        # The close button parks the app in the tray rather than tearing the tunnel
        # down, unless the user chose otherwise or there is no tray to park in.
        if self.really_closing or not self.keeps_running_when_closed():
            GLib.idle_add(lambda: (self.get_application().quit_app(), False)[1])
            return False
        self.set_visible(False)
        return True

    def save_geometry(self) -> None:
        s = self.vm.settings
        s.window_maximised = self.is_maximized()
        if not s.window_maximised:
            width, height = self.get_width(), self.get_height()
            if width >= MIN_SIZE[0] and height >= MIN_SIZE[1]:
                s.window_width, s.window_height = width, height
        s.save()
