"""The exit country picker."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ..core.i18n import _
from ..core.regions import RegionInfo
from .viewmodel import MainViewModel
from .widgets import code_badge, set_badge


class RegionRow(Adw.ActionRow):
    def __init__(self, region: RegionInfo):
        super().__init__(title=region.name, activatable=True)
        self.region = region
        if region.is_country:
            self.set_subtitle(region.code)

        badge, label, image = code_badge("small")
        set_badge(label, image, region.code)
        self.add_prefix(badge)

        self.check = Gtk.Image(icon_name="object-select-symbolic", visible=False)
        self.check.add_css_class("accent")
        self.add_suffix(self.check)

    def matches(self, query: str) -> bool:
        if not query:
            return True
        q = query.casefold()
        return q in self.region.name.casefold() or q in self.region.code.casefold()


class RegionsPage(Gtk.Box):
    def __init__(self, vm: MainViewModel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.vm = vm

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.add_css_class("page")

        title = Gtk.Label(label=_("Locations"), xalign=0)
        title.add_css_class("title-1")
        content.append(title)
        about = Gtk.Label(label=_("Where your traffic leaves the network. Changing this while connected "
                                  "rebuilds the tunnel."), xalign=0, wrap=True)
        about.add_css_class("dim-label")
        content.append(about)

        self.search = Gtk.SearchEntry(placeholder_text=_("Search locations"))
        self.search.connect("search-changed", lambda *_: self._filter())
        # Enter takes the first match, so "ger", Enter is a complete choice.
        self.search.connect("activate", self._on_search_activate)
        content.append(self.search)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START)
        self.list.add_css_class("boxed-list")
        self.list.set_filter_func(lambda row: row.matches(self.search.get_text().strip()))
        self.list.connect("row-activated", self._on_activated)

        self.placeholder = Adw.StatusPage(icon_name="find-location-symbolic")
        self.placeholder.add_css_class("compact")
        self.list.set_placeholder(self.placeholder)
        content.append(self.list)

        # The engine reports the country list once it has read its server list,
        # so before the very first start there is only "Best performance".
        self.hint = Gtk.Label(wrap=True, xalign=0,
                              label=_("Countries appear here once the tunnel engine has started. Until then, "
                                      "Best performance lets the engine choose."))
        self.hint.add_css_class("dim-label")
        self.hint.add_css_class("caption")
        content.append(self.hint)

        clamp = Adw.Clamp(maximum_size=860, child=content)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=clamp)
        self.append(scroller)

        self._rows: list[RegionRow] = []
        self._rebuild()
        vm.connect("regions-changed", lambda *_: self._rebuild())
        vm.connect("changed", lambda *_: self._mark_selected())

    def _rebuild(self) -> None:
        for row in self._rows:
            self.list.remove(row)
        self._rows = [RegionRow(r) for r in self.vm.available_regions]
        for row in self._rows:
            self.list.append(row)
        self.hint.set_visible(not any(r.region.is_country for r in self._rows))
        self._mark_selected()
        self._filter()

    def _mark_selected(self) -> None:
        code = self.vm.selected_region.code
        for row in self._rows:
            row.check.set_visible(row.region.code == code)

    def _filter(self) -> None:
        query = self.search.get_text().strip()
        self.placeholder.set_title(_("No location matches “{query}”").format(query=query) if query else "")
        self.list.invalidate_filter()

    def _on_search_activate(self, *_):
        query = self.search.get_text().strip()
        if not query:
            return
        for row in self._rows:
            if row.matches(query):
                self.vm.select_region(row.region)
                return

    def _on_activated(self, _list, row: RegionRow) -> None:
        self.vm.select_region(row.region)

    def focus_search(self) -> None:
        self.search.grab_focus()
