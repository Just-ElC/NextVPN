"""Entry point. Checks the toolkit is there before importing anything that needs it."""

from __future__ import annotations

import sys

from .core import i18n, paths

MISSING_TOOLKIT = """\
NextVPN needs GTK 4, libadwaita and PyGObject. Install them with:

  Fedora:           sudo dnf install python3-gobject gtk4 libadwaita
  Arch / CachyOS:   sudo pacman -S python-gobject python-cairo gtk4 libadwaita
  Debian / Ubuntu:  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
  NixOS:            nix run github:Just-ElC/NextVPN

({error})
"""


def main(argv=None) -> int:
    i18n.setup(paths.locale_dir(), paths.po_dir())

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
        import cairo  # noqa: F401
    except (ImportError, ValueError) as error:
        sys.stderr.write(MISSING_TOOLKIT.format(error=error))
        return 1

    from .ui.application import run
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
