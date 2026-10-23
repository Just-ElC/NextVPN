"""
Runs the engine in VPN mode and owns the tun for exactly as long as it runs.

    python3 -m nextvpn.core.vpn_helper -- <engine> --config <file> ...

The app starts this in place of the engine. It sets the tun up through
NetworkManager, starts the engine attached to it, and passes the engine's
notices through unchanged, adding a few of its own in the same format. When
it is told to stop (SIGTERM, or SIGINT or SIGHUP), when the engine exits, or
when the app dies (its parent-death signal), it stops the engine and removes
the tun, so a crashed app never leaves the machine without a network.

It follows the uplink while it runs: a changed address only updates the
reverse-path rules, a changed interface restarts the engine bound to the new
one. Only the standard library is used.
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from . import vpn
from .notice import NoticeType

VPN_UP = NoticeType.VPN_UP
VPN_SETUP_FAILED = NoticeType.VPN_SETUP_FAILED

POLL_SECONDS = 5.0
ENGINE_STOP_SECONDS = 4.0

PR_SET_PDEATHSIG = 1
try:
    _prctl = ctypes.CDLL(None, use_errno=True).prctl
except (OSError, AttributeError):  # pragma: no cover
    _prctl = None

_out_lock = threading.Lock()


def notice(kind: str, **data) -> None:
    line = json.dumps({"data": data, "noticeType": kind,
                       "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"},
                      ensure_ascii=False)
    write_line(line.encode("utf-8") + b"\n")


def write_line(raw: bytes) -> None:
    with _out_lock:
        try:
            sys.stderr.buffer.write(raw)
            sys.stderr.buffer.flush()
        except (OSError, ValueError):
            pass


def info(message: str) -> None:
    notice("Info", message=message)


def dns_works(timeout: float = 4.0) -> bool:
    """One A query for a well-known name, to the tun's resolver address."""
    query = struct.pack(">HHHHHH", 0x4E56, 0x0100, 1, 0, 0, 0)
    query += b"".join(bytes([len(p)]) + p.encode() for p in "www.gstatic.com".split(".")) + b"\0"
    query += struct.pack(">HH", 1, 1)
    for _ in range(2):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            try:
                s.sendto(query, (vpn.DNS4, 53))
                reply, _addr = s.recvfrom(2048)
            except OSError:
                continue
            if len(reply) >= 12 and reply[:2] == query[:2] and (reply[3] & 0x0F) == 0:
                return True
    return False


class Helper:
    def __init__(self, engine_argv: list[str]):
        self.engine_argv = engine_argv
        self.stop = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.uuid: str | None = None
        self.uplink: vpn.Uplink | None = None
        self.connected = threading.Event()
        self._checked_dns = False

    # ---------------------------------------------------------------- run

    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda *_: self.stop.set())
        try:
            return self._run()
        finally:
            self._stop_engine()
            if self.uuid:
                vpn.tear_down(self.uuid)
                info(f"VPN interface {vpn.IFNAME} removed")

    def _run(self) -> int:
        # Whatever a crash or a kill left behind would hold the device name.
        if vpn.cleanup():
            info("Removed a VPN interface left from an earlier session")

        uplink = vpn.detect_uplink()
        if uplink is None:
            notice(VPN_SETUP_FAILED, message="No network connection: there is no default route.")
            return 3
        try:
            self.uuid = vpn.bring_up(uplink)
        except vpn.VpnError as ex:
            notice(VPN_SETUP_FAILED, message=str(ex))
            return 4
        self.uplink = uplink
        notice(VPN_UP, device=vpn.IFNAME, uplink=uplink.iface, dns=",".join(uplink.dns))

        if self.stop.is_set() or not self._start_engine():
            return 0 if self.stop.is_set() else 5

        while not self.stop.wait(POLL_SECONDS):
            code = self.proc.poll()
            if code is not None:
                return code
            self._follow_uplink()
            if self.connected.is_set() and not self._checked_dns:
                self._checked_dns = True
                threading.Thread(target=self._check_dns, daemon=True).start()
        return 0

    # -------------------------------------------------------------- engine

    def _start_engine(self) -> bool:
        argv = [*self.engine_argv,
                "-tunDevice", vpn.IFNAME,
                "-tunBindInterface", self.uplink.iface,
                "-tunDNSServers", ",".join(self.uplink.dns)]

        def child_setup():
            if _prctl is not None:
                _prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)

        self.connected.clear()
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                         preexec_fn=child_setup, close_fds=True)
        except OSError as ex:
            notice(VPN_SETUP_FAILED, message=f"Could not start the tunnel engine: {ex.strerror or ex}")
            return False
        threading.Thread(target=self._forward, args=(self.proc,), daemon=True).start()
        return True

    def _forward(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stderr.readline, b""):
            write_line(raw if raw.endswith(b"\n") else raw + b"\n")
            if b'"noticeType":"Tunnels"' in raw:
                try:
                    count = json.loads(raw)["data"]["count"]
                except (ValueError, KeyError, TypeError):
                    continue
                if count:
                    self.connected.set()
                else:
                    self.connected.clear()

    def _stop_engine(self) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(ENGINE_STOP_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(1.0)
            except subprocess.TimeoutExpired:
                pass

    # -------------------------------------------------------------- uplink

    def _follow_uplink(self) -> None:
        current = vpn.detect_uplink()
        if current is None or current == self.uplink:
            return
        previous, self.uplink = self.uplink, current
        if set(current.addresses) != set(previous.addresses):
            vpn.update_rules(self.uuid, current)
        if not current.same_route(previous) or set(current.dns) != set(previous.dns):
            info(f"Network changed to {current.iface}; reconnecting through it")
            self._stop_engine()
            self._checked_dns = False
            self._start_engine()

    def _check_dns(self) -> None:
        if dns_works():
            info("DNS goes through the tunnel")
        else:
            notice("Warning", message="DNS through the tunnel did not answer. Names may not resolve "
                                      "until the tunnel reconnects.")


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print("usage: python3 -m nextvpn.core.vpn_helper -- <engine> [engine args]", file=sys.stderr)
        return 2
    engine_argv = argv[argv.index("--") + 1:]
    if not engine_argv:
        return 2
    return Helper(engine_argv).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
