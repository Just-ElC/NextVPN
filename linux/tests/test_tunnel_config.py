"""
The generated engine configuration. Two things matter here: the sponsor and
crypto material from the base config has to survive untouched, because that is
what puts this client on the same servers as the Windows build, and every field
that would make the engine rewrite files outside its own directory has to be
gone whether or not the base config asked for it.
"""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from nextvpn.core import paths, tunnel_config
from nextvpn.core.settings import AppSettings, ClientPlatform
from nextvpn.core.tunnel_config import InvalidConfigError

BASE_CONFIG = r"""
{
    "PropagationChannelId": "FFFFFFFFFFFFFFFF",
    "SponsorId": "0000000000000000",
    "RemoteServerListUrl": "https://example.invalid/list",
    "RemoteServerListSignaturePublicKey": "abc123",
    "AdditionalParameters": "opaque-blob",
    "EnableUpgradeDownload": true,
    "UpgradeDownloadUrl": "https://example.invalid/upgrade",
    "UpgradeDownloadURLs": ["https://example.invalid/upgrade"],
    "UpgradeDownloadFilename": "psiphon3.exe.upgrade",
    "UpgradeDownloadClientVersionHeader": "x-amz-meta-psiphon-client-version",
    "MigrateDataStoreDirectory": "C:\\Users\\Someone\\AppData\\Roaming\\Psiphon3",
    "MigrateObfuscatedServerListDownloadDirectory": "C:\\Users\\Someone\\AppData\\Roaming\\Psiphon3",
    "MigrateRemoteServerListDownloadFilename": "C:\\Users\\Someone\\remote_server_list",
    "MigrateUpgradeDownloadFilename": "C:\\Users\\Someone\\psiphon3.exe.upgrade",
    "LimitTunnelProtocols": ["FRONTED-MEEK-OSSH"],
    "NetworkLatencyMultiplier": 9.0,
    "EstablishTunnelTimeoutSeconds": 300,
    "SplitTunnelOwnRegion": true
}
"""


def build(settings=None, data_root="/data/tunnel"):
    return json.loads(tunnel_config.build(BASE_CONFIG, settings or AppSettings(), data_root))


class TunnelConfigTests(unittest.TestCase):
    # --------------------------------------------------- self-modification

    def test_fields_that_rewrite_files_outside_our_own_directory_are_stripped(self):
        config = build()
        for field in ("UpgradeDownloadURLs", "UpgradeDownloadFilename", "UpgradeDownloadClientVersionHeader",
                      "MigrateDataStoreDirectory", "MigrateObfuscatedServerListDownloadDirectory",
                      "MigrateRemoteServerListDownloadFilename", "MigrateUpgradeDownloadFilename"):
            self.assertNotIn(field, config)

    def test_upgrade_download_is_forced_off_even_when_the_base_config_enables_it(self):
        self.assertIs(False, build()["EnableUpgradeDownload"])

    # -------------------------------------------------------- pass-through

    def test_sponsor_and_crypto_material_is_passed_through_untouched(self):
        config = build()
        for field, expected in [("PropagationChannelId", "FFFFFFFFFFFFFFFF"), ("SponsorId", "0000000000000000"),
                                ("RemoteServerListSignaturePublicKey", "abc123"),
                                ("AdditionalParameters", "opaque-blob"),
                                ("RemoteServerListUrl", "https://example.invalid/list")]:
            self.assertEqual(expected, config[field])

    def test_the_shipped_base_config_keeps_its_server_identity(self):
        # The real file in engine/, the one the Windows build also ships.
        base_path = paths.REPO_DIR / "engine" / "base.config"
        if not base_path.is_file():
            self.skipTest("engine/base.config is not part of this tree")
        base = json.loads(base_path.read_text(encoding="utf-8"))
        built = json.loads(tunnel_config.build(base_path.read_text(encoding="utf-8"), AppSettings(), "/d"))
        for field in ("PropagationChannelId", "SponsorId", "AdditionalParameters",
                      "RemoteServerListSignaturePublicKey", "ServerEntrySignaturePublicKey",
                      "RemoteServerListURLs", "ObfuscatedServerListRootURLs",
                      "FeedbackEncryptionPublicKey", "ClientVersion"):
            self.assertEqual(base[field], built[field], field)

    # ---------------------------------------------------------- our fields

    def test_exit_region_comes_from_the_settings(self):
        self.assertEqual("DE", build(AppSettings(egress_region="DE"))["EgressRegion"])

    def test_best_performance_is_expressed_as_an_empty_region(self):
        config = build(AppSettings(egress_region=""))
        self.assertIn("EgressRegion", config)
        self.assertEqual("", config["EgressRegion"])

    def test_local_proxy_ports_are_written_even_when_zero(self):
        config = build(AppSettings(local_http_proxy_port=0, local_socks_proxy_port=1080))
        self.assertEqual(0, config["LocalHttpProxyPort"])
        self.assertEqual(1080, config["LocalSocksProxyPort"])

    def test_the_data_directory_is_the_one_we_were_given(self):
        self.assertEqual("/somewhere/else", build(AppSettings(), "/somewhere/else")["DataRootDirectory"])

    def test_chosen_transports_replace_whatever_the_base_config_listed(self):
        config = build(AppSettings(limit_tunnel_protocols=["OSSH", "QUIC-OSSH"]))
        self.assertEqual(["OSSH", "QUIC-OSSH"], config["LimitTunnelProtocols"])

    def test_no_chosen_transports_means_the_engine_is_left_free_to_choose(self):
        self.assertNotIn("LimitTunnelProtocols", build())

    def test_split_tunnelling_is_removed_when_it_is_off(self):
        self.assertNotIn("SplitTunnelOwnRegion", build(AppSettings(split_tunnel_own_region=False)))
        self.assertIs(True, build(AppSettings(split_tunnel_own_region=True))["SplitTunnelOwnRegion"])

    def test_relaxed_timeouts_set_both_knobs_together(self):
        config = build(AppSettings(disable_timeouts=True))
        self.assertEqual(3.0, config["NetworkLatencyMultiplier"])
        self.assertEqual(0, config["EstablishTunnelTimeoutSeconds"])

    def test_normal_timeouts_clear_the_ones_the_base_config_set(self):
        config = build(AppSettings(disable_timeouts=False))
        self.assertNotIn("NetworkLatencyMultiplier", config)
        self.assertNotIn("EstablishTunnelTimeoutSeconds", config)

    def test_upstream_proxy_is_always_written_so_clearing_it_takes_effect(self):
        self.assertEqual("http://user:pass@host:8080",
                         build(AppSettings(upstream_proxy_url="http://user:pass@host:8080"))["UpstreamProxyUrl"])
        self.assertEqual("", build()["UpstreamProxyUrl"])

    def test_telemetry_the_interface_depends_on_is_switched_on(self):
        config = build()
        for field in ("EmitBytesTransferred", "EmitDiagnosticNotices",
                      "EmitDiagnosticNetworkParameters", "EmitServerAlerts"):
            self.assertIs(True, config[field], field)

    # ---------------------------------------------------- client platform

    def test_by_default_the_client_identifies_like_the_windows_build(self):
        # The server classifies by prefix alone: Windows* is Windows, the rest "Other".
        platform = build()["ClientPlatform"]
        parts = platform.split("_")
        self.assertEqual(3, len(parts))
        self.assertEqual("Windows", parts[0])
        self.assertEqual("NextVPN", parts[2])
        self.assertNotIn(" ", platform)

    def test_the_client_can_identify_as_linux_instead(self):
        platform = build(AppSettings(client_platform=ClientPlatform.LINUX))["ClientPlatform"]
        self.assertTrue(platform.startswith("Linux_"))
        self.assertTrue(platform.endswith("_NextVPN"))

    def test_the_version_part_never_carries_a_separator(self):
        for release, expected in [("6.18.44-fc-v139", "6.18.44"), ("6.6.30_custom", "6.6.30"),
                                  ("weird release", "0"), ("", "0")]:
            self.assertEqual(f"Windows_{expected}_NextVPN",
                             tunnel_config.client_platform(ClientPlatform.WINDOWS, release))

    # --------------------------------------------------------------- shape

    def test_output_is_one_line_of_json(self):
        text = tunnel_config.build(BASE_CONFIG, AppSettings(), "/data")
        self.assertNotIn("\n", text)
        json.loads(text)

    def test_a_base_config_that_is_not_an_object_is_rejected(self):
        for text in ("[]", '"text"', "null"):
            with self.assertRaises(InvalidConfigError):
                tunnel_config.build(text, AppSettings(), "/data")

    def test_a_corrupt_base_config_is_reported_rather_than_thrown_raw(self):
        with self.assertRaises(InvalidConfigError) as caught:
            tunnel_config.build("{ not json", AppSettings(), "/data")
        self.assertIsInstance(caught.exception.__cause__, json.JSONDecodeError)

    # ------------------------------------------------------------- on disk

    def test_the_written_file_has_no_byte_order_mark_and_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            path = tunnel_config.write_to(Path(d) / "runtime.config", BASE_CONFIG, AppSettings(), d)
            data = path.read_bytes()
            self.assertNotEqual(b"\xef\xbb\xbf", data[:3])
            self.assertEqual(b"{"[0], data[0])
            json.loads(data.decode("utf-8"))
            self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))

    def test_a_base_config_that_has_a_byte_order_mark_is_still_accepted(self):
        config = json.loads(tunnel_config.build("\ufeff" + BASE_CONFIG, AppSettings(), "/data"))
        self.assertEqual("", config["EgressRegion"])

    def test_the_written_directory_is_created_if_it_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = tunnel_config.write_to(Path(d) / "nested" / "runtime.config", BASE_CONFIG, AppSettings(), d)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
