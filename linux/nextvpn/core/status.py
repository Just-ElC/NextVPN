"""
Every word the connection panel says, derived from the tunnel state alone.

This is separate from the view model because it is the part a user actually
reads, and because a pure function of (state, region, detail) can be tested
exhaustively without a main loop, a window or an engine process.
"""

from __future__ import annotations

from enum import Enum

from .i18n import _
from .regions import Regions


class TunnelState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    FAULTED = "faulted"


class StatusPresenter:
    @staticmethod
    def heading(state: TunnelState) -> str:
        return {
            TunnelState.CONNECTED: _("Connected"),
            TunnelState.CONNECTING: _("Connecting"),
            TunnelState.DISCONNECTING: _("Disconnecting"),
            TunnelState.FAULTED: _("Connection failed"),
        }.get(state, _("Not connected"))

    @staticmethod
    def subtitle(state: TunnelState, connected_region: str | None, detail: str | None) -> str:
        if state == TunnelState.CONNECTED:
            if connected_region:
                return _("Traffic is exiting through {country}").format(
                    country=Regions.name_of(connected_region))
            return _("Your traffic is protected")
        if state == TunnelState.CONNECTING:
            return _("Finding a route that works on this network")
        if state == TunnelState.DISCONNECTING:
            return _("Closing the tunnel")
        if state == TunnelState.FAULTED:
            return detail if detail else _("Something went wrong")
        return _("Your traffic is going out unprotected")

    @staticmethod
    def action_label(state: TunnelState) -> str:
        """What pressing the connect control will do next."""
        return {
            TunnelState.CONNECTED: _("Disconnect"),
            TunnelState.CONNECTING: _("Cancel"),
            TunnelState.DISCONNECTING: _("Disconnecting"),
        }.get(state, _("Connect"))

    @staticmethod
    def can_toggle(state: TunnelState) -> bool:
        """
        False only while the engine is being torn down. The engine cannot be
        restarted until its process has actually gone, so offering the action
        there would be a button that silently does nothing.
        """
        return state != TunnelState.DISCONNECTING

    @staticmethod
    def is_live(state: TunnelState) -> bool:
        """Whether the connect control should read as "on" rather than "off"."""
        return state in (TunnelState.CONNECTED, TunnelState.CONNECTING)
