"""
The connection page.

One grid, three equal columns, one gutter everywhere, the same composition as
the Windows build: the connect control, the session totals, the exit location
beside the throughput graph, the connection details, and any notices. Below
the narrow breakpoint the two-up row becomes a stack.
"""

from __future__ import annotations

from gi.repository import Adw, Gdk, GObject, Gtk

from ..core.i18n import _
from .viewmodel import MainViewModel
from .widgets import ConnectDial, ThroughputGraph, code_badge, set_badge


def _card(*css) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.add_css_class("card")
    box.add_css_class("tile")
    for c in css:
        box.add_css_class(c)
    return box


def _field(icon: str, caption: str, value_css: str) -> tuple[Gtk.Box, Gtk.Label]:
    card = _card()
    head = Gtk.Box(spacing=8)
    image = Gtk.Image(icon_name=icon)
    image.add_css_class("dim-label")
    head.append(image)
    label = Gtk.Label(label=caption, xalign=0, ellipsize=3)
    label.add_css_class("caption")
    label.add_css_class("dim-label")
    head.append(label)
    card.append(head)

    value = Gtk.Label(xalign=0, ellipsize=3, selectable=False)
    value.add_css_class(value_css)
    card.append(value)
    return card, value


class Notice(Gtk.Box):
    """An inline message strip, like the InfoBar the Windows build uses."""

    def __init__(self, kind: str, icon: str, closable: bool):
        super().__init__(spacing=12)
        self.add_css_class("notice")
        self.add_css_class(kind)
        self.set_visible(False)
        self.dismissed = False

        self.append(Gtk.Image(icon_name=icon, valign=Gtk.Align.START))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("heading")
        self.message = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.message.set_wrap_mode(2)  # word-char: engine errors carry long tokens
        text.append(self.title)
        text.append(self.message)
        self.append(text)

        self.action = Gtk.Button(valign=Gtk.Align.CENTER, visible=False)
        self.append(self.action)
        if closable:
            close = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text=_("Dismiss"))
            close.add_css_class("flat")
            close.add_css_class("circular")
            close.connect("clicked", self._dismiss)
            self.append(close)

    def _dismiss(self, *_):
        self.dismissed = True
        self.set_visible(False)

    def show(self, title: str, message: str, visible: bool) -> None:
        self.title.set_label(title)
        self.title.set_visible(bool(title))
        self.message.set_label(message)
        self.set_visible(visible and not self.dismissed)


class HomePage(Gtk.ScrolledWindow):
    STACK_BREAKPOINT = 760

    def __init__(self, vm: MainViewModel, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.vm = vm
        self.window = window

        clamp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        clamp.add_css_class("page")
        self.grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True,
                             hexpand=True)
        clamp.append(self.grid)
        holder = Adw.Clamp(maximum_size=1180, tightening_threshold=1000, child=clamp)
        self.set_child(holder)

        self._build_hero()
        self._build_totals()
        self._build_exit()
        self._build_graph()
        self._build_details()
        self._build_notices()

        self._stacked: bool | None = None
        self.set_stacked(False)

        vm.connect("changed", lambda *_: self.refresh())
        vm.connect("rates-changed", lambda *_: self.graph.set_samples(vm.rate_history))
        self.refresh()

    # ------------------------------------------------------------- build

    def _build_hero(self):
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        hero.add_css_class("card")
        hero.add_css_class("hero")
        hero.set_size_request(-1, 300)

        self.dial = ConnectDial()
        self.dial.button.connect("clicked", lambda *_: self.vm.toggle())
        hero.append(self.dial)

        self.heading = Gtk.Label(justify=Gtk.Justification.CENTER, ellipsize=3)
        self.heading.add_css_class("title-1")
        self.subtitle = Gtk.Label(justify=Gtk.Justification.CENTER, wrap=True, max_width_chars=60)
        self.subtitle.add_css_class("dim-label")
        hero.append(self.heading)
        hero.append(self.subtitle)

        # Two chips, only while a tunnel is up: what it is carried over and where
        # it comes out. They sit in a fixed-height row, so their appearance moves
        # nothing else on the page.
        chips = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        chips.set_size_request(-1, 30)
        self.protocol_chip, self.protocol_label = self._chip("network-vpn-symbolic")
        self.region_chip, self.region_label = self._chip("find-location-symbolic")
        chips.append(self.protocol_chip)
        chips.append(self.region_chip)
        hero.append(chips)

        self.hero = hero
        self.grid.attach(hero, 0, 0, 3, 1)

    @staticmethod
    def _chip(icon: str):
        chip = Gtk.Box(spacing=7, valign=Gtk.Align.CENTER)
        chip.add_css_class("pill")
        image = Gtk.Image(icon_name=icon, pixel_size=12)
        image.add_css_class("dim-label")
        chip.append(image)
        label = Gtk.Label()
        label.add_css_class("caption")
        chip.append(label)
        return chip, label

    def _build_totals(self):
        self.down_card, self.download_value = _field("network-receive-symbolic", _("Downloaded"), "stat-value")
        self.up_card, self.upload_value = _field("network-transmit-symbolic", _("Uploaded"), "stat-value")
        self.time_card, self.uptime_value = _field("document-open-recent-symbolic", _("Connected for"), "stat-value")
        self.grid.attach(self.down_card, 0, 1, 1, 1)
        self.grid.attach(self.up_card, 1, 1, 1, 1)
        self.grid.attach(self.time_card, 2, 1, 1, 1)

    def _build_exit(self):
        button = Gtk.Button(vexpand=True)
        button.add_css_class("card")
        button.add_css_class("exit-card")
        button.update_property([Gtk.AccessibleProperty.LABEL], [_("Change exit location")])
        button.connect("clicked", lambda *_: self.window.show_page("regions"))

        # Centred rather than left aligned, because this tile sits next to a tall
        # graph and would otherwise read as a mostly empty card.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        badge, self.exit_code, self.exit_icon = code_badge()
        box.append(badge)

        caption = Gtk.Label(label=_("Exit location"))
        caption.add_css_class("caption")
        caption.add_css_class("dim-label")
        box.append(caption)

        self.exit_name = Gtk.Label(justify=Gtk.Justification.CENTER, ellipsize=3, max_width_chars=22)
        self.exit_name.add_css_class("heading")
        box.append(self.exit_name)

        change = Gtk.Box(spacing=5, halign=Gtk.Align.CENTER)
        change_label = Gtk.Label(label=_("Change"))
        change_label.add_css_class("caption")
        change_label.add_css_class("accent")
        change.append(change_label)
        arrow = Gtk.Image(icon_name="go-next-symbolic", pixel_size=10)
        arrow.add_css_class("accent")
        change.append(arrow)
        box.append(change)

        button.set_child(box)
        self.exit_card = button

    def _build_graph(self):
        card = _card()
        card.set_vexpand(True)
        head = Gtk.Box(spacing=14)
        title = Gtk.Label(label=_("Throughput"), xalign=0, hexpand=True, ellipsize=3)
        title.add_css_class("caption")
        title.add_css_class("dim-label")
        head.append(title)
        self.down_rate = self._legend(head, "legend-down")
        self.up_rate = self._legend(head, "legend-up")
        card.append(head)

        self.graph = ThroughputGraph()
        card.append(self.graph)
        self.graph_card = card

    @staticmethod
    def _legend(parent: Gtk.Box, css: str) -> Gtk.Label:
        box = Gtk.Box(spacing=6)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("legend-dot")
        dot.add_css_class(css)
        box.append(dot)
        label = Gtk.Label()
        label.add_css_class("caption")
        label.add_css_class("numeric")
        box.append(label)
        parent.append(box)
        return label

    def _build_details(self):
        self.location_card, self.location_value = _field("find-location-symbolic", _("Your location"), "body")
        self.proxy_card, self.ports_value = _field("network-vpn-symbolic", _("Local proxy"), "body")
        self.system_card, self.system_value = _field("emblem-system-symbolic", _("Mode"), "body")
        for card in (self.location_card, self.proxy_card, self.system_card):
            card.add_css_class("subtle")

        # Terminals ignore desktop proxy settings; this hands over the variables.
        head = self.proxy_card.get_first_child()
        self.copy_env = Gtk.Button(icon_name="edit-copy-symbolic", halign=Gtk.Align.END, hexpand=True,
                                   tooltip_text=_("Copy proxy settings for a terminal"))
        self.copy_env.add_css_class("flat")
        self.copy_env.add_css_class("circular")
        self.copy_env.add_css_class("tiny")
        self.copy_env.connect("clicked", self._copy_env)
        head.append(self.copy_env)

    def _build_notices(self):
        self.notices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self.fault_notice = Notice("error", "dialog-error-symbolic", closable=False)
        self.fault_notice.action.set_label(_("Activity"))
        self.fault_notice.action.set_visible(True)
        self.fault_notice.action.connect("clicked", lambda *_: self.window.show_page("log"))

        # Landing pages and upstream upgrade offers are only logged: the
        # sponsor's page and Psiphon's own Windows client version mean nothing
        # to someone using this app.
        self.notices.append(self.fault_notice)

    # --------------------------------------------------------- responsive

    def set_stacked(self, stacked: bool) -> None:
        if stacked == self._stacked:
            return
        self._stacked = stacked

        for child in (self.exit_card, self.graph_card, self.location_card, self.proxy_card,
                      self.system_card, self.notices):
            if child.get_parent() is self.grid:
                self.grid.remove(child)

        if stacked:
            self.grid.attach(self.exit_card, 0, 2, 3, 1)
            self.grid.attach(self.graph_card, 0, 3, 3, 1)
            self.grid.attach(self.location_card, 0, 4, 3, 1)
            self.grid.attach(self.proxy_card, 0, 5, 3, 1)
            self.grid.attach(self.system_card, 0, 6, 3, 1)
            self.grid.attach(self.notices, 0, 7, 3, 1)
            self.heading.remove_css_class("title-1")
            self.heading.add_css_class("title-2")
        else:
            self.grid.attach(self.exit_card, 0, 2, 1, 1)
            self.grid.attach(self.graph_card, 1, 2, 2, 1)
            self.grid.attach(self.location_card, 0, 4, 1, 1)
            self.grid.attach(self.proxy_card, 1, 4, 1, 1)
            self.grid.attach(self.system_card, 2, 4, 1, 1)
            self.grid.attach(self.notices, 0, 5, 3, 1)
            self.heading.remove_css_class("title-2")
            self.heading.add_css_class("title-1")

    # ------------------------------------------------------------ refresh

    def refresh(self) -> None:
        vm = self.vm
        self.dial.set_state(vm.state, vm.action_label, vm.can_toggle)
        _set(self.heading, vm.status_text)
        _set(self.subtitle, vm.status_subtitle)

        self.protocol_chip.set_visible(vm.is_connected)
        self.region_chip.set_visible(vm.is_connected)
        _set(self.protocol_label, vm.protocol_text)
        _set(self.region_label, vm.selected_region.display)

        _set(self.download_value, vm.download_text)
        _set(self.upload_value, vm.upload_text)
        _set(self.uptime_value, vm.uptime_text)
        _set(self.down_rate, vm.down_rate_text)
        _set(self.up_rate, vm.up_rate_text)

        set_badge(self.exit_code, self.exit_icon, vm.selected_region.code)
        _set(self.exit_name, vm.selected_region.name)

        _set(self.location_value, vm.client_region_text)
        _set(self.ports_value, vm.ports_text)
        _set(self.system_value, vm.mode_text)
        if self.system_value.get_tooltip_text() != vm.mode_text:
            self.system_value.set_tooltip_text(vm.mode_text)
        self.copy_env.set_visible(bool(vm.shell_exports))

        self.fault_notice.show(_("Could not connect"), vm.status_detail, vm.is_faulted)

    # ------------------------------------------------------------ actions

    def _copy_env(self, *_):
        text = self.vm.shell_exports
        if not text:
            return
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(GObject.Value(str, text)))
        self.window.toast(_("Copied. Paste it into a terminal to send its traffic through the tunnel."))


def _set(label: Gtk.Label, text: str) -> None:
    if label.get_label() != text:
        label.set_label(text)
