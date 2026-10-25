"""
The view model's decisions about the system proxy and the session, driven by a
stand-in engine. The rule that matters most: the desktop stays pointed at the
tunnel while it reconnects, so traffic never quietly goes around it, and is
handed back as soon as the session really ends.
"""

import tempfile
import unittest
from pathlib import Path

try:
    import gi
    gi.require_version("GObject", "2.0")
    from gi.repository import GObject  # noqa: F401
    HAVE_GI = True
except (ImportError, ValueError):
    HAVE_GI = False

from nextvpn.core.engine import Signal
from nextvpn.core.notice import Notice
from nextvpn.core.settings import AppSettings
from nextvpn.core.status import TunnelState
from nextvpn.core.system_proxy import SystemProxy
from nextvpn.core.telemetry import TunnelTelemetry
from tests.test_system_proxy import FakeBackend


class StubEngine:
    def __init__(self):
        self.telemetry = TunnelTelemetry()
        self.verbose = False
        self.state = TunnelState.DISCONNECTED
        self.calls = []
        self.vpn_mode = False
        self.vpn_unavailable = False
        self.is_running = False
        self.STOP_GRACE_SECONDS = 5.0
        self.VPN_STOP_GRACE_SECONDS = 12.0
        self.state_changed, self.notice_received = Signal(), Signal()
        self.output_received, self.stats_updated, self.regions_updated = Signal(), Signal(), Signal()

    @property
    def stats(self):
        return self.telemetry.stats

    def start(self, settings):
        self.calls.append(("start", settings.egress_region))

    def stop(self):
        self.calls.append(("stop",))

    def restart(self, settings):
        self.calls.append(("restart", settings.egress_region))

    def shutdown(self):
        self.calls.append(("shutdown",))

    # Plays the part of the real engine's main-loop side.
    def feed(self, line):
        n = Notice.parse(line)
        self.telemetry.apply(n)
        self.notice_received.emit(n)

    def set_state(self, state, detail=None):
        self.state = state
        self.state_changed.emit(state, detail)

    def ports(self, http, socks):
        self.feed(f'{{"noticeType":"ListeningHttpProxyPort","data":{{"port":{http}}}}}')
        self.feed(f'{{"noticeType":"ListeningSocksProxyPort","data":{{"port":{socks}}}}}')


@unittest.skipUnless(HAVE_GI, "needs PyGObject")
class ViewModelTests(unittest.TestCase):
    def setUp(self):
        from nextvpn.ui.viewmodel import MainViewModel
        self._tmp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend()
        self.proxy = SystemProxy(Path(self._tmp.name) / "backup.json", [self.backend])
        self.settings = AppSettings()
        self.settings.save = lambda: None   # nothing on disk from these tests
        self.engine = StubEngine()
        self.vm = MainViewModel(self.settings, engine=self.engine, proxy=self.proxy)

    def tearDown(self):
        self.vm._stop_tick()
        self._tmp.cleanup()

    def connect_session(self, http=41002, socks=41001):
        self.vm.connect_tunnel()
        self.engine.set_state(TunnelState.CONNECTING)
        self.engine.ports(http, socks)
        self.engine.feed('{"noticeType":"Tunnels","data":{"count":1}}')
        self.engine.set_state(TunnelState.CONNECTED)

    def test_a_slow_connection_to_one_country_suggests_best_performance(self):
        self.settings.egress_region = "JP"
        self.vm.connect_tunnel()
        self.engine.set_state(TunnelState.CONNECTING)
        self.assertEqual("Finding a route that works on this network", self.vm.status_subtitle)
        self.vm._connecting_since -= self.vm.SLOW_CONNECT_SECONDS
        self.assertIn("Japan", self.vm.status_subtitle)
        self.assertIn("Best performance", self.vm.status_subtitle)
        # A redial does not restart the count; a finished attempt does.
        self.engine.set_state(TunnelState.CONNECTING)
        self.assertTrue(self.vm.slow_to_connect)
        self.engine.set_state(TunnelState.DISCONNECTED)
        self.assertFalse(self.vm.slow_to_connect)

    def pump(self, seconds=0.2):
        from gi.repository import GLib
        import time as _time
        deadline = _time.monotonic() + seconds
        context = GLib.MainContext.default()
        while _time.monotonic() < deadline:
            context.iteration(False)

    def test_quitting_with_nothing_running_finishes_straight_away(self):
        done = []
        self.vm.stop_for_exit(lambda: done.append(1))
        self.pump()
        self.assertEqual([1], done)

    def test_quitting_waits_for_the_engine_without_blocking_and_finishes_once(self):
        done = []
        self.engine.is_running = True
        self.vm.stop_for_exit(lambda: done.append(1))
        self.assertIn(("stop",), self.engine.calls)
        self.pump()
        self.assertEqual([], done)                       # still stopping
        self.engine.set_state(TunnelState.DISCONNECTING)
        self.engine.set_state(TunnelState.DISCONNECTED)
        self.pump()
        self.assertEqual([1], done)
        self.engine.set_state(TunnelState.DISCONNECTED)  # no second call
        self.pump()
        self.assertEqual([1], done)

    def test_drawing_without_the_graphics_card_is_explained_in_the_log(self):
        self.vm.set_renderer("GskCairoRenderer")
        self.assertTrue(self.vm.software_rendering)
        self.assertIn("without the graphics card", self.vm.log[-1].message)
        self.assertEqual("warning", self.vm.log[-1].level.name.lower())

    def test_a_software_gl_driver_counts_as_no_graphics_card(self):
        self.vm.set_renderer("GskNglRenderer", "llvmpipe (LLVM 19.1.7, 256 bits)")
        self.assertTrue(self.vm.software_rendering)
        self.assertIn("llvmpipe", self.vm.renderer_text)

    def test_a_real_graphics_card_is_only_noted(self):
        self.vm.set_renderer("GskNglRenderer", "AMD Radeon RX 6600 (radeonsi, navi23, LLVM 19.1.7)")
        self.assertFalse(self.vm.software_rendering)
        self.assertEqual("info", self.vm.log[-1].level.name.lower())
        self.assertEqual("GskNglRenderer, AMD Radeon RX 6600 (radeonsi, navi23, LLVM 19.1.7)",
                         self.vm.renderer_text)

    def test_in_vpn_mode_the_system_proxy_is_left_alone(self):
        # Everything already goes through the tun; pointing programs at the
        # local proxy as well would only add a hop.
        self.engine.vpn_mode = True
        self.connect_session()
        self.assertEqual({"mode": "none", "port": 0}, self.backend.store)
        self.assertFalse(self.vm.proxy_applied)
        self.assertEqual("VPN: all traffic", self.vm.mode_text)

    def test_the_home_page_says_when_vpn_mode_fell_back_to_the_proxy(self):
        self.engine.vpn_unavailable = True
        self.connect_session()
        self.assertEqual({"mode": "manual", "port": 41002}, self.backend.store)
        self.assertEqual("System proxy: VPN mode needs NetworkManager", self.vm.mode_text)

    def test_proxy_mode_reports_the_system_proxy(self):
        from nextvpn.core.settings import ConnectionMode
        self.settings.connection_mode = ConnectionMode.PROXY
        self.connect_session()
        self.assertTrue(self.vm.mode_text.startswith("System proxy: "))

    def test_the_proxy_is_applied_only_once_the_tunnel_is_up(self):
        self.vm.connect_tunnel()
        self.engine.set_state(TunnelState.CONNECTING)
        self.engine.ports(41002, 41001)
        self.assertEqual({"mode": "none", "port": 0}, self.backend.store)   # not yet
        self.engine.set_state(TunnelState.CONNECTED)
        self.assertEqual({"mode": "manual", "port": 41002}, self.backend.store)
        self.assertTrue(self.vm.proxy_applied)

    def test_a_reconnect_keeps_the_desktop_on_the_tunnel_and_follows_new_ports(self):
        self.connect_session()
        # A region change rebuilds the tunnel: tearing down, dialling, up again.
        self.engine.set_state(TunnelState.DISCONNECTING)
        self.assertEqual({"mode": "manual", "port": 41002}, self.backend.store)
        self.engine.telemetry.clear_listeners()
        self.engine.set_state(TunnelState.CONNECTING)
        self.assertEqual({"mode": "manual", "port": 41002}, self.backend.store)
        self.engine.ports(42002, 42001)
        self.engine.set_state(TunnelState.CONNECTED)
        self.assertEqual({"mode": "manual", "port": 42002}, self.backend.store)
        # And the original settings are still what comes back at the end.
        self.engine.set_state(TunnelState.DISCONNECTED)
        self.assertEqual({"mode": "none", "port": 0}, self.backend.store)

    def test_a_mid_session_drop_does_not_hand_the_proxy_back(self):
        self.connect_session()
        self.engine.feed('{"noticeType":"Tunnels","data":{"count":0}}')
        self.engine.set_state(TunnelState.CONNECTING)
        self.assertTrue(self.vm.proxy_applied)

    def test_a_failure_hands_the_proxy_back(self):
        self.connect_session()
        self.engine.set_state(TunnelState.FAULTED, "engine died")
        self.assertEqual({"mode": "none", "port": 0}, self.backend.store)
        self.assertTrue(self.vm.is_faulted)
        self.assertEqual("engine died", self.vm.status_subtitle)

    def test_turning_the_setting_off_mid_session_hands_the_proxy_back_at_once(self):
        self.connect_session()
        self.settings.set_system_proxy = False
        self.vm.notify_settings_changed()
        self.assertEqual({"mode": "none", "port": 0}, self.backend.store)
        self.settings.set_system_proxy = True
        self.vm.notify_settings_changed()
        self.assertEqual({"mode": "manual", "port": 41002}, self.backend.store)

    def test_quitting_hands_the_proxy_back_and_stops_the_engine(self):
        self.connect_session()
        self.vm.shutdown()
        self.assertEqual({"mode": "none", "port": 0}, self.backend.store)
        self.assertIn(("shutdown",), self.engine.calls)

    def test_choosing_a_region_while_connected_rebuilds_the_tunnel(self):
        from nextvpn.core.regions import Regions
        self.connect_session()
        self.vm.select_region(Regions.describe("DE"))
        self.assertEqual("DE", self.settings.egress_region)
        self.assertIn(("restart", "DE"), self.engine.calls)

    def test_choosing_a_region_while_idle_only_remembers_it(self):
        from nextvpn.core.regions import Regions
        self.vm.select_region(Regions.describe("NL"))
        self.assertEqual("NL", self.settings.egress_region)
        self.assertFalse([c for c in self.engine.calls if c[0] in ("start", "restart")])

    def test_the_region_list_is_remembered_for_the_next_launch(self):
        self.engine.feed('{"noticeType":"AvailableEgressRegions","data":{"regions":["US","DE"]}}')
        self.engine.regions_updated.emit()
        self.assertEqual(["DE", "US"], self.settings.known_regions)
        codes = [r.code for r in self.vm.available_regions]
        self.assertEqual(["", "DE", "US"], codes)

    def test_a_saved_region_stays_visible_before_the_engine_reports_any(self):
        from nextvpn.ui.viewmodel import MainViewModel
        settings = AppSettings(egress_region="JP")
        vm = MainViewModel(settings, engine=StubEngine(), proxy=self.proxy)
        self.assertIn("JP", [r.code for r in vm.available_regions])

    def test_toggle_follows_the_state(self):
        self.vm.toggle()
        self.assertEqual(("start", ""), self.engine.calls[-1])
        self.engine.set_state(TunnelState.CONNECTING)
        self.vm.toggle()
        self.assertEqual(("stop",), self.engine.calls[-1])
        self.engine.set_state(TunnelState.DISCONNECTING)
        count = len(self.engine.calls)
        self.vm.toggle()   # dead while tearing down
        self.assertEqual(count, len(self.engine.calls))

    def test_throughput_samples_feed_the_graph_and_are_bounded(self):
        self.connect_session()
        for _ in range(100):
            self.engine.feed('{"noticeType":"BytesTransferred","data":{"sent":10,"received":100}}')
        self.assertEqual(self.vm.MAX_RATE_SAMPLES, len(self.vm.rate_history))
        self.assertEqual(1000, self.engine.stats.bytes_sent)

    def test_the_log_is_bounded_and_copyable(self):
        for i in range(self.vm.MAX_LOG_ENTRIES + 10):
            self.engine.feed(f'{{"noticeType":"Warning","data":{{"message":"w{i}"}}}}')
        self.assertEqual(self.vm.MAX_LOG_ENTRIES, len(self.vm.log))
        text = self.vm.log_text()
        self.assertIn("Warning  w1509", text)
        self.assertNotIn("w0\n", text)


if __name__ == "__main__":
    unittest.main()
