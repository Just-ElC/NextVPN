"""
Optional "launch when I sign in" entry: an XDG autostart file in the user's own
config directory. Honoured by GNOME, Plasma, XFCE, Cinnamon and anything else
that follows the freedesktop autostart spec; never needs root, and only ever
affects the current user.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .. import APP_ID, APP_NAME
from . import paths


def entry_path() -> Path:
    return paths.user_config_home() / "autostart" / f"{APP_ID}.desktop"


def is_enabled(path: Path | None = None) -> bool:
    path = path or entry_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip().replace(" ", "")
        if line.lower() in ("hidden=true", "x-gnome-autostart-enabled=false"):
            return False
    return True


def launch_command() -> list[str]:
    """
    How a fresh session should start us. The bare name when it resolves to this
    very launcher, so the entry survives an upgrade that moves the files (every
    Nix rebuild does); otherwise the launcher's absolute path.
    """
    launcher = os.environ.get("NEXTVPN_LAUNCHER")
    if launcher and os.path.isfile(launcher):
        on_path = shutil.which("nextvpn")
        if on_path and os.path.realpath(on_path) == os.path.realpath(launcher):
            return ["nextvpn"]
        return [os.path.abspath(launcher)]

    on_path = shutil.which("nextvpn")
    if on_path:
        return ["nextvpn"]
    return [sys.executable, "-m", "nextvpn"]


def _exec_quote(arg: str) -> str:
    """Quoting for the Exec key, which is stricter than a shell's."""
    if arg and all(c.isalnum() or c in "-_./:=+,@" for c in arg):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def render(command: list[str]) -> str:
    exec_line = " ".join(_exec_quote(a) for a in command + ["--minimised"])
    # A source checkout started with "python -m" needs to run from the right place.
    working_dir = ""
    if command[1:3] == ["-m", "nextvpn"]:
        working_dir = f"Path={paths.SOURCE_DIR}\n"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Start NextVPN in the notification area\n"
        f"Exec={exec_line}\n"
        f"{working_dir}"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
    )


def set_enabled(enabled: bool, path: Path | None = None, command: list[str] | None = None) -> bool:
    path = path or entry_path()
    try:
        if not enabled:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return True

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(render(command or launch_command()), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False

