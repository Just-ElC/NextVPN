"""The main window: a header with the page switcher, four pages, and toasts."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_NAME
from ..core.i18n import _
from . import diagnostics
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
        self.connect("realize", lambda *_: GLib.idle_add(self._report_renderer))

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

    # ---------------------------------------------------------- rendering

    def _report_renderer(self) -> bool:
        renderer = self.get_renderer()
        if renderer is not None:
            self.vm.set_renderer(renderer.__gtype__.name, diagnostics.gl_driver(self.get_display()))
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------- window state

    def present_from_tray(self) -> None:
        self.set_visible(True)
        self.present()

    def keeps_running_when_closed(self) -> bool:
        return self.vm.settings.close_to_tray and self.tray_available()

    def tray_available(self) -> bool:
        return self.tray is not None and self.tray.available

    def _on_close_request(self, *_):
        if self.really_closing:
            return False
        # The close button quits, unless the user asked for it to park the app in
        # the tray and there is a tray to park in.
        if self.keeps_running_when_closed():
            self.save_geometry()
            self.set_visible(False)
            return True
        # Quitting hides the window at once and it goes with the app. Letting
        # GTK destroy it here would detach it from the app before the quit
        # could be asked for, leaving the app running with no window.
        self.get_application().quit_app()
        return True

    def save_geometry(self) -> None:
        s = self.vm.settings
        s.window_maximised = self.is_maximized()
        if not s.window_maximised:
            width, height = self.get_width(), self.get_height()
            if width >= MIN_SIZE[0] and height >= MIN_SIZE[1]:
                s.window_width, s.window_height = width, height
        s.save()
