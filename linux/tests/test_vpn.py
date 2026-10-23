"""
Whole-system VPN mode: what is asked of NetworkManager, the helper that owns
the tun for as long as the engine runs, and the promise that no way of ending
a session leaves the machine without a network.

nmcli and ip are stand-ins (fake_nm.py) on PATH, and the engine is the fake
one, so nothing on the machine running the tests is touched. CI runs the real
thing against NetworkManager and the Psiphon network (connect-check.py --vpn).
"""

import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from nextvpn.core import paths, tunnel_config, vpn, vpn_helper
from nextvpn.core.engine import TunnelEngine
from nextvpn.core.settings import AppSettings, ConnectionMode
from nextvpn.core.status import TunnelState

from .test_engine import FAKE, Loop

HERE = Path(__file__).resolve().parent
LINUX = HERE.parent
FAKE_NM = HERE / "fake_nm.py"

UPLINK = {"dev": "wlan0", "dev6": "wlan0",
          "addresses": {"wlan0": ["192.168.1.20", "2001:db8::20"]},
          "dns": ["192.168.1.1", "2001:db8::1"]}


class FakeSystem(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="nextvpn-vpn-")
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.state = self.dir / "nm"
        self.state.mkdir()
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        for tool in ("nmcli", "ip"):
            exe = bin_dir / tool
            exe.write_text(f"#!{sys.executable}\nimport os, runpy\nos.environ['FAKE_NM_TOOL'] = {tool!r}\n"
                           f"runpy.run_path({str(FAKE_NM)!r}, run_name='__main__')\n")
            exe.chmod(0o755)
        self.set_uplink(UPLINK)

        # Named like the real thing, so the orphan sweep recognises it.
        self.engine_bin = self.dir / "psiphon-tunnel-core"
        self.engine_bin.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(FAKE)!r}, run_name='__main__')\n")
        self.engine_bin.chmod(0o755)
        (self.dir / "base.config").write_text('{"SponsorId":"S","PropagationChannelId":"P"}')
        (self.dir / "server_list.dat").write_text("00")
        self.record = self.dir / "engine.txt"

        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "FAKE_NM_DIR": str(self.state),
               "FAKE_ENGINE_RECORD": str(self.record), "FAKE_ENGINE_SCENARIO": "connect"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_uplink(self, uplink):
        (self.state / "uplink.json").write_text(json.dumps(uplink))

    def calls(self):
        try:
            return [json.loads(line) for line in (self.state / "calls.txt").read_text().splitlines()]
        except FileNotFoundError:
            return []

    def nm_calls(self, *words):
        return [c for c in self.calls() if c[0] == "nmcli" and all(w in c for w in words)]

    def profiles(self):
        try:
            return json.loads((self.state / "profiles.json").read_text())
        except FileNotFoundError:
            return {}

    def add_profile(self, uuid, name, kind):
        p = self.profiles()
        p[uuid] = {"name": name, "type": kind}
        (self.state / "profiles.json").write_text(json.dumps(p))

    def engine_record(self):
        try:
            return self.record.read_text().splitlines()
        except FileNotFoundError:
            return []

    def engine_argv(self):
        for line in self.engine_record():
            if line.startswith("ARGV "):
                return json.loads(line[5:])
        return None

    def write_config(self, packet_tunnel=True):
        return tunnel_config.write_to(self.dir / "runtime.config", (self.dir / "base.config").read_text(),
                                      AppSettings(), self.dir / "tunnel", packet_tunnel)


# ------------------------------------------------------------- the module

class UplinkTests(FakeSystem):
    def test_network_manager_is_found_when_it_runs(self):
        self.assertTrue(vpn.available())

    def test_the_uplink_is_the_default_route_with_its_addresses_and_resolvers(self):
        self.assertEqual(vpn.Uplink("wlan0", ("192.168.1.20", "2001:db8::20"), ("192.168.1.1", "2001:db8::1")),
                         vpn.detect_uplink())

    def test_no_default_route_means_no_uplink(self):
        self.set_uplink({"dev": None, "dev6": None})
        self.assertIsNone(vpn.detect_uplink())

    def test_the_tun_itself_is_never_taken_for_the_uplink(self):
        self.set_uplink({"dev": vpn.IFNAME, "dev6": None})
        self.assertIsNone(vpn.detect_uplink())

    def test_resolvers_fall_back_from_network_manager_to_resolved_to_resolv_conf(self):
        def run(argv, timeout=0):
            if argv[0] == "nmcli":
                return subprocess.CompletedProcess(argv, 10, "", "Error: Device 'wlan0' not found.")
            if argv[0] == "resolvectl":
                return subprocess.CompletedProcess(argv, 0, "Link 3 (wlan0): 10.0.0.1 fe80::1%3\n", "")
            raise OSError
        self.assertEqual(["10.0.0.1", "fe80::1"], vpn.bypass_dns("wlan0", run))

        resolv = self.dir / "resolv.conf"
        resolv.write_text("nameserver 127.0.0.53\nnameserver 9.9.9.9\n")
        no_tools = lambda argv, timeout=0: subprocess.CompletedProcess(argv, 1, "", "")  # noqa: E731
        self.assertEqual(["9.9.9.9"], vpn.bypass_dns("wlan0", no_tools, str(resolv)))

    def test_a_local_stub_resolver_is_never_used_for_the_bypass(self):
        # It would forward the engine's own lookups into the tunnel it is building.
        resolv = self.dir / "resolv.conf"
        resolv.write_text("nameserver 127.0.0.53\nnameserver 198.18.0.2\n")
        no_tools = lambda argv, timeout=0: subprocess.CompletedProcess(argv, 1, "", "")  # noqa: E731
        self.assertEqual(list(vpn.FALLBACK_DNS), vpn.bypass_dns("wlan0", no_tools, str(resolv)))


class ProfileTests(FakeSystem):
    def setUp(self):
        super().setUp()
        self.uplink = vpn.detect_uplink()

    def props(self):
        values = vpn.profile_settings(self.uplink, 1000, "alice")
        return dict(zip(values[::2], values[1::2]))

    def test_the_device_belongs_to_the_user_so_the_engine_needs_no_privileges(self):
        p = self.props()
        self.assertEqual(vpn.IFNAME, p["connection.interface-name"])
        self.assertEqual("1000", p["tun.owner"])
        self.assertEqual("user:alice", p["connection.permissions"])
        # The engine opens it with IFF_TUN | IFF_NO_PI and one queue; any other
        # flag and attaching to it fails.
        self.assertEqual(("tun", "no", "no", "no"),
                         (p["tun.mode"], p["tun.pi"], p["tun.vnet-hdr"], p["tun.multi-queue"]))

    def test_everything_goes_into_the_tunnel_table_except_local_networks(self):
        p = self.props()
        self.assertEqual("0.0.0.0/1 table=28278, 128.0.0.0/1 table=28278", p["ipv4.routes"])
        self.assertEqual("::/1 table=28278, 8000::/1 table=28278", p["ipv6.routes"])
        self.assertEqual("priority 28270 from 192.168.1.20/32 table 254, "
                         "priority 28271 table 254 suppress_prefixlength 0, "
                         "priority 28272 table 28278", p["ipv4.routing-rules"])
        self.assertIn("priority 28270 from 2001:db8::20/128 table 254", p["ipv6.routing-rules"])
        self.assertEqual("yes", p["ipv4.never-default"])

    def test_dns_goes_to_the_tunnel_and_nowhere_else(self):
        p = self.props()
        self.assertEqual(vpn.DNS4, p["ipv4.dns"])
        self.assertEqual("~.", p["ipv4.dns-search"])
        self.assertLess(int(p["ipv4.dns-priority"]), 0)
        self.assertLess(int(p["ipv6.dns-priority"]), 0)

    def test_bring_up_activates_an_in_memory_profile_and_tear_down_removes_it(self):
        uuid = vpn.bring_up(self.uplink, uid_user=(1000, "alice"))
        add = self.nm_calls("connection", "add")[0]
        self.assertEqual(["save", "no", "type", "tun"], add[3:7])
        self.assertEqual("nextvpn0", self.profiles()[uuid]["device"])
        self.assertTrue(self.nm_calls("up", uuid))
        vpn.tear_down(uuid)
        self.assertEqual({}, self.profiles())

    def test_a_refusal_says_why_and_what_to_do(self):
        with mock.patch.dict(os.environ, {"FAKE_NM_FAIL": "auth"}):
            with self.assertRaises(vpn.VpnError) as caught:
                vpn.bring_up(self.uplink, uid_user=(1000, "alice"))
        message = str(caught.exception)
        self.assertIn("Insufficient privileges", message)
        self.assertIn("proxy mode", message)

    def test_a_failed_activation_leaves_no_profile_behind(self):
        with mock.patch.dict(os.environ, {"FAKE_NM_FAIL": "up"}):
            with self.assertRaises(vpn.VpnError):
                vpn.bring_up(self.uplink, uid_user=(1000, "alice"))
        self.assertEqual({}, self.profiles())

    def test_cleanup_removes_only_our_own_profiles(self):
        self.add_profile("11111111-0000-4000-8000-000000000001", "NextVPN", "tun")
        self.add_profile("11111111-0000-4000-8000-000000000002", "Wired connection 1", "802-3-ethernet")
        self.add_profile("11111111-0000-4000-8000-000000000003", "NextVPN", "wireguard")
        self.assertEqual(1, vpn.cleanup())
        self.assertEqual({"11111111-0000-4000-8000-000000000002", "11111111-0000-4000-8000-000000000003"},
                         set(self.profiles()))


# ------------------------------------------------------------- the helper

class Reader:
    def __init__(self, stream):
        self.q = queue.Queue()
        self.lines = []
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream):
        for raw in iter(stream.readline, b""):
            self.q.put(raw.decode().strip())

    def until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            self.lines.append(line)
            if predicate(line):
                return line
        raise AssertionError(f"not seen in time; got {self.lines}")

    def notices(self, kind):
        return [json.loads(l)["data"] for l in self.lines if f'"noticeType": "{kind}"' in l
                or f'"noticeType":"{kind}"' in l]


class HelperProcessTests(FakeSystem):
    def start_helper(self):
        config = self.write_config()
        env = dict(os.environ, PYTHONPATH=str(LINUX))
        proc = subprocess.Popen([sys.executable, "-m", "nextvpn.core.vpn_helper", "--", str(self.engine_bin),
                                 "--config", str(config), "--serverList", str(self.dir / "server_list.dat")],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
        self.addCleanup(proc.stderr.close)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc, Reader(proc.stderr)

    def test_the_engine_runs_on_the_tun_bound_to_the_uplink_and_everything_goes_on_stop(self):
        proc, out = self.start_helper()
        out.until(lambda l: '"count":1' in l.replace(" ", "") and "Tunnels" in l)

        up = out.notices("VpnUp")
        self.assertEqual([{"device": "nextvpn0", "uplink": "wlan0", "dns": "192.168.1.1,2001:db8::1"}], up)
        argv = self.engine_argv()
        self.assertEqual(["-tunDevice", "nextvpn0", "-tunBindInterface", "wlan0",
                          "-tunDNSServers", "192.168.1.1,2001:db8::1"], argv[-6:])
        self.assertEqual(1, len(self.profiles()))

        proc.send_signal(signal.SIGTERM)
        self.assertEqual(0, proc.wait(15))
        self.assertIn("SIGTERM", self.engine_record())
        self.assertEqual({}, self.profiles())

    def test_a_refused_setup_is_reported_and_no_engine_is_started(self):
        with mock.patch.dict(os.environ, {"FAKE_NM_FAIL": "auth"}):
            proc, out = self.start_helper()
            self.assertEqual(4, proc.wait(15))
        out.until(lambda l: "VpnSetupFailed" in l)
        self.assertIn("Insufficient privileges", out.notices("VpnSetupFailed")[0]["message"])
        self.assertIsNone(self.engine_argv())
        self.assertEqual({}, self.profiles())

    def test_no_network_at_all_is_reported_plainly(self):
        self.set_uplink({"dev": None, "dev6": None})
        proc, out = self.start_helper()
        self.assertEqual(3, proc.wait(15))
        out.until(lambda l: "VpnSetupFailed" in l)
        self.assertIn("No network connection", out.notices("VpnSetupFailed")[0]["message"])

    def test_a_profile_left_by_a_crash_is_removed_before_anything_else(self):
        self.add_profile("11111111-0000-4000-8000-000000000009", "NextVPN", "tun")
        proc, out = self.start_helper()
        out.until(lambda l: "VpnUp" in l)
        self.assertNotIn("11111111-0000-4000-8000-000000000009", self.profiles())
        proc.send_signal(signal.SIGTERM)
        proc.wait(15)

    def test_an_engine_that_dies_takes_the_tun_with_it(self):
        with mock.patch.dict(os.environ, {"FAKE_ENGINE_SCENARIO": "error"}):
            proc, out = self.start_helper()
            self.assertEqual(1, proc.wait(20))
        self.assertEqual({}, self.profiles())


class FollowUplinkTests(unittest.TestCase):
    def make(self, uplink):
        helper = vpn_helper.Helper(["engine"])
        helper.uuid = "u"
        helper.uplink = uplink
        helper._stop_engine = mock.Mock()
        helper._start_engine = mock.Mock(return_value=True)
        return helper

    def test_a_new_address_on_the_same_interface_only_moves_the_rules(self):
        helper = self.make(vpn.Uplink("wlan0", ("192.168.1.20",), ("192.168.1.1",)))
        moved = vpn.Uplink("wlan0", ("192.168.1.77",), ("192.168.1.1",))
        with mock.patch.object(vpn, "detect_uplink", return_value=moved), \
                mock.patch.object(vpn, "update_rules") as update, mock.patch.object(vpn_helper, "notice"):
            helper._follow_uplink()
        update.assert_called_once_with("u", moved)
        helper._start_engine.assert_not_called()

    def test_a_new_interface_rebinds_the_engine(self):
        helper = self.make(vpn.Uplink("wlan0", ("192.168.1.20",), ("192.168.1.1",)))
        cable = vpn.Uplink("eth0", ("10.0.0.5",), ("10.0.0.1",))
        with mock.patch.object(vpn, "detect_uplink", return_value=cable), \
                mock.patch.object(vpn, "update_rules"), mock.patch.object(vpn_helper, "notice"):
            helper._follow_uplink()
        helper._stop_engine.assert_called_once()
        helper._start_engine.assert_called_once()
        self.assertEqual("eth0", helper.uplink.iface)

    def test_losing_the_network_for_a_moment_changes_nothing(self):
        helper = self.make(vpn.Uplink("wlan0", ("192.168.1.20",), ("192.168.1.1",)))
        with mock.patch.object(vpn, "detect_uplink", return_value=None), \
                mock.patch.object(vpn, "update_rules") as update:
            helper._follow_uplink()
        update.assert_not_called()
        helper._stop_engine.assert_not_called()


# ------------------------------------------------------- through the engine

class EngineVpnTests(FakeSystem):
    def make_engine(self, loop, available=True):
        ep = paths.EnginePaths(self.engine_bin, self.dir / "base.config", self.dir / "server_list.dat")

        def write(settings, e, packet_tunnel=False):
            return tunnel_config.write_to(self.dir / "runtime.config", e.base_config.read_text(), settings,
                                          self.dir / "tunnel", packet_tunnel)

        engine = TunnelEngine(post=loop.post, engine_paths=lambda: ep, write_config=write,
                              vpn_available=lambda: available)
        self.addCleanup(engine.shutdown, 15)
        return engine

    def test_vpn_mode_connects_through_the_helper_and_disconnects_cleanly(self):
        loop = Loop()
        engine = self.make_engine(loop)
        engine.start(AppSettings(connection_mode=ConnectionMode.VPN))
        loop.pump_until(lambda: engine.state == TunnelState.CONNECTED, timeout=20, what="connected")

        self.assertTrue(engine.vpn_mode)
        self.assertEqual("nextvpn0", engine.telemetry.vpn_device)
        self.assertEqual("wlan0", engine.telemetry.vpn_uplink)
        config = json.loads((self.dir / "runtime.config").read_text())
        self.assertEqual(vpn.DNS4, config["PacketTunnelTransparentDNSIPv4Address"])

        engine.stop()
        loop.pump_until(lambda: engine.state == TunnelState.DISCONNECTED, timeout=20, what="disconnected")
        self.assertEqual({}, self.profiles())

    def test_a_refused_setup_shows_networkmanagers_reason(self):
        loop = Loop()
        engine = self.make_engine(loop)
        details = []
        engine.state_changed.connect(lambda s, d: details.append(d))
        with mock.patch.dict(os.environ, {"FAKE_NM_FAIL": "auth"}):
            engine.start(AppSettings(connection_mode=ConnectionMode.VPN))
            loop.pump_until(lambda: engine.state == TunnelState.FAULTED, timeout=20, what="faulted")
        self.assertTrue(details[-1].startswith("NetworkManager could not create the VPN interface"))
        self.assertIn("Insufficient privileges", details[-1])

    def test_without_network_manager_the_proxy_mode_engine_runs(self):
        loop = Loop()
        engine = self.make_engine(loop, available=False)
        engine.start(AppSettings(connection_mode=ConnectionMode.VPN))
        loop.pump_until(lambda: engine.state == TunnelState.CONNECTED, timeout=20, what="connected")
        self.assertFalse(engine.vpn_mode)
        self.assertTrue(engine.vpn_unavailable)
        self.assertNotIn("-tunDevice", self.engine_argv())
        self.assertNotIn("PacketTunnelTransparentDNSIPv4Address",
                         json.loads((self.dir / "runtime.config").read_text()))

    def test_a_killed_app_still_gets_its_network_back(self):
        script = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(LINUX)!r})
            from pathlib import Path
            from nextvpn.core import paths, tunnel_config
            from nextvpn.core.engine import TunnelEngine
            from nextvpn.core.settings import AppSettings
            d = Path({str(self.dir)!r})
            ep = paths.EnginePaths(d / "psiphon-tunnel-core", d / "base.config", d / "server_list.dat")
            def write(s, e, packet_tunnel=False):
                return tunnel_config.write_to(d / "child.config", e.base_config.read_text(), s, d / "t",
                                              packet_tunnel)
            engine = TunnelEngine(post=lambda fn, *a: fn(*a), engine_paths=lambda: ep, write_config=write,
                                  vpn_available=lambda: True)
            engine.start(AppSettings())
            print("started", flush=True)
            time.sleep(60)
        """)
        app = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        self.addCleanup(app.stdout.close)
        try:
            self.assertEqual("started", app.stdout.readline().strip())
            deadline = time.monotonic() + 15
            while not (self.profiles() and any(l.startswith("ARGV") for l in self.engine_record())):
                self.assertLess(time.monotonic(), deadline, "the VPN never came up")
                time.sleep(0.05)

            app.send_signal(signal.SIGKILL)
            app.wait(5)
            deadline = time.monotonic() + 15
            while self.profiles() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual({}, self.profiles(), "the tun outlived the app")
            self.assertIn("SIGTERM", self.engine_record())
        finally:
            if app.poll() is None:
                app.kill()


if __name__ == "__main__":
    unittest.main()
