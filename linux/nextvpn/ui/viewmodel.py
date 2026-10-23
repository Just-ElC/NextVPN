"""
The state every page shows, in one place.

Pages never talk to the engine. They read from here and listen for "changed",
which is deliberately coarse: a handful of labels are refreshed from plain
properties, which is cheaper and much harder to get wrong than wiring each one
to its own notification.
"""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass
from datetime import datetime

from gi.repository import GLib, GObject

from ..core import fmt, paths, system_proxy
from ..core.engine import EngineOutput, TunnelEngine
from ..core.i18n import _
from ..core.notice import Notice, NoticeType
from ..core.policy import NoticeLevel, NoticePolicy
from ..core.regions import RegionInfo, Regions, embedded_regions
from ..core.settings import AppSettings, ConnectionMode
from ..core.status import StatusPresenter, TunnelState
from ..core.system_proxy import SystemProxy


@dataclass(frozen=True)
class LogEntry:
    time: datetime
    level: NoticeLevel
    type: str
    message: str

    @property
    def time_text(self) -> str:
        return self.time.astimezone().strftime("%H:%M:%S")

    def as_line(self) -> str:
        return f"{self.time_text}  {self.type}  {self.message}"


class MainViewModel(GObject.Object):
    MAX_LOG_ENTRIES = 1500
    #: After this long without a tunnel the status line suggests what to try.
    SLOW_CONNECT_SECONDS = 40
    MAX_RATE_SAMPLES = 64

    __gsignals__ = {
        # Something any page may be showing has changed.
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "rates-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "regions-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "log-appended": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "log-cleared": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # (old state, new state) for the tray and for notifications.
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (object, object)),
    }

    def __init__(self, settings: AppSettings, engine: TunnelEngine | None = None,
                 proxy: SystemProxy | None = None):
        super().__init__()
        self.settings = settings
        self.engine = engine or TunnelEngine()
        self.proxy = proxy or SystemProxy()

        self.state = TunnelState.DISCONNECTED
        self.status_detail = ""
        self.active_protocol: str | None = None
        self.client_region: str | None = None
        self.connected_region: str | None = None
        self.http_port = 0
        self.socks_port = 0

        self._proxy_target: tuple[int, int] | None = None
        self.proxy_backends: list[str] = []
        self._connecting_since: float | None = None
        self._slow_id = 0

        self.log: collections.deque[LogEntry] = collections.deque(maxlen=self.MAX_LOG_ENTRIES)
        self.rate_history: list[tuple[float, float]] = []
        self._last_sample_at: float | None = None
        self._tick_id = 0

        self.selected_region = Regions.describe(settings.egress_region)
        self.available_regions: list[RegionInfo] = []
        # Until the engine has reported once, the countries of the built-in
        # servers: the engine starts from exactly those.
        self._rebuild_regions(settings.known_regions or embedded_regions(paths.engine().server_list))

        self.engine.state_changed.connect(self._on_state_changed)
        self.engine.notice_received.connect(self._on_notice)
        self.engine.output_received.connect(self._on_output)
        self.engine.regions_updated.connect(self._on_regions)

    # ------------------------------------------------------------- derived

    @property
    def is_connected(self) -> bool:
        return self.state == TunnelState.CONNECTED

    @property
    def is_live(self) -> bool:
        return StatusPresenter.is_live(self.state)

    @property
    def is_faulted(self) -> bool:
        return self.state == TunnelState.FAULTED and bool(self.status_detail)

    @property
    def can_toggle(self) -> bool:
        return StatusPresenter.can_toggle(self.state)

    @property
    def status_text(self) -> str:
        return StatusPresenter.heading(self.state)

    @property
    def status_subtitle(self) -> str:
        if self.state == TunnelState.CONNECTING and self.slow_to_connect:
            region = self.settings.egress_region
            if region:
                return _("Slow to connect through {country}. “Best performance” has many more servers "
                         "to try.").format(country=Regions.name_of(region))
            return _("Still looking for a route. On heavily filtered networks this can take a few minutes.")
        return StatusPresenter.subtitle(self.state, self.connected_region, self.status_detail)

    @property
    def slow_to_connect(self) -> bool:
        return (self._connecting_since is not None
                and time.monotonic() - self._connecting_since >= self.SLOW_CONNECT_SECONDS)

    @property
    def action_label(self) -> str:
        return StatusPresenter.action_label(self.state)

    @property
    def protocol_text(self) -> str:
        return self.active_protocol or fmt.EMPTY

    @property
    def ports_text(self) -> str:
        return fmt.ports(self.http_port, self.socks_port)

    @property
    def client_region_text(self) -> str:
        return fmt.country(self.client_region)

    @property
    def proxy_applied(self) -> bool:
        return self._proxy_target is not None

    @property
    def mode_text(self) -> str:
        """What the tunnel covers: everything, or what follows the system proxy."""
        if self.settings.connection_mode == ConnectionMode.VPN:
            if self.engine.vpn_unavailable:
                return _("System proxy: VPN mode needs NetworkManager")
            if self.engine.vpn_mode and self.state == TunnelState.CONNECTED:
                return _("VPN: all traffic")
            return _("VPN: all traffic, on connect")
        return _("System proxy: {state}").format(state=self.system_proxy_text)

    @property
    def system_proxy_text(self) -> str:
        if not self.settings.set_system_proxy:
            return _("Off — configure apps manually")
        if self.proxy_applied and self.proxy_backends:
            names = {"gnome": _("GNOME"), "kde": _("KDE")}
            return _("Applied: {desktops}").format(
                desktops=", ".join(names.get(b, b) for b in self.proxy_backends))
        if self.proxy_applied:
            return _("No desktop settings to change")
        return _("Applies on connect")

    @property
    def download_text(self) -> str:
        return fmt.bytes_(self.engine.stats.bytes_received)

    @property
    def upload_text(self) -> str:
        return fmt.bytes_(self.engine.stats.bytes_sent)

    @property
    def uptime_text(self) -> str:
        return fmt.duration(self.engine.stats.uptime)

    @property
    def down_rate_text(self) -> str:
        return fmt.rate(self.rate_history[-1][0] if self.rate_history else 0)

    @property
    def up_rate_text(self) -> str:
        return fmt.rate(self.rate_history[-1][1] if self.rate_history else 0)

    @property
    def shell_exports(self) -> str:
        return system_proxy.shell_exports(self.http_port, self.socks_port)

    # ------------------------------------------------------------ commands

    def toggle(self) -> None:
        if not self.can_toggle:
            return
        if self.is_live:
            self.disconnect_tunnel()
        else:
            self.connect_tunnel()

    def connect_tunnel(self) -> None:
        if self.state in (TunnelState.CONNECTED, TunnelState.CONNECTING):
            return
        self._clear_rates()
        self.append_log(NoticeLevel.INFO, "Client", _("Starting tunnel"))
        self.engine.start(self.settings)
        self.emit("changed")

    def disconnect_tunnel(self) -> None:
        if self.state == TunnelState.DISCONNECTED:
            return
        self.append_log(NoticeLevel.INFO, "Client", _("Stopping tunnel"))
        self.engine.stop()

    def select_region(self, region: RegionInfo) -> None:
        if region.code == self.selected_region.code:
            return
        self.selected_region = region
        self.settings.egress_region = region.code
        self.settings.save()
        self.emit("changed")
        # A region change only takes effect on a fresh tunnel.
        if self.state in (TunnelState.CONNECTED, TunnelState.CONNECTING):
            self.append_log(NoticeLevel.INFO, "Client",
                            _("Switching exit to {region}").format(region=region.display))
            self.engine.restart(self.settings)

    def apply_tunnel_setting_change(self) -> None:
        """
        For settings the engine only reads at startup. Saves them and rebuilds the
        tunnel if one is up, so the change is not silently ignored until next time.
        """
        self.settings.save()
        if self.state in (TunnelState.CONNECTED, TunnelState.CONNECTING):
            self.append_log(NoticeLevel.INFO, "Client", _("Rebuilding the tunnel to apply a changed setting"))
            self.engine.restart(self.settings)

    def notify_settings_changed(self) -> None:
        """Settings that take effect at once, such as whether to set the system proxy."""
        self.settings.save()
        self._apply_or_revert_proxy()
        self.emit("changed")

    def reapply_proxy(self) -> None:
        """Hands the desktop the current bypass list without dropping the proxy first."""
        self.settings.save()
        if self._proxy_target is not None:
            self._proxy_target = None
            self._apply_or_revert_proxy()
        self.emit("changed")

    def set_show_diagnostics(self, value: bool) -> None:
        self.engine.verbose = value

    @property
    def show_diagnostics(self) -> bool:
        return self.engine.verbose

    def clear_log(self) -> None:
        self.log.clear()
        self.emit("log-cleared")

    def log_text(self) -> str:
        return "\n".join(entry.as_line() for entry in self.log) + ("\n" if self.log else "")

    def shutdown(self) -> None:
        self._stop_tick()
        if self._slow_id:
            GLib.source_remove(self._slow_id)
            self._slow_id = 0
        self.engine.shutdown()
        if self.proxy_applied or self.proxy.is_applied:
            self.proxy.revert()
            self._proxy_target = None

    # ------------------------------------------------------- engine events

    def _on_state_changed(self, state: TunnelState, detail: str | None) -> None:
        previous = self.state
        self.state = state
        self.status_detail = detail or ""

        t = self.engine.telemetry
        self.socks_port = t.socks_port
        self.http_port = t.http_port
        self.active_protocol = t.active_protocol
        self.connected_region = t.connected_region

        if detail:
            level = NoticeLevel.ERROR if state == TunnelState.FAULTED else NoticeLevel.INFO
            self.append_log(level, "Client", detail)

        if state in (TunnelState.DISCONNECTED, TunnelState.FAULTED):
            self._clear_rates()

        # The clock only has something to count while a session is up.
        if state == TunnelState.CONNECTED:
            self._start_tick()
        else:
            self._stop_tick()

        # Counted from the first attempt, not from each redial within it.
        if state == TunnelState.CONNECTING:
            if self._connecting_since is None:
                self._connecting_since = time.monotonic()
                self._slow_id = GLib.timeout_add_seconds(self.SLOW_CONNECT_SECONDS, self._on_slow)
        elif state != TunnelState.CONNECTING:
            self._connecting_since = None
            if self._slow_id:
                GLib.source_remove(self._slow_id)
                self._slow_id = 0

        self._apply_or_revert_proxy()
        self.emit("changed")
        if previous != state:
            self.emit("state-changed", previous, state)

    def _on_notice(self, n: Notice) -> None:
        t = self.engine.telemetry
        kind = n.type

        if kind == NoticeType.CLIENT_REGION:
            self.client_region = t.client_region
        elif kind == NoticeType.ACTIVE_TUNNEL:
            self.active_protocol = t.active_protocol
        elif kind == NoticeType.CONNECTED_SERVER_REGION:
            self.connected_region = t.connected_region
        elif kind in (NoticeType.LISTENING_HTTP_PROXY_PORT, NoticeType.LISTENING_SOCKS_PROXY_PORT):
            self.socks_port = t.socks_port
            self.http_port = t.http_port
            self._apply_or_revert_proxy()
        elif kind == NoticeType.BYTES_TRANSFERRED:
            # "received" is inbound, "sent" is outbound: down first, then up.
            self._record_rate(n.long("received") or 0, n.long("sent") or 0)

        if NoticePolicy.should_log(kind, self.engine.verbose):
            self.append_log(NoticePolicy.level_of(kind), kind, n.message)

        if NoticePolicy.changes_visible_state(kind):
            self.emit("changed")

    def _on_output(self, output: EngineOutput) -> None:
        self.append_log(NoticeLevel.ERROR, "Engine", output.text)

    def _on_regions(self) -> None:
        codes = Regions.sorted_codes(self.engine.telemetry.available_regions)
        if codes and codes != self.settings.known_regions:
            self.settings.known_regions = codes
            self.settings.save()
        self._rebuild_regions(codes)
        self.emit("regions-changed")
        self.emit("changed")

    # ----------------------------------------------------------- regions

    def _rebuild_regions(self, codes) -> None:
        regions = [Regions.best()] + [Regions.describe(c) for c in Regions.sorted_codes(codes)]
        # Keep the saved choice visible even before the engine reports the list.
        if self.selected_region.is_country and all(r.code != self.selected_region.code for r in regions):
            regions.append(self.selected_region)
        self.available_regions = regions

    # ------------------------------------------------------------- rates

    def _record_rate(self, delta_down: int, delta_up: int) -> None:
        now = time.monotonic()
        seconds = 1.0 if self._last_sample_at is None else now - self._last_sample_at
        self._last_sample_at = now
        seconds = max(seconds, 0.05)

        self.rate_history.append((delta_down / seconds, delta_up / seconds))
        del self.rate_history[:-self.MAX_RATE_SAMPLES]
        self.emit("rates-changed")
        self.emit("changed")

    def _clear_rates(self) -> None:
        self.rate_history.clear()
        self._last_sample_at = None
        self.emit("rates-changed")

    # -------------------------------------------------------------- tick

    def _start_tick(self) -> None:
        if not self._tick_id:
            self._tick_id = GLib.timeout_add_seconds(1, self._tick)

    def _stop_tick(self) -> None:
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0

    def _tick(self) -> bool:
        self.emit("changed")
        return GLib.SOURCE_CONTINUE

    def _on_slow(self) -> bool:
        self._slow_id = 0
        self.emit("changed")
        return GLib.SOURCE_REMOVE

    # --------------------------------------------------------------- log

    def append_log(self, level: NoticeLevel, kind: str, message: str) -> None:
        entry = LogEntry(datetime.now().astimezone(), level, kind, message)
        self.log.append(entry)
        self.emit("log-appended", entry)

    # ------------------------------------------------------------- proxy

    def _apply_or_revert_proxy(self) -> None:
        """
        The desktop is pointed at the tunnel while it is up, and stays pointed at
        it while the engine redials or is being rebuilt for a new exit: taking the
        proxy away for those few seconds would quietly send traffic around the
        tunnel. It is only handed back when the session actually ends.
        """
        state = self.state
        if not self.settings.set_system_proxy or self.engine.vpn_mode:
            # In VPN mode everything already goes through the tun.
            self._revert_proxy()
        elif state == TunnelState.CONNECTED and self.http_port > 0:
            if self._proxy_target != (self.http_port, self.socks_port):
                self._apply_proxy()
        elif state in (TunnelState.DISCONNECTED, TunnelState.FAULTED):
            self._revert_proxy()

    def _apply_proxy(self) -> None:
        result = self.proxy.apply(self.http_port, self.socks_port, self.settings.proxy_bypass_list)
        for error in result.errors:
            self.append_log(NoticeLevel.WARNING, "Client", _("System proxy: {error}").format(error=error))
        if result.ok:
            self._proxy_target = (self.http_port, self.socks_port)
            self.proxy_backends = result.applied
            self.append_log(NoticeLevel.INFO, "Client", _("System proxy set to {proxy} ({desktops})").format(
                proxy=system_proxy.describe(self.http_port, self.socks_port),
                desktops=", ".join(b.upper() for b in result.applied)))
        elif not result.errors:
            self.append_log(NoticeLevel.WARNING, "Client",
                            _("No desktop proxy settings were found to change. Point applications at {proxy} by hand.")
                            .format(proxy=system_proxy.describe(self.http_port, self.socks_port)))
            # Remembered anyway, so the warning is not repeated every second.
            self._proxy_target = (self.http_port, self.socks_port)
            self.proxy_backends = []

    def _revert_proxy(self) -> None:
        if self._proxy_target is None:
            return
        self._proxy_target = None
        self.proxy_backends = []
        if self.proxy.revert():
            self.append_log(NoticeLevel.INFO, "Client", _("System proxy restored"))
