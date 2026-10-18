"""
User-facing settings, persisted as JSON in the config directory.
Everything here maps onto either the generated tunnel-core config or local UI behaviour.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from enum import IntEnum
from pathlib import Path

from . import paths


class AppTheme(IntEnum):
    SYSTEM = 0
    LIGHT = 1
    DARK = 2


class ClientPlatform:
    """
    How the client describes itself to the Psiphon servers.

    The servers sort clients by the start of this string alone: anything that
    begins with "Windows" is a Windows client, everything else is "Other". The
    sponsor and channel in base.config are the Windows client's, and the
    server-side tactics, landing pages and protocol tuning for them are keyed on
    that answer. Reporting "Windows" therefore gets this build exactly the
    treatment NextVPN for Windows gets; "Linux" is the honest alternative and
    may be served a different, less tuned set.
    """

    WINDOWS = "windows"
    LINUX = "linux"
    ALL = (WINDOWS, LINUX)


#: Loopback, the RFC1918 ranges, link-local, IPv6 unique-local and mDNS names,
#: written the way GNOME and KDE both read them.
DEFAULT_BYPASS_LIST = (
    "localhost, 127.0.0.0/8, ::1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, "
    "169.254.0.0/16, fc00::/7, fe80::/10, *.local"
)


def parse_bypass_list(text: str) -> list[str]:
    """Splits on commas, semicolons or whitespace; drops blanks and repeats."""
    seen: list[str] = []
    for item in re.split(r"[,;\s]+", text or ""):
        if item and item not in seen:
            seen.append(item)
    return seen


@dataclass
class AppSettings:
    # --- Tunnel ----------------------------------------------------------
    #: Two-letter egress country code. Empty string means "best available".
    egress_region: str = ""
    #: Restrict to these tunnel protocols. Empty means "let the engine choose".
    limit_tunnel_protocols: list[str] = field(default_factory=list)
    #: 0 = let the engine pick a free port.
    local_http_proxy_port: int = 0
    local_socks_proxy_port: int = 0
    #: Optional upstream proxy, e.g. "http://user:pass@host:port".
    upstream_proxy_url: str = ""
    #: Relax the engine's dial timeouts, for very slow or lossy links.
    disable_timeouts: bool = False
    #: Split tunnelling: traffic for your own country leaves directly.
    split_tunnel_own_region: bool = False
    #: See ClientPlatform.
    client_platform: str = ClientPlatform.WINDOWS

    # --- System integration ----------------------------------------------
    #: Point GNOME and KDE at the local proxy while connected.
    set_system_proxy: bool = True
    #: Hosts that bypass the tunnel. Commas, CIDR ranges and * wildcards.
    proxy_bypass_list: str = DEFAULT_BYPASS_LIST

    start_at_login: bool = False
    connect_on_launch: bool = False
    start_minimised: bool = False
    minimise_to_tray: bool = True

    # --- Appearance --------------------------------------------------------
    theme: AppTheme = AppTheme.SYSTEM

    # --- Window geometry ----------------------------------------------------
    # Wayland gives a client no say over where its window goes, so only the
    # size and the maximised state are remembered.
    window_width: int = 0
    window_height: int = 0
    window_maximised: bool = False

    # --- Remembered state ---------------------------------------------------
    #: The last list of exit countries the engine reported, so the picker is not
    #: empty before the first connection of a session.
    known_regions: list[str] = field(default_factory=list)

    # --- Persistence -------------------------------------------------------

    @staticmethod
    def path() -> Path:
        return paths.settings_file()

    @classmethod
    def load(cls) -> "AppSettings":
        return cls.load_from(cls.path())

    def save(self) -> None:
        self.save_to(self.path())

    @classmethod
    def load_from(cls, path: os.PathLike | str) -> "AppSettings":
        """Reads settings from an explicit file. Anything unreadable yields defaults."""
        settings = cls()
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            # Corrupt or unreadable settings must never stop the app from starting.
            return settings

        if not isinstance(raw, dict):
            return settings

        for f in fields(cls):
            if f.name not in raw:
                continue
            value = _coerce(getattr(settings, f.name), raw[f.name])
            if value is not None:
                setattr(settings, f.name, value)

        if settings.client_platform not in ClientPlatform.ALL:
            settings.client_platform = ClientPlatform.WINDOWS
        return settings

    def save_to(self, path: os.PathLike | str) -> None:
        """
        Writes to a temporary file and moves it into place, so a settings file is
        never left half written if the machine loses power mid-save. The file is
        private to the user: an upstream proxy URL can carry a password.
        """
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(self)
            data["theme"] = int(self.theme)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except OSError:
            # Best effort: losing a settings write is not worth crashing over.
            try:
                tmp.unlink()
            except OSError:
                pass


def _coerce(default, value):
    """
    Accepts a stored value only when it has the type of the default. A file
    edited by hand, or written by a future version, then degrades field by field
    instead of all at once.
    """
    if isinstance(default, AppTheme):
        if isinstance(value, int) and not isinstance(value, bool):
            try:
                return AppTheme(value)
            except ValueError:
                return None
        return None
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(default, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if isinstance(default, str):
        return value if isinstance(value, str) else None
    if isinstance(default, list):
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return list(value)
        return None
    return None
