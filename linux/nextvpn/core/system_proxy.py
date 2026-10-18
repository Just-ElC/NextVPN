"""
Points the desktop at the tunnel's local proxy and puts the previous settings
back afterwards: the Linux counterpart of setting the WinINet proxy on Windows.

Two stores are written, because Linux desktops keep this in two places:

  GNOME  GSettings org.gnome.system.proxy. Read by GNOME, Cinnamon, Budgie,
         Pantheon, every GIO application, Chromium-based browsers on those
         desktops and Firefox with "use system proxy settings".
  KDE    ~/.config/kioslaverc, [Proxy Settings]. Read by Plasma, KDE
         applications and Chromium-based browsers under Plasma.

Each one is only touched when it exists on this machine. The previous values
are written to disk before anything is changed, so a crash or a power cut
cannot leave the machine pointing at a dead local port with no way back:
recover_if_stale() repairs that on the next start. Settings the user changed
by hand while connected are left alone rather than overwritten on the way out.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .i18n import _
from .settings import parse_bypass_list

LOOPBACK = "127.0.0.1"


@dataclass(frozen=True)
class ProxyTarget:
    http_port: int
    socks_port: int
    bypass: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {"http": self.http_port, "socks": self.socks_port, "bypass": list(self.bypass)}

    @staticmethod
    def from_json(data) -> "ProxyTarget | None":
        if not isinstance(data, dict):
            return None
        http, socks = data.get("http"), data.get("socks")
        if not isinstance(http, int) or not isinstance(socks, int):
            return None
        bypass = data.get("bypass") if isinstance(data.get("bypass"), list) else []
        return ProxyTarget(http, socks, tuple(str(b) for b in bypass))


@dataclass
class ApplyResult:
    applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.applied)


def describe(http_port: int, socks_port: int) -> str:
    """The proxy as a person would write it, for the activity log."""
    parts = []
    if http_port > 0:
        parts.append(f"HTTP(S) {LOOPBACK}:{http_port}")
    if socks_port > 0:
        parts.append(f"SOCKS {LOOPBACK}:{socks_port}")
    return ", ".join(parts)


def shell_exports(http_port: int, socks_port: int) -> str:
    """
    The same proxy for a terminal. Command-line tools read these variables and
    nothing else, and no program can change them for a shell that is already
    running, so they are offered for copying instead.
    """
    if http_port <= 0 and socks_port <= 0:
        return ""
    parts = []
    if http_port > 0:
        url = f"http://{LOOPBACK}:{http_port}"
        parts += [f"http_proxy={url}", f"https_proxy={url}", f"HTTP_PROXY={url}", f"HTTPS_PROXY={url}"]
    if socks_port > 0:
        url = f"socks5h://{LOOPBACK}:{socks_port}"
        parts += [f"all_proxy={url}", f"ALL_PROXY={url}"]
    parts += ["no_proxy=localhost,127.0.0.1,::1", "NO_PROXY=localhost,127.0.0.1,::1"]
    return "export " + " ".join(parts)


# =================================================================== GNOME

class GnomeBackend:
    name = "gnome"
    SCHEMA = "org.gnome.system.proxy"
    #: key -> captured; everything apply() writes is in here, so restore() puts
    #: back exactly what was there.
    ROOT_KEYS = ("mode", "ignore-hosts", "use-same-proxy", "autoconfig-url")
    CHILD_KEYS = {
        "http": ("host", "port", "enabled", "use-authentication"),
        "https": ("host", "port"),
        "ftp": ("host", "port"),
        "socks": ("host", "port"),
    }

    def __init__(self, settings_backend=None):
        #: An explicit Gio.SettingsBackend; tests pass a memory backend.
        self._backend = settings_backend

    @property
    def label(self) -> str:
        return _("GNOME")

    def _gio(self):
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        return Gio, GLib

    def _settings(self, schema: str):
        Gio, _GLib = self._gio()
        if self._backend is not None:
            return Gio.Settings.new_with_backend(schema, self._backend)
        return Gio.Settings.new(schema)

    def available(self) -> bool:
        try:
            Gio, _GLib = self._gio()
        except (ImportError, ValueError):
            return False

        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup(self.SCHEMA, True) is None:
            return False
        if self._backend is None:
            # Without dconf, GSettings silently keeps changes in memory: nothing
            # else on the desktop would ever see them.
            backend = Gio.SettingsBackend.get_default()
            if "Memory" in type(backend).__name__ or "Null" in type(backend).__name__:
                return False
        return True

    def _schemas(self):
        yield self.SCHEMA, self.ROOT_KEYS
        for child, keys in self.CHILD_KEYS.items():
            yield f"{self.SCHEMA}.{child}", keys

    def capture(self) -> dict:
        saved: dict = {}
        for schema, keys in self._schemas():
            s = self._settings(schema)
            saved[schema] = {}
            for key in keys:
                value = s.get_value(key)
                saved[schema][key] = [value.get_type_string(), value.unpack()]
        return saved

    def apply(self, target: ProxyTarget) -> None:
        Gio, GLib = self._gio()
        socks_host = LOOPBACK if target.socks_port > 0 else ""

        values = {
            f"{self.SCHEMA}.http": {"host": LOOPBACK, "port": target.http_port,
                                    "enabled": True, "use-authentication": False},
            f"{self.SCHEMA}.https": {"host": LOOPBACK, "port": target.http_port},
            f"{self.SCHEMA}.ftp": {"host": "", "port": 0},
            f"{self.SCHEMA}.socks": {"host": socks_host, "port": max(0, target.socks_port)},
        }
        for schema, keys in values.items():
            s = self._settings(schema)
            s.delay()
            for key, value in keys.items():
                if isinstance(value, bool):
                    s.set_boolean(key, value)
                elif isinstance(value, int):
                    s.set_int(key, value)
                else:
                    s.set_string(key, value)
            s.apply()

        # The mode goes last, so nothing ever reads "manual" with stale hosts.
        root = self._settings(self.SCHEMA)
        root.delay()
        root.set_strv("ignore-hosts", list(target.bypass))
        root.set_boolean("use-same-proxy", False)
        root.set_string("mode", "manual")
        root.apply()
        Gio.Settings.sync()

    def restore(self, saved: dict) -> None:
        Gio, GLib = self._gio()
        # Root first this time, so the mode leaves "manual" before the hosts go.
        order = [self.SCHEMA] + [s for s in saved if s != self.SCHEMA]
        for schema in order:
            keys = saved.get(schema)
            if not isinstance(keys, dict):
                continue
            s = self._settings(schema)
            s.delay()
            for key, (type_string, value) in keys.items():
                try:
                    s.set_value(key, GLib.Variant(type_string, value))
                except (TypeError, ValueError):
                    s.reset(key)
            s.apply()
        Gio.Settings.sync()

    def is_ours(self, target: ProxyTarget) -> bool:
        root = self._settings(self.SCHEMA)
        http = self._settings(f"{self.SCHEMA}.http")
        return (root.get_string("mode") == "manual"
                and http.get_string("host") == LOOPBACK
                and http.get_int("port") == target.http_port)


# ===================================================================== KDE

class KdeBackend:
    name = "kde"
    GROUP = "Proxy Settings"
    KEYS = ("ProxyType", "httpProxy", "httpsProxy", "ftpProxy", "socksProxy",
            "NoProxyFor", "ReversedException")
    MANUAL = "1"

    def __init__(self, path: os.PathLike | str | None = None, environ=os.environ, notify: bool = True):
        self._path = Path(path) if path else None
        self._environ = environ
        self._notify = notify

    @property
    def label(self) -> str:
        return _("KDE")

    @property
    def path(self) -> Path:
        return self._path or (paths.user_config_home() / "kioslaverc")

    def is_kde_session(self) -> bool:
        desktop = self._environ.get("XDG_CURRENT_DESKTOP", "") + ":" + self._environ.get("XDG_SESSION_DESKTOP", "")
        return "KDE" in desktop.upper().split(":") or bool(self._environ.get("KDE_FULL_SESSION"))

    def available(self) -> bool:
        return self.is_kde_session() or self.path.is_file()

    @staticmethod
    def proxy_url(scheme: str, port: int) -> str:
        # Plasma writes host and port separated by a space, and reads it back that way.
        return f"{scheme}://{LOOPBACK} {port}" if port > 0 else ""

    def capture(self) -> dict:
        return get_kconfig_values(_read_lines(self.path), self.GROUP, self.KEYS)

    def apply(self, target: ProxyTarget) -> None:
        values = {
            "ProxyType": self.MANUAL,
            "httpProxy": self.proxy_url("http", target.http_port),
            "httpsProxy": self.proxy_url("http", target.http_port),
            "ftpProxy": "",
            "socksProxy": self.proxy_url("socks", target.socks_port),
            "NoProxyFor": ",".join(target.bypass),
            "ReversedException": "false",
        }
        self._write(values)

    def restore(self, saved: dict) -> None:
        self._write({k: (v if isinstance(v, str) else None) for k, v in saved.items() if k in self.KEYS})

    def is_ours(self, target: ProxyTarget) -> bool:
        current = self.capture()
        return (current.get("ProxyType") == self.MANUAL
                and current.get("httpProxy") == self.proxy_url("http", target.http_port))

    def _write(self, values: dict) -> None:
        lines = set_kconfig_values(_read_lines(self.path), self.GROUP, values)
        _atomic_write(self.path, "".join(lines))
        if self._notify:
            _notify_kio()


def _read_lines(path: Path) -> list[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.readlines()
    except FileNotFoundError:
        return []


def _key_of(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("[") or "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    # "key[$e]" and "key[ru]" carry flags or a locale; the key is what precedes them.
    return key.split("[", 1)[0].strip()


def _group_span(lines: list[str], group: str) -> tuple[int, int] | None:
    header = f"[{group}]"
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None:
            if stripped == header:
                start = i
        elif stripped.startswith("["):
            return start, i
    return (start, len(lines)) if start is not None else None


def get_kconfig_values(lines: list[str], group: str, keys) -> dict:
    """Raw values of keys in group, None for the ones that are absent."""
    result = {k: None for k in keys}
    span = _group_span(lines, group)
    if span is None:
        return result
    for line in lines[span[0] + 1:span[1]]:
        key = _key_of(line)
        if key in result and "[" not in line.split("=", 1)[0]:
            result[key] = line.split("=", 1)[1].rstrip("\r\n")
    return result


def set_kconfig_values(lines: list[str], group: str, values: dict) -> list[str]:
    """
    Sets (or, for None, removes) keys in one group and leaves every other line
    of the file exactly as it was.
    """
    lines = list(lines)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    span = _group_span(lines, group)
    if span is None:
        if not any(v is not None for v in values.values()):
            return lines
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"[{group}]\n")
        span = (len(lines) - 1, len(lines))

    start, end = span
    body = lines[start + 1:end]
    remaining = dict(values)
    new_body: list[str] = []
    for line in body:
        key = _key_of(line)
        if key in remaining:
            value = remaining.pop(key)
            if value is not None:
                new_body.append(f"{key}={value}\n")
            continue
        new_body.append(line)

    # New keys go before any blank lines that separate this group from the next.
    trailing: list[str] = []
    while new_body and not new_body[-1].strip():
        trailing.insert(0, new_body.pop())
    for key, value in remaining.items():
        if value is not None:
            new_body.append(f"{key}={value}\n")

    return lines[:start + 1] + new_body + trailing + lines[end:]


def _notify_kio() -> None:
    """Tells running KDE applications to re-read their proxy settings."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.emit_signal(None, "/KIO/Scheduler", "org.kde.KIO.Scheduler",
                        "reparseSlaveConfiguration", GLib.Variant("(s)", ("",)))
        bus.flush_sync(None)
    except Exception:  # noqa: BLE001 - no session bus is not an error here
        pass


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        pass
    tmp = path.with_name(f".{path.name}.nextvpn-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# ================================================================ manager

class SystemProxy:
    def __init__(self, backup_path: os.PathLike | str | None = None, backends=None):
        self._backup_path = Path(backup_path) if backup_path else None
        self._backends = backends if backends is not None else [GnomeBackend(), KdeBackend()]

    @property
    def backup_path(self) -> Path:
        return self._backup_path or paths.proxy_backup_file()

    def available_backends(self) -> list:
        result = []
        for backend in self._backends:
            try:
                if backend.available():
                    result.append(backend)
            except Exception:  # noqa: BLE001 - a broken store is just an absent one
                continue
        return result

    @property
    def is_applied(self) -> bool:
        return self.backup_path.is_file()

    def apply(self, http_port: int, socks_port: int, bypass_list: str) -> ApplyResult:
        result = ApplyResult()
        # Guards the case where Tunnels arrives before ListeningHttpProxyPort:
        # pointing the machine at port zero would break every connection.
        if http_port <= 0:
            return result

        target = ProxyTarget(http_port, max(0, socks_port), tuple(parse_bypass_list(bypass_list)))
        backends = self.available_backends()
        if not backends:
            return result

        existing = self._read_backup()
        # Only capture what is not already saved, so that reconnecting, or a port
        # change mid-session, can never overwrite the user's real settings with ours.
        saved = dict(existing[1]) if existing else {}
        for backend in backends:
            if backend.name in saved:
                continue
            try:
                saved[backend.name] = backend.capture()
            except Exception as ex:  # noqa: BLE001
                result.errors.append(f"{backend.label}: {ex}")

        if not saved:
            return result
        # Written before anything is changed: this is the way back after a crash.
        self._write_backup(target, saved)

        for backend in backends:
            if backend.name not in saved:
                continue
            try:
                backend.apply(target)
                result.applied.append(backend.name)
            except Exception as ex:  # noqa: BLE001
                result.errors.append(f"{backend.label}: {ex}")

        if not result.applied and existing is None:
            _try_delete(self.backup_path)
        return result

    def revert(self) -> bool:
        backup = self._read_backup()
        if backup is None:
            return False

        target, saved = backup
        by_name = {b.name: b for b in self._backends}
        for name, values in saved.items():
            backend = by_name.get(name)
            if backend is None:
                continue
            try:
                # Only undo what is still ours. If the user pointed the desktop
                # somewhere else while connected, that choice stands.
                if backend.available() and backend.is_ours(target):
                    backend.restore(values)
            except Exception:  # noqa: BLE001 - shutting down regardless
                continue

        _try_delete(self.backup_path)
        return True

    def recover_if_stale(self) -> bool:
        """
        Called at startup. If a previous run left the desktop pointing at one of
        our local ports, restore the saved settings so the network works again.
        """
        return self.revert()

    # ------------------------------------------------------------ backup

    def _read_backup(self) -> tuple[ProxyTarget, dict] | None:
        try:
            with open(self.backup_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        target = ProxyTarget.from_json(data.get("target"))
        saved = data.get("saved")
        if target is None or not isinstance(saved, dict):
            return None
        return target, saved

    def _write_backup(self, target: ProxyTarget, saved: dict) -> None:
        data = {"version": 1, "target": target.to_json(), "saved": saved}
        _atomic_write(self.backup_path, json.dumps(data, indent=2, ensure_ascii=False))


def _try_delete(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
