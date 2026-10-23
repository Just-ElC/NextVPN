"""
Owns the psiphon-tunnel-core child process and translates its notice stream into
state the interface can show.

The engine binary is run from where it is installed. It is never copied, never
extracted at runtime and never deleted afterwards.

What each notice means lives in TunnelTelemetry; this class owns only the
process lifetime and the state machine around it. Every event it raises is
raised on the main loop: the reader threads only parse, filter and post.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths, tunnel_config, vpn
from .i18n import _
from .notice import Notice, NoticeType
from .policy import NoticePolicy
from .settings import AppSettings, ConnectionMode
from .status import TunnelState
from .telemetry import TelemetrySignal, TunnelTelemetry

PR_SET_PDEATHSIG = 1

try:
    _prctl = ctypes.CDLL(None, use_errno=True).prctl
except (OSError, AttributeError):  # pragma: no cover - not glibc/musl Linux
    _prctl = None


class Signal:
    """A minimal multicast callback list."""

    def __init__(self):
        self._handlers: list[Callable] = []

    def connect(self, handler: Callable) -> Callable:
        self._handlers.append(handler)
        return handler

    def disconnect(self, handler: Callable) -> None:
        try:
            self._handlers.remove(handler)
        except ValueError:
            pass

    def emit(self, *args) -> None:
        for handler in list(self._handlers):
            handler(*args)


def glib_post(callback: Callable, *args) -> None:
    """Runs callback on the GLib main loop. The default way events leave a thread."""
    from gi.repository import GLib

    def run():
        callback(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(run)


@dataclass(frozen=True)
class EngineOutput:
    """A line the engine wrote that was not a notice: usually a Go panic."""

    text: str


class TunnelEngine:
    #: How long a stop waits for a graceful exit before killing the engine.
    STOP_GRACE_SECONDS = 5.0
    #: In VPN mode the helper also has to hand the tun back to NetworkManager.
    VPN_STOP_GRACE_SECONDS = 12.0
    #: Non-notice stderr lines forwarded to the log per run; a panic is long.
    MAX_RAW_LINES = 40

    def __init__(self, post: Callable = glib_post,
                 engine_paths: Callable[[], paths.EnginePaths] = paths.engine,
                 write_config: Callable[..., Path] = tunnel_config.write,
                 vpn_available: Callable[[], bool] = vpn.available,
                 vpn_helper: list[str] | None = None):
        self._post = post
        self._engine_paths = engine_paths
        self._write_config = write_config
        self._vpn_available = vpn_available
        #: What VPN mode runs in place of the engine; the engine's command line follows "--".
        self._vpn_helper = vpn_helper or [sys.executable, "-m", "nextvpn.core.vpn_helper"]
        #: Whether the current or last run is in VPN mode.
        self.vpn_mode = False
        #: Set when VPN mode was asked for and NetworkManager was not there.
        self.vpn_unavailable = False
        self._setup_error: str | None = None
        #: Held while stale VPN profiles are removed, so a helper being started
        #: never has its own fresh profile removed from under it.
        self._vpn_lock = threading.Lock()

        self.telemetry = TunnelTelemetry()
        self.state = TunnelState.DISCONNECTED
        #: Read by the reader thread to decide what is worth posting.
        self.verbose = False

        self._process: subprocess.Popen | None = None
        self._generation = 0
        self._stop_requested = False
        self._restart_with: AppSettings | None = None
        self._last_error: str | None = None
        self._first_raw: str | None = None

        self.state_changed = Signal()     # (state, detail)
        self.notice_received = Signal()   # (notice)
        self.output_received = Signal()   # (EngineOutput)
        self.stats_updated = Signal()     # ()
        self.regions_updated = Signal()   # ()

    # ----------------------------------------------------------- properties

    @property
    def stats(self):
        return self.telemetry.stats

    @property
    def is_running(self) -> bool:
        return self._process is not None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    # ---------------------------------------------------------------- start

    def start(self, settings: AppSettings) -> None:
        if self._process is not None:
            # Still on its way out: start again as soon as it has gone, rather than
            # racing a second engine onto the same datastore.
            if self._stop_requested:
                self._restart_with = settings
            return
        self._start(settings)

    def _start(self, settings: AppSettings) -> None:
        engine = self._engine_paths()

        if engine.binary is None or not engine.binary.is_file():
            self._fault(_("Tunnel engine not found. Install psiphon-tunnel-core "
                          "or point NEXTVPN_ENGINE at it."))
            return
        if not os.access(engine.binary, os.X_OK):
            self._fault(_("The tunnel engine at {path} is not executable.").format(path=engine.binary))
            return
        if not engine.server_list.is_file():
            self._fault(_("Embedded server list not found at {path}").format(path=engine.server_list))
            return

        wants_vpn = settings.connection_mode == ConnectionMode.VPN
        use_vpn = wants_vpn and self._vpn_available()
        self.vpn_unavailable = wants_vpn and not use_vpn

        try:
            if use_vpn:
                config_path = self._write_config(settings, engine, packet_tunnel=True)
            else:
                config_path = self._write_config(settings, engine)
        except (OSError, ValueError) as ex:
            self._fault(_("Could not prepare tunnel configuration: {error}").format(error=ex))
            return

        self.vpn_mode = use_vpn
        self.telemetry.reset()
        self._stop_requested = False
        self._last_error = None
        self._first_raw = None
        self._setup_error = None
        self._set_state(TunnelState.CONNECTING)

        # An engine left behind by a previous hard kill still holds the datastore
        # lock, which would make this start fail with no obvious cause.
        kill_orphaned_engines(config_path)

        parent = os.getpid()

        def child_setup():
            # Runs in the child between fork and exec. The kernel delivers SIGTERM
            # to the engine the moment this process dies, however it dies, so a
            # crashed or killed client can never leave an engine holding the
            # datastore lock. It is tied to the forking thread, which is why the
            # engine is only ever started from the main loop.
            if _prctl is not None:
                _prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
            if os.getppid() != parent:
                os._exit(1)

        argv = [str(engine.binary), "--config", str(config_path),
                "--serverList", str(engine.server_list)]
        env = None
        if use_vpn:
            # The helper sets the tun up, runs the engine on it and takes the tun
            # down again however the session ends. See vpn_helper.
            argv = [*self._vpn_helper, "--", *argv]
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                p for p in (str(paths.PACKAGE_DIR.parent), env.get("PYTHONPATH")) if p)
        try:
            with self._vpn_lock:
                proc = self._spawn(argv, env, config_path, child_setup)
                self._process = proc
        except OSError as ex:
            self._fault(_("Could not start the tunnel engine: {error}").format(error=ex.strerror or ex))
            return

        self._generation += 1
        generation = self._generation

        # Notices are newline-delimited JSON on stderr; stdout is drained so a
        # full pipe buffer can never stall the engine.
        pump = threading.Thread(target=self._pump, args=(proc, generation),
                                name="nextvpn-notices", daemon=True)
        drain = threading.Thread(target=_drain, args=(proc.stdout,),
                                 name="nextvpn-stdout", daemon=True)
        pump.start()
        drain.start()
        threading.Thread(target=self._watch_exit, args=(proc, generation, (pump, drain)),
                         name="nextvpn-exit", daemon=True).start()

    @staticmethod
    def _spawn(argv, env, config_path: Path, child_setup) -> subprocess.Popen:
        return subprocess.Popen(
            argv,
            env=env,
            cwd=str(config_path.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=child_setup,
            # Its own session: a Ctrl+C in the terminal that launched the app
            # is the app's to handle, not something to deliver to the engine.
            start_new_session=True,
            close_fds=True,
        )

    def recover_vpn(self) -> None:
        """
        Removes, in the background, a VPN interface no helper is attached to any
        more: left by a killed session, it would hold every connection on the
        machine. Does nothing while an engine runs, since its helper owns it.
        """
        def work():
            with self._vpn_lock:
                if self._process is None and vpn.nmcli_path() is not None:
                    vpn.cleanup()

        threading.Thread(target=work, name="nextvpn-vpn-cleanup", daemon=True).start()

    # ----------------------------------------------------------------- stop

    def stop(self) -> None:
        self._restart_with = None
        self._stop()

    def restart(self, settings: AppSettings) -> None:
        """Rebuilds the tunnel so a changed setting takes effect."""
        if self._process is None:
            self._start(settings)
            return
        self._restart_with = settings
        self._stop()

    def _stop(self) -> None:
        proc = self._process
        if proc is None:
            self._set_state(TunnelState.DISCONNECTED)
            return
        if self._stop_requested:
            return

        self._stop_requested = True
        self._set_state(TunnelState.DISCONNECTING)

        # The console client stops its controller and closes the datastore on
        # SIGTERM. Anything that ignores it for longer than the grace period is
        # killed: the BoltDB datastore is transactional and survives that.
        _send(proc, signal.SIGTERM)
        grace = self.VPN_STOP_GRACE_SECONDS if self.vpn_mode else self.STOP_GRACE_SECONDS
        threading.Thread(target=_reap_or_kill, args=(proc, grace),
                         name="nextvpn-stop", daemon=True).start()

    def shutdown(self, timeout: float = 3.0) -> None:
        """Synchronous stop for application exit. Raises no events."""
        self._restart_with = None
        proc = self._process
        self._generation += 1   # anything still queued for this run is stale now
        self._process = None
        if proc is None:
            return
        self._stop_requested = True
        if self.vpn_mode:
            timeout = max(timeout, self.VPN_STOP_GRACE_SECONDS)
        if proc.poll() is None:
            _send(proc, signal.SIGTERM)
            try:
                proc.wait(timeout)
            except subprocess.TimeoutExpired:
                _send(proc, signal.SIGKILL)
                try:
                    proc.wait(1.0)
                except subprocess.TimeoutExpired:
                    pass

    # ------------------------------------------------------------- threads

    def _pump(self, proc: subprocess.Popen, generation: int) -> None:
        raw_forwarded = 0
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                notice = Notice.parse(line)
                if notice is None:
                    if raw_forwarded < self.MAX_RAW_LINES:
                        raw_forwarded += 1
                        self._post(self._handle_output, generation, line)
                    continue

                if (notice.type in TunnelTelemetry.TRACKED_TYPES or
                        NoticePolicy.needs_ui(notice.type, self.verbose)):
                    self._post(self._handle, generation, notice)
        except (OSError, ValueError):
            pass

    def _watch_exit(self, proc: subprocess.Popen, generation: int, readers) -> None:
        code = proc.wait()
        # Every notice the engine managed to write is handled before its exit is:
        # the readers end at EOF, and the main loop runs callbacks in order.
        for reader in readers:
            reader.join(2.0)
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass
        self._post(self._handle_exit, generation, code)

    # ------------------------------------------------------- main loop side

    def _handle(self, generation: int, n: Notice) -> None:
        if generation != self._generation:
            return

        if n.type == NoticeType.ERROR:
            self._last_error = n.message
        elif n.type == NoticeType.VPN_SETUP_FAILED:
            self._setup_error = vpn_failure_text(n)

        signal_ = self.telemetry.apply(n)

        if signal_ & TelemetrySignal.TUNNEL_UP:
            if self.state == TunnelState.CONNECTING:
                self._set_state(TunnelState.CONNECTED)
        elif signal_ & TelemetrySignal.TUNNEL_DOWN and self.state == TunnelState.CONNECTED:
            # The engine redials by itself, so this is not the end of the session.
            self._set_state(TunnelState.CONNECTING)

        if signal_ & TelemetrySignal.REGIONS_CHANGED:
            self.regions_updated.emit()
        if signal_ & TelemetrySignal.STATS_CHANGED:
            self.stats_updated.emit()

        self.notice_received.emit(n)

    def _handle_output(self, generation: int, line: str) -> None:
        if generation != self._generation:
            return
        if self._first_raw is None:
            self._first_raw = line
        self.output_received.emit(EngineOutput(line))

    def _handle_exit(self, generation: int, code: int) -> None:
        if generation != self._generation:
            return

        self._process = None
        # The local listeners died with the process; the session totals stay, so
        # the last screenful of numbers does not blank out on disconnect.
        self.telemetry.clear_listeners()

        if self.vpn_mode and code < 0:
            # The helper was killed before it could hand the tun back.
            self.recover_vpn()

        restart = self._restart_with
        self._restart_with = None
        if restart is not None:
            self._start(restart)
            return

        if self._stop_requested:
            self._set_state(TunnelState.DISCONNECTED)
            return

        if self._setup_error:
            self._set_state(TunnelState.FAULTED, self._setup_error)
            return

        reason = self._last_error or self._first_raw
        if reason:
            detail = _("The tunnel engine stopped unexpectedly: {reason}").format(reason=reason)
        else:
            detail = _("The tunnel engine stopped unexpectedly (exit code {code}).").format(code=code)
        self._set_state(TunnelState.FAULTED, detail)

    # ---------------------------------------------------------------- state

    def _set_state(self, state: TunnelState, detail: str | None = None) -> None:
        if self.state == state and detail is None:
            return
        self.state = state
        self.state_changed.emit(state, detail)

    def _fault(self, message: str) -> None:
        self._set_state(TunnelState.FAULTED, message)


# ------------------------------------------------------------------ helpers

def vpn_failure_text(n: Notice) -> str:
    """What vpn_helper reported, worded for the user."""
    step = n.string("step") or ""
    detail = n.string("detail") or ""
    if step == "route":
        text = _("No network connection: this machine has no route to the internet.")
    elif step == "create":
        text = _("NetworkManager could not create the VPN interface: {detail}").format(detail=detail)
    elif step == "activate":
        text = _("NetworkManager could not bring the VPN interface up: {detail}").format(detail=detail)
    elif step == "engine":
        text = _("Could not start the tunnel engine: {error}").format(error=detail)
    else:
        text = n.message
    if n.data.get("denied") is True:
        text += " " + _("NetworkManager allows this without a password only to the user of an active "
                        "desktop session. Sign in to the desktop, or switch Settings → System to the "
                        "system proxy.")
    return text


def _send(proc: subprocess.Popen, sig: int) -> None:
    try:
        proc.send_signal(sig)
    except (ProcessLookupError, OSError):
        pass  # already gone


def _reap_or_kill(proc: subprocess.Popen, grace: float) -> None:
    try:
        proc.wait(grace)
    except subprocess.TimeoutExpired:
        _send(proc, signal.SIGKILL)


def _drain(stream) -> None:
    try:
        while stream.read(65536):
            pass
    except (OSError, ValueError):
        pass


def kill_orphaned_engines(config_path: os.PathLike | str, timeout: float = 2.0) -> list[int]:
    """
    Terminates engine processes of this user that were started with our own
    runtime config but are no longer our children. Matching on the config path
    keeps this from touching any other Psiphon client the user may be running,
    and still finds an engine left by an older install at a different path.
    """
    target = str(config_path)
    me = os.getpid()
    uid = os.getuid()
    found: list[int] = []

    try:
        entries = os.listdir("/proc")
    except OSError:
        return found

    for name in entries:
        if not name.isdigit() or int(name) == me:
            continue
        pid = int(name)
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
        except OSError:
            continue

        try:
            i = argv.index("--config")
        except ValueError:
            continue
        # The engine itself, or an interpreter running a wrapper named after it.
        if not any("psiphon" in os.path.basename(a) for a in argv[:i]):
            continue
        if i + 1 < len(argv) and argv[i + 1] == target:
            found.append(pid)

    for pid in found:
        _terminate_pid(pid, timeout)
    return found


def _terminate_pid(pid: int, timeout: float) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


@dataclass(frozen=True)
class EngineVersion:
    revision: str
    built_with: str
    build_date: str


def engine_version(binary: os.PathLike | str | None, timeout: float = 5.0) -> EngineVersion | None:
    """Build banner from the tunnel engine. Slow enough to keep off the main loop."""
    if not binary or not os.path.isfile(binary):
        return None
    try:
        result = subprocess.run([str(binary), "-v"], capture_output=True, timeout=timeout,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None

    text = (result.stdout + result.stderr).decode("utf-8", "replace")

    def line(prefix: str) -> str:
        for raw in text.splitlines():
            item = raw.strip()
            if item.lower().startswith(prefix.lower()):
                return item[len(prefix):].strip()
        return "unknown"

    return EngineVersion(line("Revision:"), line("Built With:"), line("Build Date:"))
