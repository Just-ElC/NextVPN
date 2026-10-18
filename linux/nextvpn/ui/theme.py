"""Light/dark selection and the application stylesheet."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from ..core import paths
from ..core.settings import AppTheme

_providers: dict[str, Gtk.CssProvider] = {}

# Module-level functions from GTK 4.10; the StyleContext statics before that.
_add = getattr(Gtk, "style_context_add_provider_for_display", None) or Gtk.StyleContext.add_provider_for_display
_remove = (getattr(Gtk, "style_context_remove_provider_for_display", None)
           or Gtk.StyleContext.remove_provider_for_display)


def apply(theme: AppTheme) -> None:
    scheme = {
        AppTheme.LIGHT: Adw.ColorScheme.FORCE_LIGHT,
        AppTheme.DARK: Adw.ColorScheme.FORCE_DARK,
    }.get(theme, Adw.ColorScheme.DEFAULT)
    Adw.StyleManager.get_default().set_color_scheme(scheme)


def _load(name: str) -> Gtk.CssProvider:
    provider = Gtk.CssProvider()
    provider.load_from_path(str(paths.css_dir() / name))
    return provider


def install() -> None:
    """
    Loads the stylesheet, plus the dark variant whenever the dark style is in use.
    The brand accent is set the way the running libadwaita expects it: as CSS
    variables from 1.6, as named colours before.
    """
    display = Gdk.Display.get_default()
    if display is None:
        return

    _providers["base"] = _load("style.css")
    _add(display, _providers["base"], Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    modern = (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 6)
    _providers["accent-light"] = _load("accent-light-vars.css" if modern else "accent-light.css")
    _providers["accent-dark"] = _load("accent-dark-vars.css" if modern else "accent-dark.css")
    _providers["dark"] = _load("style-dark.css")

    manager = Adw.StyleManager.get_default()

    def update(*_):
        dark = manager.get_dark()
        for name, wanted in (("accent-light", not dark), ("accent-dark", dark), ("dark", dark)):
            provider = _providers[name]
            _remove(display, provider)
            if wanted:
                _add(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    manager.connect("notify::dark", update)
    update()
