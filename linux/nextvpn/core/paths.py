"""
Every path the app touches. Deliberately explicit: per-user state lives in the
XDG directories, and no binary is ever self-extracted, self-replaced or
self-deleted.

  $XDG_CONFIG_HOME/nextvpn/settings.json       user settings
  $XDG_DATA_HOME/nextvpn/tunnel/               the engine's datastore
  $XDG_DATA_HOME/nextvpn/runtime.config        generated engine config
  $XDG_DATA_HOME/nextvpn/proxy-backup.json     system proxy settings to restore

The engine itself is looked up in this order:

  1. $NEXTVPN_ENGINE                           an explicit binary
  2. the path meson recorded at install time   (/usr/libexec/nextvpn/...)
  3. linux/engine/ in a source checkout
  4. psiphon-tunnel-core on $PATH

and its two data files (base.config, server_list.dat) from $NEXTVPN_ENGINE_DIR,
the installed data directory, or engine/ at the top of a source checkout, the
same files the Windows build ships.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import _build

PACKAGE_DIR = Path(__file__).resolve().parent.parent
#: linux/ in a source checkout. Meaningless once installed, and only used when
#: the files it would point at actually exist.
SOURCE_DIR = PACKAGE_DIR.parent
REPO_DIR = SOURCE_DIR.parent

ENGINE_NAME = "psiphon-tunnel-core"


def _xdg(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "")
    # The spec says relative values are invalid and must be ignored.
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "nextvpn"


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "nextvpn"


def user_config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def settings_file() -> Path:
    return config_dir() / "settings.json"


def tunnel_data_dir() -> Path:
    return data_dir() / "tunnel"


def runtime_config_file() -> Path:
    return data_dir() / "runtime.config"


def proxy_backup_file() -> Path:
    return data_dir() / "proxy-backup.json"


def is_source_checkout() -> bool:
    return _build is None


def po_dir() -> Path | None:
    candidate = SOURCE_DIR / "po"
    return candidate if candidate.is_dir() else None


def locale_dir() -> str | None:
    return getattr(_build, "LOCALEDIR", None) or None


def icons_dir() -> Path | None:
    """A directory laid out as an icon theme, for the tray host to search."""
    installed = getattr(_build, "ICONS_DIR", None)
    if installed and os.path.isdir(installed):
        return Path(installed)
    candidate = SOURCE_DIR / "data" / "icons"
    return candidate if candidate.is_dir() else None


def shared_icon_exists(name: str, context: str = "status") -> bool:
    """
    Whether an icon by this name is installed where other programs look for
    icons: the user's and the system's data directories, NixOS profiles
    included. A tray host is a separate program with its own environment, so
    directories only this process was pointed at (a Nix store path added by the
    launcher wrapper, or this source checkout) do not count.
    """
    dirs = [str(_xdg("XDG_DATA_HOME", ".local/share"))]
    dirs += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    for d in dirs:
        if not d or d.startswith("/nix/store/"):
            continue
        root = Path(d) / "icons" / "hicolor"
        if (root / "scalable" / context / f"{name}.svg").is_file():
            return True
        if any(root.glob(f"*/{context}/{name}.png")):
            return True
    return False


def css_dir() -> Path:
    return PACKAGE_DIR / "ui"


@dataclass(frozen=True)
class EnginePaths:
    binary: Path | None
    base_config: Path
    server_list: Path

    @property
    def data_dir(self) -> Path:
        return self.base_config.parent


def _machine() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)


def _engine_data_dir() -> Path:
    override = os.environ.get("NEXTVPN_ENGINE_DIR")
    if override:
        return Path(override)

    installed = getattr(_build, "ENGINE_DATA_DIR", None)
    if installed and os.path.isdir(installed):
        return Path(installed)

    return REPO_DIR / "engine"


def _engine_binary(data: Path) -> Path | None:
    candidates: list[Path] = []

    override = os.environ.get("NEXTVPN_ENGINE")
    if override:
        # An explicit choice is final: falling back silently would run
        # something other than what was asked for.
        return Path(override)

    installed = getattr(_build, "ENGINE_BINARY", None)
    if installed:
        candidates.append(Path(installed))

    machine = _machine()
    candidates += [
        data / ENGINE_NAME,
        SOURCE_DIR / "engine" / f"{ENGINE_NAME}-{machine}",
        SOURCE_DIR / "engine" / ENGINE_NAME,
    ]

    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path

    found = shutil.which(ENGINE_NAME)
    return Path(found) if found else None


def engine() -> EnginePaths:
    data = _engine_data_dir()
    return EnginePaths(
        binary=_engine_binary(data),
        base_config=data / "base.config",
        server_list=data / "server_list.dat",
    )
