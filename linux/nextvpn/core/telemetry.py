"""
Everything the notice stream tells us about the current session.

Split out of the engine so the protocol handling, which is the part that
actually decides whether the app believes it is connected, can be driven by a
recorded notice stream in a test, with no child process involved.
"""

from __future__ import annotations

import time
from datetime import timedelta
from enum import IntFlag

from .notice import Notice, NoticeType as T


class TelemetrySignal(IntFlag):
    """What a notice changed, so the engine knows which events to raise."""

    NONE = 0
    #: The engine reports at least one live tunnel.
    TUNNEL_UP = 1 << 0
    #: The tunnel count fell to zero. The engine redials on its own.
    TUNNEL_DOWN = 1 << 1
    PORTS_CHANGED = 1 << 2
    REGIONS_CHANGED = 1 << 3
    STATS_CHANGED = 1 << 4


class TunnelStats:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.bytes_sent = 0
        self.bytes_received = 0
        #: Monotonic seconds at which the session came up, or None.
        self.connected_at: float | None = None

    @property
    def uptime(self) -> timedelta:
        if self.connected_at is None:
            return timedelta(0)
        return timedelta(seconds=max(0.0, self._clock() - self.connected_at))

    def reset(self) -> None:
        self.bytes_sent = 0
        self.bytes_received = 0
        self.connected_at = None


class TunnelTelemetry:
    #: Notice types apply() acts on. The reader thread forwards these to the main
    #: loop even when nothing about them is going to be logged.
    TRACKED_TYPES = frozenset({
        T.LISTENING_SOCKS_PROXY_PORT, T.LISTENING_HTTP_PROXY_PORT, T.TUNNELS,
        T.ACTIVE_TUNNEL, T.CONNECTED_SERVER_REGION, T.CLIENT_REGION,
        T.AVAILABLE_EGRESS_REGIONS, T.HOMEPAGE, T.CLIENT_UPGRADE_AVAILABLE,
        T.BYTES_TRANSFERRED, T.VPN_UP, T.VPN_SETUP_FAILED,
    })

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.stats = TunnelStats(clock)
        self.socks_port = 0
        self.http_port = 0
        self.tunnel_count = 0
        self.client_region: str | None = None
        self.connected_region: str | None = None
        self.active_protocol: str | None = None
        self.homepage_url: str | None = None
        self.upgrade_available_version: str | None = None
        self.available_regions: list[str] = []
        #: VPN mode: the tun device and the interface the tunnel itself leaves by.
        self.vpn_device: str | None = None
        self.vpn_uplink: str | None = None

    def apply(self, n: Notice) -> TelemetrySignal:
        """Applies one notice and reports what it moved."""
        kind = n.type

        if kind == T.LISTENING_SOCKS_PROXY_PORT:
            self.socks_port = n.int("port") or 0
            return TelemetrySignal.PORTS_CHANGED

        if kind == T.LISTENING_HTTP_PROXY_PORT:
            self.http_port = n.int("port") or 0
            return TelemetrySignal.PORTS_CHANGED

        if kind == T.TUNNELS:
            previous = self.tunnel_count
            self.tunnel_count = max(0, n.int("count") or 0)

            if self.tunnel_count > 0:
                # First tunnel of the session starts the clock; later ones do not
                # restart it, so a mid-session redial does not reset the uptime.
                if self.stats.connected_at is None:
                    self.stats.connected_at = self._clock()
                return TelemetrySignal.TUNNEL_UP

            if previous > 0:
                self.stats.connected_at = None
                return TelemetrySignal.TUNNEL_DOWN
            return TelemetrySignal.NONE

        if kind == T.ACTIVE_TUNNEL:
            self.active_protocol = n.string("protocol")
            return TelemetrySignal.NONE

        if kind == T.CONNECTED_SERVER_REGION:
            self.connected_region = n.string("serverRegion")
            return TelemetrySignal.NONE

        if kind == T.CLIENT_REGION:
            self.client_region = n.string("region")
            return TelemetrySignal.NONE

        if kind == T.AVAILABLE_EGRESS_REGIONS:
            self.available_regions = n.string_array("regions")
            return TelemetrySignal.REGIONS_CHANGED

        if kind == T.HOMEPAGE:
            self.homepage_url = n.string("url")
            return TelemetrySignal.NONE

        if kind == T.CLIENT_UPGRADE_AVAILABLE:
            # Recorded so the interface can mention it. Nothing is downloaded and
            # no file belonging to this application is ever replaced.
            self.upgrade_available_version = n.string("version")
            return TelemetrySignal.NONE

        if kind == T.VPN_UP:
            self.vpn_device = n.string("device")
            self.vpn_uplink = n.string("uplink")
            return TelemetrySignal.NONE

        if kind == T.BYTES_TRANSFERRED:
            self.stats.bytes_sent += max(0, n.long("sent") or 0)
            self.stats.bytes_received += max(0, n.long("received") or 0)
            return TelemetrySignal.STATS_CHANGED

        return TelemetrySignal.NONE

    def reset(self) -> None:
        """
        Clears everything that belongs to one run of the engine. The available
        region list deliberately survives, so the picker is not empty between
        connections.
        """
        self.stats.reset()
        self.socks_port = 0
        self.http_port = 0
        self.tunnel_count = 0
        self.connected_region = None
        self.active_protocol = None
        self.homepage_url = None
        self.vpn_device = None
        self.vpn_uplink = None

    def clear_listeners(self) -> None:
        """Called when the engine process is gone: the listeners went with it."""
        self.socks_port = 0
        self.http_port = 0
        self.tunnel_count = 0
        self.stats.connected_at = None
        self.vpn_device = None
        self.vpn_uplink = None
