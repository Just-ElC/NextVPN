"""Activity: live output from the tunnel engine."""

from __future__ import annotations

from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Pango

from ..core.i18n import _
from ..core.policy import NoticeLevel
from .viewmodel import LogEntry, MainViewModel


class LogPage(Gtk.Box):
    def __init__(self, vm: MainViewModel, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.vm = vm
        self.window = window

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, vexpand=True)
        content.add_css_class("page")

        title = Gtk.Label(label=_("Activity"), xalign=0)
        title.add_css_class("title-1")
        content.append(title)
        about = Gtk.Label(label=_("Live output from the tunnel engine. Useful when a network is blocking "
                                  "connections."), xalign=0, wrap=True)
        about.add_css_class("dim-label")
        content.append(about)

        bar = Gtk.Box(spacing=10)
        verbose = Gtk.Switch(valign=Gtk.Align.CENTER, active=vm.show_diagnostics)
        verbose.connect("notify::active", lambda s, _p: vm.set_show_diagnostics(s.get_active()))
        label = Gtk.Label(label=_("Verbose diagnostics"), mnemonic_widget=verbose, wrap=True, xalign=0)
        bar.append(verbose)
        bar.append(label)
        bar.append(Gtk.Box(hexpand=True))

        copy = Gtk.Button()
        copy.set_child(Adw.ButtonContent(icon_name="edit-copy-symbolic", label=_("Copy all"), can_shrink=True))
        copy.set_tooltip_text(_("Copy all"))
        copy.connect("clicked", self._copy)
        bar.append(copy)
        clear = Gtk.Button()
        clear.set_child(Adw.ButtonContent(icon_name="user-trash-symbolic", label=_("Clear"), can_shrink=True))
        clear.set_tooltip_text(_("Clear"))
        clear.connect("clicked", lambda *_: vm.clear_log())
        bar.append(clear)
        content.append(bar)

        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=12, right_margin=12,
                                 top_margin=10, bottom_margin=10)
        self.view.add_css_class("log-view")
        self.buffer = self.view.get_buffer()
        self._tags = {
            "time": self.buffer.create_tag("time", foreground_rgba=_rgba("#8A8F98")),
            NoticeLevel.INFO: self.buffer.create_tag("info", foreground_rgba=_rgba("#3D8FD8"),
                                                     weight=Pango.Weight.BOLD),
            NoticeLevel.WARNING: self.buffer.create_tag("warning", foreground_rgba=_rgba("#C98A1B"),
                                                        weight=Pango.Weight.BOLD),
            NoticeLevel.ERROR: self.buffer.create_tag("error", foreground_rgba=_rgba("#E05252"),
                                                      weight=Pango.Weight.BOLD),
        }
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.view)
        self.scroller.add_css_class("card")
        self.scroller.add_css_class("log-card")

        empty = Adw.StatusPage(icon_name="view-list-symbolic", title=_("Nothing yet"),
                               description=_("Everything the tunnel engine reports appears here as it happens."))
        empty.add_css_class("compact")

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(empty, "empty")
        self.stack.add_named(self.scroller, "log")
        content.append(self.stack)

        clamp = Adw.Clamp(maximum_size=1180, child=content, vexpand=True)
        self.append(clamp)

        self._lines = 0
        for entry in vm.log:
            self._append(entry)
        self._update_empty()

        vm.connect("log-appended", lambda _vm, e: self._on_appended(e))
        vm.connect("log-cleared", lambda *_: self._on_cleared())

    def _at_bottom(self) -> bool:
        adj = self.scroller.get_vadjustment()
        return adj.get_value() >= adj.get_upper() - adj.get_page_size() - 24

    def _on_appended(self, entry: LogEntry) -> None:
        follow = self._at_bottom()
        self._append(entry)
        self._update_empty()
        if follow:
            GLib.idle_add(self._scroll_to_end)

    def _append(self, entry: LogEntry) -> None:
        end = self.buffer.get_end_iter()
        self.buffer.insert_with_tags(end, entry.time_text + "  ", self._tags["time"])
        end = self.buffer.get_end_iter()
        self.buffer.insert_with_tags(end, f"{entry.type:<24} ", self._tags[entry.level])
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, entry.message + "\n")
        self._lines += 1

        # Same cap as the model, so the view never holds more than the log does.
        while self._lines > self.vm.MAX_LOG_ENTRIES:
            start = self.buffer.get_start_iter()
            second = self.buffer.get_iter_at_line(1)
            second = second[1] if isinstance(second, tuple) else second
            self.buffer.delete(start, second)
            self._lines -= 1

    def _scroll_to_end(self) -> bool:
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return GLib.SOURCE_REMOVE

    def _on_cleared(self) -> None:
        self.buffer.set_text("")
        self._lines = 0
        self._update_empty()

    def _update_empty(self) -> None:
        self.stack.set_visible_child_name("log" if self._lines else "empty")

    def _copy(self, *_):
        text = self.vm.log_text()
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(GObject.Value(str, text)))
        self.window.toast(_("Activity copied"))


def _rgba(spec: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    rgba.parse(spec)
    return rgba
