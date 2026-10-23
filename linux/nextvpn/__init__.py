"""NextVPN for Linux: a GTK 4 / libadwaita interface over psiphon-tunnel-core."""

APP_ID = "io.github.just_elc.NextVPN"
APP_NAME = "NextVPN"

try:
    # Written by meson at install time. Absent when running from a source checkout.
    from . import buildconfig as _build
    VERSION = _build.VERSION
except ImportError:  # pragma: no cover - depends on how the app was started
    _build = None
    VERSION = "1.1.0"
