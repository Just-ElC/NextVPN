"""
Whole-system VPN mode: every program's traffic goes through the tunnel.

The system proxy only reaches programs that read GNOME's or KDE's settings,
which on Hyprland, Sway, niri and the like is hardly any. In VPN mode the
engine runs a packet tunnel instead: it reads IP packets from a tun device and
relays them, TCP, UDP and DNS alike, to the Psiphon server, which sends them on
to the internet. The servers support this for every client; the official iOS
app works the same way.

Everything the tun needs from the system is asked of NetworkManager, which
grants it to the user of an active desktop session without a password: the
device itself (owned by the user, so the unprivileged engine can attach to it),
its addresses, the routes and policy rules that send traffic into it, and DNS.
The profile is in memory only and removed on disconnect; vpn_helper removes it
even if the app is killed, and cleanup() on the next start catches the rest.

Routing, IPv4 and IPv6 alike:

    PRIORITY_UPLINK   from <uplink address> lookup main
    PRIORITY_MAIN     lookup main suppress_prefixlength 0
    PRIORITY_TUNNEL   lookup TABLE            (two /1 routes into the tun)

Local networks keep working through the main table; only its default routes
are passed over. The engine's own connections are bound to the uplink
interface (SO_BINDTODEVICE, allowed unprivileged since Linux 5.7), which the
tun routes never match, so they fall through to the main table's default
route. The first rule is for strict reverse-path filtering (NixOS's firewall
default, firewalld for IPv6): without it a reply from a Psiphon server arriving
on the uplink would fail the check, because the reverse lookup would point at
the tun.

This module only decides and asks; it never changes anything as root.
"""

from __future__ import annotations

import ipaddress
import json
import os
import pwd
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: The tun device and the NetworkManager profile that owns it.
IFNAME = "nextvpn0"
CONNECTION_NAME = "NextVPN"

#: Routing table and rule priorities, chosen clear of wg-quick (51820) and of
#: the kernel's own rules (0, 32766, 32767).
TABLE = 28278
PRIORITY_UPLINK = 28270
PRIORITY_MAIN = 28271
PRIORITY_TUNNEL = 28272

#: The tun's own addresses. The server rewrites source addresses, so these only
#: need to stay clear of real networks: 198.18.0.0/15 is reserved for
#: benchmarking and never routed on the internet.
ADDRESS4 = "198.18.0.1/30"
ADDRESS6 = "fd6e:7670:6e2d::1/126"
#: What the system resolver is pointed at. The engine rewrites DNS packets sent
#: here to the Psiphon server's resolver, so names resolve at the exit, past
#: any local DNS tampering.
DNS4 = "198.18.0.2"

ROUTES4 = ("0.0.0.0/1", "128.0.0.0/1")
ROUTES6 = ("::/1", "8000::/1")

#: Below anything a desktop or another VPN is likely to use: in the presence of
#: a negative priority, NetworkManager uses only the lowest one's servers.
DNS_PRIORITY = -1000000

#: Bypass resolvers for the engine's own lookups when the uplink reports none.
FALLBACK_DNS = ("1.1.1.1", "8.8.8.8")


class VpnError(RuntimeError):
    """Setting up the tun failed; the message is meant for the user."""


@dataclass(frozen=True)
class Uplink:
    """Where traffic leaves the machine when the tunnel is not in the way."""

    #: The interface the engine binds its own connections to.
    iface: str
    #: Its addresses, IPv4 and IPv6, for the reverse-path rules.
    addresses: tuple[str, ...] = ()
    #: Resolvers for the engine's own lookups, reached over the uplink.
    dns: tuple[str, ...] = field(default=FALLBACK_DNS)

    @property
    def addresses4(self) -> list[str]:
        return [a for a in self.addresses if ":" not in a]

    @property
    def addresses6(self) -> list[str]:
        return [a for a in self.addresses if ":" in a]

    def same_route(self, other: "Uplink | None") -> bool:
        """Whether the engine can keep running: same interface to bind to."""
        return other is not None and other.iface == self.iface


# ------------------------------------------------------------------ commands

def _run(argv: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    env = dict(os.environ, LC_ALL="C")   # nmcli's messages are parsed below
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=timeout, env=env)


def nmcli_path() -> str | None:
    return shutil.which("nmcli")


def available(run=_run) -> bool:
    """NetworkManager is installed and running."""
    if nmcli_path() is None:
        return False
    try:
        result = run(["nmcli", "-t", "-f", "RUNNING", "general"], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "running"


# -------------------------------------------------------------------- uplink

def _ip_json(args: list[str], run=_run) -> list:
    try:
        result = run(["ip", "-j", *args], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _default_route_dev(family: str, run=_run) -> str | None:
    routes = [r for r in _ip_json([family, "route", "show", "table", "main", "default"], run)
              if isinstance(r, dict) and r.get("dev") and r.get("dev") != IFNAME]
    if not routes:
        return None
    routes.sort(key=lambda r: r.get("metric", 0) if isinstance(r.get("metric", 0), int) else 0)
    return routes[0]["dev"]


def _addresses(dev: str, run=_run) -> list[str]:
    out: list[str] = []
    for link in _ip_json(["addr", "show", "dev", dev], run):
        for info in link.get("addr_info", []) if isinstance(link, dict) else []:
            if info.get("scope") != "global" or not info.get("local"):
                continue
            if any(info.get(flag) for flag in ("tentative", "dadfailed")):
                continue
            out.append(info["local"])
    return out


def detect_uplink(run=_run, resolv_conf: str = "/etc/resolv.conf") -> Uplink | None:
    """
    The interface the main table's preferred default route leaves through, with
    its addresses and resolvers. None when the machine has no route out at all.
    """
    dev4 = _default_route_dev("-4", run)
    dev6 = _default_route_dev("-6", run)
    iface = dev4 or dev6
    if iface is None:
        return None
    addresses = _addresses(iface, run)
    if dev6 and dev6 != iface:
        addresses += _addresses(dev6, run)
    return Uplink(iface, tuple(dict.fromkeys(addresses)), tuple(bypass_dns(iface, run, resolv_conf)))


def _usable_resolver(text: str) -> str | None:
    text = text.strip().split("%")[0].split("#")[0]
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    # A local stub (systemd-resolved, dnsmasq) would answer through the tunnel's
    # own DNS once it is up, and the engine needs to reach the network before.
    if ip.is_loopback or ip.is_unspecified or str(ip) == DNS4:
        return None
    return str(ip)


def bypass_dns(iface: str, run=_run, resolv_conf: str = "/etc/resolv.conf") -> list[str]:
    """
    Resolvers the engine can reach over the uplink for its own lookups: the
    interface's own (from NetworkManager, then systemd-resolved), then whatever
    resolv.conf names, then public ones.
    """
    found: list[str] = []

    def add(values) -> None:
        for v in values:
            ip = _usable_resolver(v)
            if ip and ip not in found:
                found.append(ip)

    try:
        result = run(["nmcli", "-g", "IP4.DNS,IP6.DNS", "device", "show", iface], timeout=5)
        if result.returncode == 0:
            add(re.split(r"[|\s]+", result.stdout))
    except (OSError, subprocess.TimeoutExpired):
        pass
    if not found:
        try:
            result = run(["resolvectl", "dns", iface], timeout=5)
            if result.returncode == 0:
                add(result.stdout.split(":", 1)[-1].split())
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not found:
        try:
            for line in Path(resolv_conf).read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    add([parts[1]])
        except OSError:
            pass
    return found or list(FALLBACK_DNS)


# ------------------------------------------------------------------ profile

def routing_rules(uplink: Uplink, family: int) -> str:
    addresses = uplink.addresses4 if family == 4 else uplink.addresses6
    host = 32 if family == 4 else 128
    rules = [f"priority {PRIORITY_UPLINK} from {a}/{host} table 254" for a in addresses]
    rules.append(f"priority {PRIORITY_MAIN} table 254 suppress_prefixlength 0")
    rules.append(f"priority {PRIORITY_TUNNEL} table {TABLE}")
    return ", ".join(rules)


def profile_settings(uplink: Uplink, uid: int, user: str) -> list[str]:
    """The profile's properties, as nmcli setting/value pairs."""
    return [
        "connection.id", CONNECTION_NAME,
        "connection.interface-name", IFNAME,
        "connection.autoconnect", "no",
        "connection.permissions", f"user:{user}",
        "tun.mode", "tun",
        "tun.owner", str(uid),
        "tun.pi", "no",
        "tun.vnet-hdr", "no",
        "tun.multi-queue", "no",
        "ipv4.method", "manual",
        "ipv4.addresses", ADDRESS4,
        "ipv4.never-default", "yes",
        "ipv4.routes", ", ".join(f"{r} table={TABLE}" for r in ROUTES4),
        "ipv4.routing-rules", routing_rules(uplink, 4),
        "ipv4.dns", DNS4,
        "ipv4.dns-search", "~.",
        "ipv4.dns-priority", str(DNS_PRIORITY),
        "ipv6.method", "manual",
        "ipv6.addresses", ADDRESS6,
        "ipv6.never-default", "yes",
        "ipv6.may-fail", "yes",
        "ipv6.routes", ", ".join(f"{r} table={TABLE}" for r in ROUTES6),
        "ipv6.routing-rules", routing_rules(uplink, 6),
        "ipv6.dns-priority", str(DNS_PRIORITY),
    ]


def current_user() -> tuple[int, str]:
    uid = os.getuid()
    try:
        return uid, pwd.getpwuid(uid).pw_name
    except KeyError:
        return uid, str(uid)


def _explain(result: subprocess.CompletedProcess, doing: str) -> VpnError:
    text = (result.stderr or result.stdout or "").strip().splitlines()
    detail = text[-1] if text else f"exit code {result.returncode}"
    detail = re.sub(r"^Error:\s*", "", detail)
    if re.search(r"insufficient privileges|not authori[sz]ed|permission denied", detail, re.I):
        detail += (". NetworkManager lets the user of an active desktop session do this without a "
                   "password; from anywhere else it needs a polkit rule, or use proxy mode")
    return VpnError(f"NetworkManager could not {doing}: {detail}")


def our_connections(run=_run) -> list[str]:
    """UUIDs of profiles this app created, including ones left by a crash."""
    try:
        result = run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    uuids = []
    for line in result.stdout.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) >= 3 and parts[0] == CONNECTION_NAME and parts[2] == "tun":
            uuids.append(parts[1])
    return uuids


def cleanup(run=_run) -> int:
    """Removes our profiles, which takes the tun, its routes and its DNS with them."""
    removed = 0
    for uuid in our_connections(run):
        try:
            if run(["nmcli", "connection", "delete", "uuid", uuid], timeout=20).returncode == 0:
                removed += 1
        except (OSError, subprocess.TimeoutExpired):
            pass
    return removed


def bring_up(uplink: Uplink, run=_run, uid_user: tuple[int, str] | None = None) -> str:
    """Creates the in-memory profile and activates it. Returns its UUID."""
    uid, user = uid_user or current_user()
    try:
        added = run(["nmcli", "connection", "add", "save", "no", "type", "tun",
                     *profile_settings(uplink, uid, user)], timeout=30)
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise VpnError(f"NetworkManager could not create the VPN interface: {ex}") from None
    if added.returncode != 0:
        raise _explain(added, "create the VPN interface")
    match = re.search(r"\(([0-9a-fA-F-]{36})\)", added.stdout)
    if not match:
        raise VpnError("NetworkManager created the VPN interface but did not say which one it is")
    uuid = match.group(1)

    try:
        up = run(["nmcli", "--wait", "30", "connection", "up", "uuid", uuid], timeout=40)
    except (OSError, subprocess.TimeoutExpired) as ex:
        up = subprocess.CompletedProcess([], 1, "", str(ex))
    if up.returncode != 0:
        tear_down(uuid, run)
        raise _explain(up, "bring the VPN interface up")
    return uuid


def update_rules(uuid: str, uplink: Uplink, run=_run) -> bool:
    """Points the reverse-path rules at a changed uplink, without dropping the tun."""
    try:
        changed = run(["nmcli", "connection", "modify", "uuid", uuid,
                       "ipv4.routing-rules", routing_rules(uplink, 4),
                       "ipv6.routing-rules", routing_rules(uplink, 6)], timeout=15)
        if changed.returncode != 0:
            return False
        return run(["nmcli", "device", "reapply", IFNAME], timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def tear_down(uuid: str, run=_run) -> None:
    try:
        run(["nmcli", "connection", "delete", "uuid", uuid], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass
