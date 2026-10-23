"""
Decides what the activity log does with each notice.

The engine emits hundreds of notices while a tunnel is being established and
most of them mean nothing to a user, so this runs on the engine's reader thread
and keeps the main loop out of it entirely unless something is worth showing.
"""

from __future__ import annotations

from enum import IntEnum

from .notice import NoticeType as T


class NoticeLevel(IntEnum):
    """Severity of a log line. Mirrors the three levels the engine reports."""

    INFO = 0
    WARNING = 1
    ERROR = 2


_INTERESTING = frozenset({
    T.TUNNELS, T.CONNECTED_SERVER, T.ACTIVE_TUNNEL, T.CONNECTED_SERVER_REGION,
    T.CLIENT_REGION, T.LISTENING_HTTP_PROXY_PORT, T.LISTENING_SOCKS_PROXY_PORT,
    T.HOMEPAGE, T.SERVER_ALERT, T.UNTUNNELED, T.CLIENT_UPGRADE_AVAILABLE,
    T.UPSTREAM_PROXY_ERROR, T.SOCKS_PROXY_PORT_IN_USE, T.HTTP_PROXY_PORT_IN_USE,
    T.VPN_UP, T.VPN_SETUP_FAILED,
})

_VISIBLE = frozenset({
    T.CLIENT_REGION, T.ACTIVE_TUNNEL, T.CONNECTED_SERVER_REGION,
    T.LISTENING_HTTP_PROXY_PORT, T.LISTENING_SOCKS_PROXY_PORT, T.BYTES_TRANSFERRED, T.VPN_UP,
})


class NoticePolicy:
    @staticmethod
    def level_of(kind: str) -> NoticeLevel:
        if kind in (T.ERROR, T.VPN_SETUP_FAILED):
            return NoticeLevel.ERROR
        if kind == T.WARNING:
            return NoticeLevel.WARNING
        return NoticeLevel.INFO

    @staticmethod
    def is_interesting(kind: str) -> bool:
        """Info notices a user benefits from seeing even with diagnostics off."""
        return kind in _INTERESTING

    @staticmethod
    def changes_visible_state(kind: str) -> bool:
        """Notices that move something visible, whether or not they are logged."""
        return kind in _VISIBLE

    @staticmethod
    def should_log(kind: str, verbose: bool) -> bool:
        # Throughput belongs in the graph. In the log it would be one line per
        # second forever, pushing everything that matters out of the buffer.
        if kind == T.BYTES_TRANSFERRED:
            return verbose
        return (NoticePolicy.level_of(kind) != NoticeLevel.INFO
                or verbose or NoticePolicy.is_interesting(kind))

    @staticmethod
    def needs_ui(kind: str, verbose: bool) -> bool:
        """True when the notice is worth waking the main loop for at all."""
        return NoticePolicy.should_log(kind, verbose) or NoticePolicy.changes_visible_state(kind)
