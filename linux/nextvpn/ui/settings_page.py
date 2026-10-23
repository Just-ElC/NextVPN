"""Settings. Every option the Windows build has, laid out as libadwaita preferences."""

from __future__ import annotations

import threading

from gi.repository import Adw, Gio, GLib, Gtk

from .. import VERSION
from ..core import autostart, paths, vpn
from ..core.engine import engine_version
from ..core.i18n import _
from ..core.regions import TUNNEL_PROTOCOLS
from ..core.settings import DEFAULT_BYPASS_LIST, AppTheme, ClientPlatform, ConnectionMode
from ..core.system_proxy import GnomeBackend, KdeBackend
from . import theme
from .viewmodel import MainViewModel


class SettingsPage(Adw.PreferencesPage):
    def __init__(self, vm: MainViewModel, window, tray):
        super().__init__()
        self.vm = vm
        self.settings = vm.settings
        self.window = window
        self.tray = tray
        self._loading = True
        self._port_timer = 0
        #: Whether NetworkManager is running; None until the first check returns.
        self._vpn_available: bool | None = None

        self._build_connection()
        self._build_transports()
        self._build_system()
        self._build_startup()
        self._build_appearance()
        self._build_about()

        vm.connect("changed", lambda *_: self._refresh())
        if tray is not None:
            tray.connect("availability-changed", lambda *_: self._refresh_tray())
        self.connect("map", lambda *_: self._sync_autostart())
        self.connect("map", lambda *_: self._check_vpn())
        self._refresh()
        self._refresh_tray()
        self._loading = False

    # ----------------------------------------------------------- helpers

    def _switch(self, group, title: str, subtitle: str, attr: str, on_change) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.set_active(getattr(self.settings, attr))

        def changed(r, _pspec):
            if self._loading:
                return
            setattr(self.settings, attr, r.get_active())
            on_change()

        row.connect("notify::active", changed)
        group.add(row)
        return row

    def _tunnel_changed(self):
        self.vm.apply_tunnel_setting_change()

    def _local_changed(self):
        self.vm.notify_settings_changed()

    # ------------------------------------------------------------- build

    def _build_connection(self):
        group = Adw.PreferencesGroup(title=_("Connection"))

        self.region_row = Adw.ActionRow(title=_("Exit location"),
                                        subtitle=_("The country your traffic appears to come from."))
        self.region_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.region_button.connect("clicked", lambda *_: self.window.show_page("regions"))
        self.region_row.add_suffix(self.region_button)
        self.region_row.set_activatable_widget(self.region_button)
        group.add(self.region_row)

        self.mode_row = Adw.ComboRow(
            title=_("What goes through the tunnel"),
            model=Gtk.StringList.new([_("Everything (VPN)"), _("Programs that use the system proxy")]))
        self.mode_row.set_selected(0 if self.settings.connection_mode == ConnectionMode.VPN else 1)
        self.mode_row.connect("notify::selected", self._on_mode)
        group.add(self.mode_row)

        self._switch(group, _("Split tunnelling"),
                     _("Send traffic bound for your own country straight out, bypassing the tunnel. Local "
                       "banking and streaming keep working, but those connections are not hidden."),
                     "split_tunnel_own_region", self._tunnel_changed)

        self._switch(group, _("Relax connection timeouts"),
                     _("Give each candidate server longer to answer and never give up establishing. Helps on "
                       "very slow or lossy links."),
                     "disable_timeouts", self._tunnel_changed)

        platforms = Gtk.StringList.new(["Windows", "Linux"])
        self.platform_row = Adw.ComboRow(
            title=_("Identify to the servers as"),
            subtitle=_("The servers tune their settings by platform. Windows gets this client exactly what "
                       "NextVPN for Windows gets from the same servers."),
            model=platforms)
        self.platform_row.set_selected(1 if self.settings.client_platform == ClientPlatform.LINUX else 0)
        self.platform_row.connect("notify::selected", self._on_platform)
        group.add(self.platform_row)

        self.upstream_row = Adw.EntryRow(title=_("Upstream proxy, e.g. http://user:pass@host:8080"),
                                         show_apply_button=True)
        self.upstream_row.set_text(self.settings.upstream_proxy_url)
        self.upstream_row.connect("apply", self._on_upstream)
        group.add(self.upstream_row)
        self.add(group)

    def _build_transports(self):
        group = Adw.PreferencesGroup(
            title=_("Transports"),
            description=_("Leave everything unchecked to let the engine pick whatever gets through. That is "
                          "the right choice on almost every network; restrict it only when you know a specific "
                          "transport works."))
        self.protocol_checks = {}
        for p in TUNNEL_PROTOCOLS:
            row = Adw.ActionRow(title=_(p.name), subtitle=_(p.description))
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(p.id in self.settings.limit_tunnel_protocols)
            check.connect("toggled", self._on_protocol)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            group.add(row)
            self.protocol_checks[p.id] = check
        self.add(group)

    def _build_system(self):
        group = Adw.PreferencesGroup(title=_("System"))
        self.proxy_row = self._switch(
            group, _("Set the system proxy"), "", "set_system_proxy", self._local_changed)

        self.bypass_row = Adw.EntryRow(title=_("Hosts that go direct"),
                                       show_apply_button=True)
        self.bypass_row.set_text(self.settings.proxy_bypass_list)
        self.bypass_row.set_tooltip_text(_("Separated by commas. CIDR ranges such as 10.0.0.0/8 and * wildcards "
                                           "such as *.local work."))
        self.bypass_row.connect("apply", self._on_bypass)
        reset = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text=_("Reset to defaults"))
        reset.add_css_class("flat")
        reset.connect("clicked", self._on_reset_bypass)
        self.bypass_row.add_suffix(reset)
        group.add(self.bypass_row)

        self.http_port_row = self._port_row(_("HTTP proxy port"), self.settings.local_http_proxy_port)
        self.socks_port_row = self._port_row(_("SOCKS proxy port"), self.settings.local_socks_proxy_port)
        group.add(self.http_port_row)
        group.add(self.socks_port_row)
        self.add(group)

    def _port_row(self, title: str, value: int) -> Adw.SpinRow:
        row = Adw.SpinRow.new_with_range(0, 65535, 1)
        row.set_title(title)
        row.set_subtitle(_("0 picks a free port automatically. Set a fixed port if other software needs to "
                           "point at it."))
        row.set_value(value)
        row.connect("notify::value", self._on_port)
        return row

    def _build_startup(self):
        group = Adw.PreferencesGroup(title=_("Startup and window"))
        self.tray_row = self._switch(group, _("Keep running in the notification area"), "",
                                     "minimise_to_tray", self._local_changed)
        self._switch(group, _("Start in the notification area"), _("Launch without showing the window."),
                     "start_minimised", self._local_changed)
        self._switch(group, _("Connect on launch"), _("Start the tunnel as soon as the app opens."),
                     "connect_on_launch", self._local_changed)

        self.autostart_row = Adw.SwitchRow(
            title=_("Launch when I sign in"),
            subtitle=_("Adds a startup entry for your user account only. No administrator rights needed."))
        self.autostart_row.set_active(autostart.is_enabled())
        self.autostart_row.connect("notify::active", self._on_autostart)
        group.add(self.autostart_row)
        self.add(group)

    def _build_appearance(self):
        group = Adw.PreferencesGroup(title=_("Appearance"))
        self.theme_row = Adw.ComboRow(
            title=_("Theme"), subtitle=_("Takes effect immediately."),
            model=Gtk.StringList.new([_("Follow system"), _("Light"), _("Dark")]))
        self.theme_row.set_selected(int(self.settings.theme))
        self.theme_row.connect("notify::selected", self._on_theme)
        group.add(self.theme_row)
        self.add(group)

    def _build_about(self):
        group = Adw.PreferencesGroup(title=_("About"))

        group.add(Adw.ActionRow(title="NextVPN", subtitle=_("Version {version} for Linux").format(version=VERSION)))

        self.engine_row = Adw.ActionRow(title=_("Tunnel engine"), subtitle=_("Checking…"))
        self.engine_row.set_subtitle_selectable(True)
        group.add(self.engine_row)
        threading.Thread(target=self._query_engine, daemon=True).start()

        licence = Adw.ActionRow(
            title=_("Psiphon"),
            subtitle=_("Circumvention is provided by psiphon-tunnel-core, the open source engine from "
                       "Psiphon Inc., licensed under the GPLv3. This client uses the same server network as "
                       "NextVPN for Windows. It is an independent interface and is not affiliated with or "
                       "endorsed by Psiphon Inc."))
        group.add(licence)

        updates = Adw.ActionRow(
            title=_("No self-updating"),
            subtitle=_("This client never downloads a replacement for itself and never rewrites or deletes "
                       "its own files. Updates are entirely your decision."))
        updates.add_prefix(Gtk.Image(icon_name="security-high-symbolic"))
        group.add(updates)

        for title, path in ((_("Open data folder"), paths.data_dir()),
                            (_("Open settings folder"), paths.config_dir()),
                            (_("Open engine folder"), None)):
            row = Adw.ActionRow(title=title, activatable=True)
            row.add_suffix(Gtk.Image(icon_name="folder-open-symbolic"))
            row.connect("activated", self._open_folder, path)
            group.add(row)
        self.add(group)

    # ------------------------------------------------------------ refresh

    def _refresh(self):
        label = self.vm.selected_region.display
        if self.region_button.get_label() != label:
            self.region_button.set_label(label)

        vpn_mode = self.settings.connection_mode == ConnectionMode.VPN
        if vpn_mode and self._vpn_available is False:
            mode = _("NetworkManager was not found here, so connections fall back to the system proxy. "
                     "Install and start NetworkManager to tunnel every program.")
        elif vpn_mode:
            mode = _("Every program, game and terminal goes through the tunnel, DNS included, on any desktop. "
                     "NetworkManager sets up the VPN interface; no password is asked.")
        else:
            mode = _("Only programs that follow the GNOME or KDE proxy settings go through the tunnel, plus "
                     "whatever you point at the local proxy yourself. Most programs on Hyprland, Sway and "
                     "other window managers ignore it.")
        self.mode_row.set_subtitle(mode)
        for row in (self.proxy_row, self.bypass_row):
            row.set_sensitive(not vpn_mode or self._vpn_available is False)

        found = []
        for backend in (GnomeBackend(), KdeBackend()):
            try:
                if backend.available():
                    found.append(backend.label)
            except Exception:  # noqa: BLE001
                continue
        if found:
            where = _("Found here: {desktops}.").format(desktops=", ".join(found))
        else:
            where = _("No GNOME or KDE proxy settings were found here; point applications at the local "
                      "proxy by hand.")
        self.proxy_row.set_subtitle(
            _("Points GNOME and KDE at the local proxy while connected, keeps it there while the tunnel "
              "reconnects so nothing leaks around it, and puts your own settings back on disconnect.")
            + " " + where)

    def _refresh_tray(self):
        available = self.tray is not None and self.tray.available
        if available:
            self.tray_row.set_subtitle(_("Closing the window parks the app in the tray instead of quitting. "
                                         "Turn this off and the close button really quits."))
        else:
            self.tray_row.set_subtitle(_("No notification area was found on this desktop, so closing the window "
                                         "quits. On GNOME, install the AppIndicator extension."))

    def _check_vpn(self):
        def check():
            found = vpn.available()
            GLib.idle_add(done, found)

        def done(found):
            if found != self._vpn_available:
                self._vpn_available = found
                self._refresh()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=check, daemon=True).start()

    def _on_mode(self, row, _pspec):
        if self._loading:
            return
        self.settings.connection_mode = ConnectionMode.VPN if row.get_selected() == 0 else ConnectionMode.PROXY
        self._refresh()
        self.vm.apply_tunnel_setting_change()
        self.vm.notify_settings_changed()

    def _sync_autostart(self):
        # Keep the toggle honest if the entry was removed elsewhere.
        enabled = autostart.is_enabled()
        if self.autostart_row.get_active() != enabled:
            self._loading = True
            self.autostart_row.set_active(enabled)
            self._loading = False
        self.settings.start_at_login = enabled

    def _query_engine(self):
        binary = paths.engine().binary
        info = engine_version(binary)
        if info is None:
            text = _("Not found. Install psiphon-tunnel-core or point NEXTVPN_ENGINE at it.")
        elif info.revision == "unknown":
            text = _("{path}, version unknown").format(path=binary)
        else:
            text = _("psiphon-tunnel-core {revision} ({go}), built {date}").format(
                revision=info.revision, go=info.built_with, date=info.build_date)
        GLib.idle_add(lambda: (self.engine_row.set_subtitle(text), False)[1])

    # ----------------------------------------------------------- handlers

    def _on_platform(self, row, _pspec):
        if self._loading:
            return
        self.settings.client_platform = ClientPlatform.LINUX if row.get_selected() == 1 else ClientPlatform.WINDOWS
        self._tunnel_changed()

    def _on_upstream(self, row):
        text = row.get_text().strip()
        if text and "://" not in text:
            self.window.toast(_("An upstream proxy needs a scheme, such as http:// or socks5://"))
            return
        self.settings.upstream_proxy_url = text
        self._tunnel_changed()
        self.window.toast(_("Upstream proxy saved"))

    def _on_protocol(self, *_):
        if self._loading:
            return
        self.settings.limit_tunnel_protocols = [p.id for p in TUNNEL_PROTOCOLS if self.protocol_checks[p.id].get_active()]
        self._tunnel_changed()

    def _on_bypass(self, row):
        self.settings.proxy_bypass_list = row.get_text().strip()
        self._reapply_proxy()

    def _on_reset_bypass(self, *_):
        self.bypass_row.set_text(DEFAULT_BYPASS_LIST)
        self.settings.proxy_bypass_list = DEFAULT_BYPASS_LIST
        self._reapply_proxy()

    def _reapply_proxy(self):
        # The bypass list is part of what the desktop was given, so a live session
        # is pointed at it again with the new list.
        self.vm.reapply_proxy()
        self.window.toast(_("Bypass list saved"))

    def _on_port(self, *_):
        if self._loading:
            return
        if self._port_timer:
            GLib.source_remove(self._port_timer)
        # A spin button moves one step per press; wait for the user to settle.
        self._port_timer = GLib.timeout_add(900, self._apply_ports)

    def _apply_ports(self):
        self._port_timer = 0
        self.settings.local_http_proxy_port = int(self.http_port_row.get_value())
        self.settings.local_socks_proxy_port = int(self.socks_port_row.get_value())
        self._tunnel_changed()
        return GLib.SOURCE_REMOVE

    def _on_autostart(self, row, _pspec):
        if self._loading:
            return
        if not autostart.set_enabled(row.get_active()):
            self._loading = True
            row.set_active(autostart.is_enabled())
            self._loading = False
            self.window.toast(_("Could not change the startup entry"))
        self.settings.start_at_login = autostart.is_enabled()
        self.settings.save()

    def _on_theme(self, row, _pspec):
        if self._loading:
            return
        self.settings.theme = AppTheme(row.get_selected())
        self.settings.save()
        theme.apply(self.settings.theme)

    def _open_folder(self, _row, path):
        if path is None:
            engine = paths.engine()
            path = engine.binary.parent if engine.binary else engine.data_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(path)))
        launcher.launch(self.window, None, None, None)
