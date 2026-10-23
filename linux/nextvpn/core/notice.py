"""
One line of psiphon-tunnel-core's notice stream.
The engine emits newline-delimited JSON objects shaped as
{ "noticeType": "...", "data": { ... }, "timestamp": "..." }.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_INT32 = (-(2**31), 2**31 - 1)
_INT64 = (-(2**63), 2**63 - 1)


class NoticeType:
    """Notice type names emitted by psiphon-tunnel-core that this client acts on."""

    TUNNELS = "Tunnels"
    LISTENING_SOCKS_PROXY_PORT = "ListeningSocksProxyPort"
    LISTENING_HTTP_PROXY_PORT = "ListeningHttpProxyPort"
    CONNECTING_SERVER = "ConnectingServer"
    CONNECTED_SERVER = "ConnectedServer"
    ACTIVE_TUNNEL = "ActiveTunnel"
    CONNECTED_SERVER_REGION = "ConnectedServerRegion"
    CLIENT_REGION = "ClientRegion"
    AVAILABLE_EGRESS_REGIONS = "AvailableEgressRegions"
    HOMEPAGE = "Homepage"
    BYTES_TRANSFERRED = "BytesTransferred"
    CLIENT_UPGRADE_AVAILABLE = "ClientUpgradeAvailable"
    SERVER_ALERT = "ServerAlert"
    SOCKS_PROXY_PORT_IN_USE = "SocksProxyPortInUse"
    HTTP_PROXY_PORT_IN_USE = "HttpProxyPortInUse"
    UNTUNNELED = "Untunneled"
    TRAFFIC_RATE_LIMITS = "TrafficRateLimits"
    UPSTREAM_PROXY_ERROR = "UpstreamProxyError"
    EXITING = "Exiting"
    INFO = "Info"
    WARNING = "Warning"
    ERROR = "Error"
    # Added by vpn_helper, in the engine's own format.
    VPN_UP = "VpnUp"
    VPN_SETUP_FAILED = "VpnSetupFailed"


def _parse_timestamp(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    # Go writes RFC3339 with nanosecond precision, which is finer than a datetime
    # carries, and a trailing Z that older Pythons do not accept.
    text = text.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class Notice:
    type: str
    data: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: str = ""

    @staticmethod
    def parse(line: str) -> "Notice | None":
        """The parsed notice, or None for anything that is not one."""
        if not line or not line.strip():
            return None
        try:
            root = json.loads(line)
        except ValueError:
            return None
        if not isinstance(root, dict):
            return None

        kind = root.get("noticeType")
        if not isinstance(kind, str) or not kind:
            return None

        data = root.get("data")
        if not isinstance(data, dict):
            data = {}

        when = _parse_timestamp(root.get("timestamp")) or datetime.now(timezone.utc)
        return Notice(kind, data, when, line)

    def string(self, key: str) -> str | None:
        value = self.data.get(key)
        return None if value is None else _as_text(value)

    # Numbers are read without ever raising: a value too large for the type, or a
    # type nobody expected, has to read as "absent" rather than take down the
    # reader loop that the whole connection state depends on.

    def _integer(self, key: str, bounds: tuple[int, int]) -> int | None:
        value = self.data.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError:
                return None
        if not isinstance(value, int):
            return None
        return value if bounds[0] <= value <= bounds[1] else None

    def int(self, key: str) -> int | None:
        return self._integer(key, _INT32)

    def long(self, key: str) -> int | None:
        return self._integer(key, _INT64)

    def string_array(self, key: str) -> list[str]:
        value = self.data.get(key)
        if not isinstance(value, list):
            return []
        return [_as_text(v) for v in value if v is not None]

    @property
    def message(self) -> str:
        """Human-readable single-line rendering, used by the log view."""
        text = self.string("message")
        if text is not None:
            return text
        return json.dumps(self.data, separators=(",", ":"), ensure_ascii=False)
