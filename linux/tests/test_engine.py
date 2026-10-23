"""
The engine process: start, the notices that move the state machine, stop,
restart, failure, and the guarantee that an engine never outlives the client.

Driven by a fake engine that speaks the real notice protocol. A smoke test
against the real binary runs when NEXTVPN_REAL_ENGINE_TEST=1.
"""

import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from nextvpn.core import engine as engine_module
from nextvpn.core import paths, tunnel_config
from nextvpn.core.engine import TunnelEngine, kill_orphaned_engines
from nextvpn.core.settings import AppSettings
from nextvpn.core.status import TunnelState

HERE = Path(__file__).resolve().parent
LINUX = HERE.parent
FAKE = HERE / "fake_engine.py"


class Loop:
    """Stands in for the GLib main loop: posts queue up, the test pumps them."""

    def __init__(self):
        self.q = queue.Queue()

    def post(self, fn, *args):
        self.q.put((fn, args))

    def pump(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._one(0.02)

    def pump_until(self, predicate, timeout=10.0, what="condition"):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {what}")
            self._one(0.02)

    def _one(self, wait):
        try:
            fn, args = self.q.get(timeout=wait)
        except queue.Empty:
            return
        fn(*args)


def process_gone(pid):
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("State:"):
                    return "Z" in line.split()[1]
    except OSError:
        return True
    return False


class Harness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="nextvpn-engine")
        self.dir = Path(self._tmp.name)
        self.record = self.dir / "record.txt"

        # Named like the real thing, so the orphan sweep recognises it.
        self.binary = self.dir / "psiphon-tunnel-core"
        self.binary.write_text(f"#!{sys.executable}\nimport runpy, sys\n"
                               f"runpy.run_path({str(FAKE)!r}, run_name='__main__')\n")
        self.binary.chmod(0o755)
        (self.dir / "base.config").write_text('{"SponsorId":"S","PropagationChannelId":"P"}')
        (self.dir / "server_list.dat").write_text("00")

        self.engine_paths = paths.EnginePaths(self.binary, self.dir / "base.config",
                                              self.dir / "server_list.dat")
        self.config_path = self.dir / "runtime.config"

        os.environ["FAKE_ENGINE_RECORD"] = str(self.record)
        os.environ["FAKE_ENGINE_SCENARIO"] = "connect"

        self.loop = Loop()
        self.engine = self.make_engine(self.engine_paths)
        self.states = []
        self.details = []
        self.engine.state_changed.connect(lambda s, d: (self.states.append(s), self.details.append(d)))

    def make_engine(self, engine_paths):
        def write(settings, ep):
            return tunnel_config.write_to(self.config_path, ep.base_config.read_text(), settings,
                                          self.dir / "tunnel")
        # Never a real VPN from a test, even where NetworkManager runs.
        return TunnelEngine(post=self.loop.post, engine_paths=lambda: engine_paths, write_config=write,
                            vpn_available=lambda: False)

    def tearDown(self):
        self.engine.shutdown(timeout=2)
        os.environ.pop("FAKE_ENGINE_RECORD", None)
        os.environ.pop("FAKE_ENGINE_SCENARIO", None)
        self._tmp.cleanup()

    def recorded(self):
        try:
            return self.record.read_text().splitlines()
        except FileNotFoundError:
            return []

    def connect(self, settings=None):
        self.engine.start(settings or AppSettings())
        self.loop.pump_until(lambda: self.engine.state == TunnelState.CONNECTED, what="connected")


class EngineLifecycleTests(Harness):
    def test_a_full_session_connects_and_disconnects_gracefully(self):
        stats = []
        regions = []
        self.engine.stats_updated.connect(lambda: stats.append(1))
        self.engine.regions_updated.connect(lambda: regions.append(1))

        self.connect()
        self.assertEqual([TunnelState.CONNECTING, TunnelState.CONNECTED], self.states)
        self.assertEqual(41002, self.engine.telemetry.http_port)
        self.assertEqual(41001, self.engine.telemetry.socks_port)
        self.assertEqual("OSSH", self.engine.telemetry.active_protocol)
        self.assertEqual(["DE", "NL", "US"], self.engine.telemetry.available_regions)
        self.assertTrue(regions)

        self.loop.pump_until(lambda: len(stats) >= 2, what="throughput")
        pid = self.engine.pid

        self.engine.stop()
        self.assertEqual(TunnelState.DISCONNECTING, self.engine.state)
        self.loop.pump_until(lambda: self.engine.state == TunnelState.DISCONNECTED, what="disconnected")

        self.assertEqual([TunnelState.CONNECTING, TunnelState.CONNECTED,
                          TunnelState.DISCONNECTING, TunnelState.DISCONNECTED], self.states)
        self.assertIn("SIGTERM", self.recorded())   # asked, not killed
        self.assertIn("EXITED", self.recorded())
        self.assertTrue(process_gone(pid))
        # The totals stay on screen after a disconnect; the listeners do not.
        self.assertEqual(0, self.engine.telemetry.http_port)
        self.assertGreater(self.engine.stats.bytes_received, 0)

    def test_the_engine_is_given_the_config_and_the_server_list(self):
        self.connect()
        argv = json.loads(next(l for l in self.recorded() if l.startswith("ARGV "))[5:])
        self.assertEqual(["--config", str(self.config_path),
                          "--serverList", str(self.engine_paths.server_list)], argv)
        config = json.loads(self.config_path.read_text())
        self.assertEqual("S", config["SponsorId"])
        self.assertEqual("P", config["PropagationChannelId"])

    def test_cancelling_while_connecting_stops_the_engine(self):
        self.engine.start(AppSettings())
        self.assertEqual(TunnelState.CONNECTING, self.engine.state)
        self.engine.stop()
        self.loop.pump_until(lambda: self.engine.state == TunnelState.DISCONNECTED, what="disconnected")
        self.assertNotIn(TunnelState.FAULTED, self.states)

    def test_a_mid_session_drop_goes_back_to_connecting_and_recovers(self):
        os.environ["FAKE_ENGINE_SCENARIO"] = "redial"
        self.connect()
        self.loop.pump_until(lambda: self.states.count(TunnelState.CONNECTED) >= 2, what="redial")
        self.assertEqual([TunnelState.CONNECTING, TunnelState.CONNECTED,
                          TunnelState.CONNECTING, TunnelState.CONNECTED], self.states)

    def test_restart_rebuilds_the_tunnel_with_the_new_settings(self):
        self.connect()
        first = self.engine.pid
        self.states.clear()

        self.engine.restart(AppSettings(egress_region="DE"))
        self.loop.pump_until(lambda: self.engine.state == TunnelState.CONNECTED and self.engine.pid != first,
                             what="reconnected")

        # Straight from tearing down to dialling: no flash of "Not connected".
        self.assertEqual([TunnelState.DISCONNECTING, TunnelState.CONNECTING, TunnelState.CONNECTED], self.states)
        self.assertIn("REGION DE", self.recorded())
        self.assertTrue(process_gone(first))
        self.assertEqual("DE", self.engine.telemetry.connected_region)

    def test_a_start_while_stopping_waits_for_the_old_engine_to_go(self):
        self.connect()
        first = self.engine.pid
        self.engine.stop()
        self.engine.start(AppSettings(egress_region="NL"))
        self.loop.pump_until(lambda: self.engine.state == TunnelState.CONNECTED and self.engine.pid != first,
                             what="second session")
        self.assertTrue(process_gone(first))

    def test_an_engine_that_ignores_sigterm_is_killed_after_the_grace_period(self):
        os.environ["FAKE_ENGINE_SCENARIO"] = "stubborn"
        self.engine.STOP_GRACE_SECONDS = 0.5
        self.connect()
        pid = self.engine.pid
        self.engine.stop()
        self.loop.pump_until(lambda: self.engine.state == TunnelState.DISCONNECTED, timeout=5, what="killed")
        self.assertIn("SIGTERM-IGNORED", self.recorded())
        self.assertTrue(process_gone(pid))

    def test_shutdown_is_synchronous_and_quiet(self):
        self.connect()
        pid = self.engine.pid
        self.states.clear()
        self.engine.shutdown(timeout=3)
        self.assertTrue(process_gone(pid))
        self.loop.pump(0.3)
        self.assertEqual([], self.states)   # nothing left to tell anyone

    def test_platform_identity_reaches_the_engine(self):
        self.connect()
        platform = next(l for l in self.recorded() if l.startswith("PLATFORM "))[9:]
        self.assertTrue(platform.startswith("Windows_"), platform)


class EngineFailureTests(Harness):
    def test_an_engine_error_becomes_the_reason_shown(self):
        os.environ["FAKE_ENGINE_SCENARIO"] = "error"
        self.engine.start(AppSettings())
        self.loop.pump_until(lambda: self.engine.state == TunnelState.FAULTED, what="fault")
        self.assertIn("error loading configuration file", self.details[-1])

    def test_a_crash_with_a_go_panic_is_reported_and_logged(self):
        os.environ["FAKE_ENGINE_SCENARIO"] = "panic"
        output = []
        self.engine.output_received.connect(lambda o: output.append(o.text))
        self.engine.start(AppSettings())
        self.loop.pump_until(lambda: self.engine.state == TunnelState.FAULTED, what="fault")
        self.assertIn("panic: assignment to entry in nil map", self.details[-1])
        self.assertIn("goroutine 1 [running]:", output)

    def test_a_missing_engine_is_a_fault_not_a_crash(self):
        missing = paths.EnginePaths(None, self.dir / "base.config", self.dir / "server_list.dat")
        engine = self.make_engine(missing)
        details = []
        engine.state_changed.connect(lambda s, d: details.append((s, d)))
        engine.start(AppSettings())
        self.assertEqual(TunnelState.FAULTED, engine.state)
        self.assertIn("not found", details[-1][1])

    def test_a_missing_server_list_is_a_fault(self):
        broken = paths.EnginePaths(self.binary, self.dir / "base.config", self.dir / "nope.dat")
        engine = self.make_engine(broken)
        engine.start(AppSettings())
        self.assertEqual(TunnelState.FAULTED, engine.state)

    def test_stopping_when_nothing_runs_just_settles_on_disconnected(self):
        self.engine.stop()
        self.assertEqual(TunnelState.DISCONNECTED, self.engine.state)


class EngineLifetimeTests(Harness):
    def test_an_orphaned_engine_with_our_config_is_cleared_before_starting(self):
        self.config_path.write_text("{}")
        orphan = subprocess.Popen([str(self.binary), "--config", str(self.config_path),
                                   "--serverList", str(self.engine_paths.server_list)],
                                  stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            time.sleep(0.5)
            found = kill_orphaned_engines(self.config_path)
            self.assertEqual([orphan.pid], found)
            orphan.wait(5)
        finally:
            if orphan.poll() is None:
                orphan.kill()

    def test_an_engine_never_outlives_the_client_even_after_sigkill(self):
        # A client process that starts an engine and is then killed outright.
        script = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(LINUX)!r})
            from pathlib import Path
            from nextvpn.core import paths, tunnel_config
            from nextvpn.core.engine import TunnelEngine
            from nextvpn.core.settings import AppSettings
            ep = paths.EnginePaths(Path({str(self.binary)!r}), Path({str(self.dir / 'base.config')!r}),
                                   Path({str(self.dir / 'server_list.dat')!r}))
            def write(s, e):
                return tunnel_config.write_to(Path({str(self.dir / 'child.config')!r}),
                                              e.base_config.read_text(), s, {str(self.dir)!r})
            engine = TunnelEngine(post=lambda fn, *a: fn(*a), engine_paths=lambda: ep, write_config=write,
                                  vpn_available=lambda: False)
            engine.start(AppSettings())
            print(engine.pid, flush=True)
            time.sleep(60)
        """)
        client = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        self.addCleanup(client.stdout.close)
        try:
            engine_pid = int(client.stdout.readline())
            self.assertFalse(process_gone(engine_pid))
            client.send_signal(signal.SIGKILL)
            client.wait(5)
            deadline = time.monotonic() + 5
            while not process_gone(engine_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(process_gone(engine_pid), "engine outlived its client")
        finally:
            if client.poll() is None:
                client.kill()


@unittest.skipUnless(os.environ.get("NEXTVPN_REAL_ENGINE_TEST") == "1",
                     "set NEXTVPN_REAL_ENGINE_TEST=1 to run against the real engine")
class RealEngineSmokeTest(unittest.TestCase):
    """The shipped binary, the shipped base config and server list."""

    def test_the_real_engine_starts_reports_and_stops_on_request(self):
        ep = paths.engine()
        if ep.binary is None:
            self.skipTest("no engine binary available")
        loop = Loop()
        with tempfile.TemporaryDirectory() as d:
            def write(settings, e):
                return tunnel_config.write_to(Path(d) / "runtime.config", tunnel_config.read_base_config(e),
                                              settings, Path(d) / "tunnel")
            engine = TunnelEngine(post=loop.post, engine_paths=lambda: ep, write_config=write,
                                  vpn_available=lambda: False)
            notices = []
            engine.notice_received.connect(lambda n: notices.append(n.type))
            try:
                engine.start(AppSettings(upstream_proxy_url=os.environ.get("NEXTVPN_TEST_UPSTREAM", "")))
                loop.pump_until(lambda: engine.telemetry.http_port > 0 and engine.telemetry.available_regions,
                                timeout=30, what="listeners and regions")
                self.assertEqual(TunnelState.CONNECTING, engine.state)
                engine.stop()
                loop.pump_until(lambda: engine.state == TunnelState.DISCONNECTED, timeout=15, what="stop")
            finally:
                engine.shutdown()
            self.assertIn("ListeningHttpProxyPort", notices)


if __name__ == "__main__":
    unittest.main()
