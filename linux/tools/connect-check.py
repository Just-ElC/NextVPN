#!/usr/bin/env python3
"""
Connects to the Psiphon network exactly the way the app does, with the shipped
engine, base.config and server list, and then fetches a page through the local
proxy. Exits 0 only if the tunnel came up and traffic actually went through it.

  python3 linux/tools/connect-check.py [--timeout 180] [--region DE]
"""

import argparse
import queue
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nextvpn.core import paths, tunnel_config  # noqa: E402
from nextvpn.core.engine import TunnelEngine  # noqa: E402
from nextvpn.core.notice import NoticeType  # noqa: E402
from nextvpn.core.settings import AppSettings  # noqa: E402
from nextvpn.core.status import TunnelState  # noqa: E402

PROBE = "https://www.gstatic.com/generate_204"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--region", default="", help="exit country code; empty for the fastest")
    args = parser.parse_args()

    engine_paths = paths.engine()
    print(f"engine:      {engine_paths.binary}")
    print(f"base config: {engine_paths.base_config}")
    print(f"server list: {engine_paths.server_list}", flush=True)

    events = queue.Queue()

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                fn, fn_args = events.get(timeout=0.1)
            except queue.Empty:
                continue
            fn(*fn_args)

    with tempfile.TemporaryDirectory(prefix="nextvpn-connect-") as tmp:
        def write(settings, engine):
            return tunnel_config.write_to(Path(tmp) / "runtime.config", tunnel_config.read_base_config(engine),
                                          settings, Path(tmp) / "tunnel")

        engine = TunnelEngine(post=lambda fn, *a: events.put((fn, a)), write_config=write)

        def on_state(state, detail):
            print(f"state: {state.value}" + (f" ({detail})" if detail else ""), flush=True)

        def on_notice(n):
            if n.type in (NoticeType.ACTIVE_TUNNEL, NoticeType.CONNECTED_SERVER_REGION,
                          NoticeType.CLIENT_REGION, NoticeType.LISTENING_HTTP_PROXY_PORT,
                          NoticeType.LISTENING_SOCKS_PROXY_PORT, NoticeType.ERROR):
                print(f"  {n.type}: {n.message}", flush=True)

        engine.state_changed.connect(on_state)
        engine.notice_received.connect(on_notice)

        started = time.monotonic()
        engine.start(AppSettings(egress_region=args.region))
        try:
            while (engine.state not in (TunnelState.CONNECTED, TunnelState.FAULTED)
                   and time.monotonic() - started < args.timeout):
                pump(0.5)

            if engine.state != TunnelState.CONNECTED:
                print(f"FAILED: no tunnel after {time.monotonic() - started:.0f} s", flush=True)
                return 1
            print(f"connected in {time.monotonic() - started:.1f} s", flush=True)
            pump(1)

            proxy = f"http://127.0.0.1:{engine.telemetry.http_port}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            with opener.open(PROBE, timeout=60) as response:
                status = response.status
            pump(2)
            stats = engine.stats
            print(f"GET {PROBE} through {proxy}: HTTP {status}")
            print(f"exit region: {engine.telemetry.connected_region}, protocol: {engine.telemetry.active_protocol}, "
                  f"bytes up/down: {stats.bytes_sent}/{stats.bytes_received}", flush=True)
            if status != 204:
                print("FAILED: unexpected response through the tunnel")
                return 1
        finally:
            engine.stop()
            stop_deadline = time.monotonic() + 15
            while engine.state != TunnelState.DISCONNECTED and time.monotonic() < stop_deadline:
                pump(0.2)
            engine.shutdown()

    print("OK: connected to the Psiphon network and carried traffic")
    return 0


if __name__ == "__main__":
    sys.exit(main())
