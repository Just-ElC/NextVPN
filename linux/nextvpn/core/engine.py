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
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths, tunnel_config
from .i18n import _
from .notice import Notice, NoticeType
from .policy import NoticePolicy
from .settings import AppSettings
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
    #: Non-notice stderr lines forwarded to the log per run; a panic is long.
    MAX_RAW_LINES = 40

    def __init__(self, post: Callable = glib_post,
                 engine_paths: Callable[[], paths.EnginePaths] = paths.engine,
                 write_config: Callable[[AppSettings, paths.EnginePaths], Path] = tunnel_config.write):
        self._post = post
        self._engine_paths = engine_paths
        self._write_config = write_config

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

        try:
            config_path = self._write_config(settings, engine)
        except (OSError, ValueError) as ex:
            self._fault(_("Could not prepare tunnel configuration: {error}").format(error=ex))
            return

        self.telemetry.reset()
        self._stop_requested = False
        self._last_error = None
        self._first_raw = None
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
        try:
            proc = subprocess.Popen(
                argv,
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
        except OSError as ex:
            self._fault(_("Could not start the tunnel engine: {error}").format(error=ex.strerror or ex))
            return

        self._generation += 1
        generation = self._generation
        self._process = proc

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
        threading.Thread(target=_reap_or_kill, args=(proc, self.STOP_GRACE_SECONDS),
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

        restart = self._restart_with
        self._restart_with = None
        if restart is not None:
            self._start(restart)
            return

        if self._stop_requested:
            self._set_state(TunnelState.DISCONNECTED)
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
