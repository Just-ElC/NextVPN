#!/usr/bin/env python3
"""
Connects to the Psiphon network exactly the way the app does, with the shipped
engine, base.config and server list, and checks that traffic really goes
through the tunnel. Exits 0 only if it does.

  python3 linux/tools/connect-check.py [--timeout 180] [--region DE]
  python3 linux/tools/connect-check.py --vpn      # whole-system mode, needs NetworkManager

In proxy mode a page is fetched through the local proxy. In VPN mode nothing is
pointed anywhere: a plain request has to leave from a Psiphon server's address,
DNS has to be answered from there too, and after disconnecting the machine has
to be exactly as it was.
"""

import argparse
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nextvpn.core import paths, tunnel_config, vpn  # noqa: E402
from nextvpn.core.engine import TunnelEngine  # noqa: E402
from nextvpn.core.notice import NoticeType  # noqa: E402
from nextvpn.core.settings import AppSettings, ConnectionMode  # noqa: E402
from nextvpn.core.status import TunnelState  # noqa: E402

PROBE = "https://www.gstatic.com/generate_204"
TRACE = "https://www.cloudflare.com/cdn-cgi/trace"


def trace(opener=None) -> dict:
    """Where Cloudflare sees this request coming from."""
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(TRACE, timeout=30) as response:
        text = response.read().decode()
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def resolver_address() -> str | None:
    """The address Google's name servers see the system resolver's query come from."""
    if shutil.which("dig") is None:
        return None
    try:
        out = subprocess.run(["dig", "+short", "+time=5", "+tries=2", "TXT", "o-o.myaddr.l.google.com"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r'"([0-9a-fA-F:.]+)"', out)
    return match.group(1) if match else None


def leftovers() -> list[str]:
    """Anything of the VPN still on the system."""
    found = []
    if vpn.our_connections():
        found.append("NetworkManager profile")
    rules = subprocess.run(["ip", "rule"], capture_output=True, text=True).stdout
    rules += subprocess.run(["ip", "-6", "rule"], capture_output=True, text=True).stdout
    if any(str(p) in rules for p in (vpn.PRIORITY_UPLINK, vpn.PRIORITY_MAIN, vpn.PRIORITY_TUNNEL)):
        found.append("routing rules")
    if Path(f"/sys/class/net/{vpn.IFNAME}").exists():
        found.append(f"device {vpn.IFNAME}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--region", default="", help="exit country code; empty for the fastest")
    parser.add_argument("--vpn", action="store_true", help="whole-system VPN mode instead of the proxy")
    parser.add_argument("--regions-wait", type=float, default=0,
                        help="stay connected this long, reporting the exit countries the network offers")
    parser.add_argument("--hold", type=float, default=0,
                        help="stay connected this long after the checks (for a test that kills this process)")
    parser.add_argument("--check-clean", action="store_true",
                        help="only report whether anything of the VPN is left on the system")
    args = parser.parse_args()

    if args.check_clean:
        left = leftovers()
        print(f"left behind: {', '.join(left)}" if left else "nothing of the VPN is left")
        return 1 if left else 0

    engine_paths = paths.engine()
    print(f"engine:      {engine_paths.binary}")
    print(f"base config: {engine_paths.base_config}")
    print(f"server list: {engine_paths.server_list}")
    print(f"mode:        {'VPN' if args.vpn else 'proxy'}", flush=True)

    direct = {}
    direct_resolver = None
    if args.vpn:
        direct = trace()
        direct_resolver = resolver_address()
        print(f"direct: ip={direct.get('ip')} loc={direct.get('loc')} resolver={direct_resolver}", flush=True)

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
        def write(settings, engine, packet_tunnel=False):
            return tunnel_config.write_to(Path(tmp) / "runtime.config", tunnel_config.read_base_config(engine),
                                          settings, Path(tmp) / "tunnel", packet_tunnel)

        engine = TunnelEngine(post=lambda fn, *a: events.put((fn, a)), write_config=write,
                              vpn_available=(vpn.available if args.vpn else (lambda: False)))

        def on_state(state, detail):
            print(f"state: {state.value}" + (f" ({detail})" if detail else ""), flush=True)

        def on_notice(n):
            if n.type in (NoticeType.ACTIVE_TUNNEL, NoticeType.CONNECTED_SERVER_REGION,
                          NoticeType.CLIENT_REGION, NoticeType.LISTENING_HTTP_PROXY_PORT,
                          NoticeType.LISTENING_SOCKS_PROXY_PORT, NoticeType.ERROR, NoticeType.VPN_UP,
                          NoticeType.VPN_SETUP_FAILED, NoticeType.AVAILABLE_EGRESS_REGIONS):
                print(f"  {n.type}: {n.message}", flush=True)
            elif n.type in (NoticeType.INFO, NoticeType.WARNING) and "tunnel" in n.message.lower():
                print(f"  {n.type}: {n.message}", flush=True)
            elif "ServerList" in n.type or "ServerEntries" in n.type:
                print(f"  {n.type}: {n.message[:200]}", flush=True)

        engine.state_changed.connect(on_state)
        engine.notice_received.connect(on_notice)
        # Server list fetches are only reported to the app in verbose mode.
        engine.verbose = bool(args.regions_wait)

        mode = ConnectionMode.VPN if args.vpn else ConnectionMode.PROXY
        started = time.monotonic()
        engine.start(AppSettings(egress_region=args.region, connection_mode=mode))
        try:
            while (engine.state not in (TunnelState.CONNECTED, TunnelState.FAULTED)
                   and time.monotonic() - started < args.timeout):
                pump(0.5)

            if engine.state != TunnelState.CONNECTED:
                print(f"FAILED: no tunnel after {time.monotonic() - started:.0f} s", flush=True)
                return 1
            if args.vpn and not engine.vpn_mode:
                print("FAILED: VPN mode was asked for but the engine ran in proxy mode", flush=True)
                return 1
            print(f"connected in {time.monotonic() - started:.1f} s", flush=True)
            pump(1)

            if args.vpn:
                if not check_vpn(engine, direct, direct_resolver, args.region, pump):
                    return 1
            else:
                proxy = f"http://127.0.0.1:{engine.telemetry.http_port}"
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                with opener.open(PROBE, timeout=60) as response:
                    status = response.status
                pump(2)
                print(f"GET {PROBE} through {proxy}: HTTP {status}")
                if status != 204:
                    print("FAILED: unexpected response through the tunnel")
                    return 1

            stats = engine.stats
            print(f"exit region: {engine.telemetry.connected_region}, protocol: {engine.telemetry.active_protocol}, "
                  f"bytes up/down: {stats.bytes_sent}/{stats.bytes_received}", flush=True)

            if args.regions_wait:
                pump(args.regions_wait)
                regions = engine.telemetry.available_regions
                print(f"exit countries offered after {args.regions_wait:.0f} s: {len(regions)}: "
                      f"{' '.join(sorted(regions))}", flush=True)
            if args.hold:
                print("holding", flush=True)
                pump(args.hold)
        finally:
            engine.stop()
            stop_deadline = time.monotonic() + 20
            while engine.state != TunnelState.DISCONNECTED and time.monotonic() < stop_deadline:
                pump(0.2)
            engine.shutdown()

    if args.vpn:
        left = leftovers()
        if left:
            print(f"FAILED: left behind after disconnecting: {', '.join(left)}")
            return 1
        after = trace()
        if after.get("ip") != direct.get("ip"):
            print(f"FAILED: after disconnecting traffic leaves from {after.get('ip')}, not {direct.get('ip')}")
            return 1
        print(f"after disconnecting: ip={after.get('ip')}, nothing left behind")

    print("OK: connected to the Psiphon network and carried traffic")
    return 0


def check_vpn(engine, direct, direct_resolver, region, pump) -> bool:
    print(f"device {engine.telemetry.vpn_device}, uplink {engine.telemetry.vpn_uplink}")
    for cmd in (["ip", "rule"], ["ip", "route", "show", "table", str(vpn.TABLE)],
                ["ip", "-6", "route", "show", "table", str(vpn.TABLE)], ["resolvectl", "dns"]):
        if shutil.which(cmd[0]):
            out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
            print(f"$ {' '.join(cmd)}\n{out}")

    # Nothing points this request anywhere: it is an ordinary connection.
    tunnelled = None
    for attempt in range(3):
        try:
            tunnelled = trace()
            break
        except OSError as ex:
            print(f"plain request failed ({ex}), retrying", flush=True)
            pump(3)
    if tunnelled is None:
        print("FAILED: no plain connection works with the VPN up")
        return False
    print(f"plain request: ip={tunnelled.get('ip')} loc={tunnelled.get('loc')}", flush=True)
    if tunnelled.get("ip") == direct.get("ip"):
        print("FAILED: a plain request left from this machine's own address, not through the tunnel")
        return False
    if region and tunnelled.get("loc") != region:
        print(f"FAILED: exit is in {tunnelled.get('loc')}, not {region}")
        return False

    resolver = resolver_address()
    print(f"system resolver seen from: {resolver}", flush=True)
    if direct_resolver and resolver == direct_resolver:
        print("FAILED: DNS still goes to this machine's own resolver: it leaks around the tunnel")
        return False
    if direct_resolver and resolver is None:
        print("FAILED: the system resolver stopped answering with the VPN up")
        return False

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(PROBE, timeout=60) as response:
            print(f"plain GET {PROBE}: HTTP {response.status}")
            if response.status != 204:
                return False
    except OSError as ex:
        print(f"FAILED: plain GET {PROBE}: {ex}")
        return False
    pump(1)
    return True


if __name__ == "__main__":
    sys.exit(main())
