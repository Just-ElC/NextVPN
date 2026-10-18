"""
Builds the JSON configuration handed to psiphon-tunnel-core.

The base config carries the opaque sponsor identity and crypto material
(PropagationChannelId, SponsorId, signature public keys, AdditionalParameters).
Those fields are passed through byte-for-byte and never interpreted here: they
are what makes this client part of the same server network as NextVPN for
Windows, so the Linux build reads the very same engine/base.config. Only the
runtime fields this client actually owns are overridden.
"""

from __future__ import annotations

import json
import os
import platform
import re
from pathlib import Path

from . import paths
from .settings import AppSettings, ClientPlatform


class InvalidConfigError(ValueError):
    """The base configuration cannot be used."""


#: Fields that make the stock client rewrite files outside its own directory,
#: or replace its own binary. They are stripped unconditionally.
STRIPPED_FIELDS = (
    "MigrateDataStoreDirectory",
    "MigrateObfuscatedServerListDownloadDirectory",
    "MigrateRemoteServerListDownloadFilename",
    "MigrateUpgradeDownloadFilename",
    "UpgradeDownloadURLs",
    "UpgradeDownloadClientVersionHeader",
    "UpgradeDownloadFilename",
)


def write(settings: AppSettings, engine: paths.EnginePaths | None = None) -> Path:
    """Writes the runtime config and returns its path."""
    engine = engine or paths.engine()
    data_root = paths.tunnel_data_dir()
    data_root.mkdir(parents=True, exist_ok=True)
    return write_to(paths.runtime_config_file(), read_base_config(engine), settings, data_root)


def write_to(path: os.PathLike | str, base_config_json: str, settings: AppSettings,
             data_root_directory: os.PathLike | str) -> Path:
    """
    Builds the config and writes it to an explicit path, as BOM-less UTF-8 and
    readable only by the user: it may carry upstream proxy credentials.
    """
    text = build(base_config_json, settings, str(data_root_directory))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The engine creates its datastore inside this directory but refuses to
    # start if the directory itself is missing.
    Path(data_root_directory).mkdir(parents=True, exist_ok=True, mode=0o700)

    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return path


def build(base_config_json: str, settings: AppSettings, data_root_directory: str) -> str:
    """
    Produces the runtime config text from a base config, without touching disk.

    Everything the client decides is applied here and nowhere else, so the rules
    about what is stripped, forced or overridden can be verified directly.
    """
    root = _parse(base_config_json)

    # --- Hard-disabled behaviour ------------------------------------
    # The stock client can download a replacement binary and swap itself out.
    # This client never does that, so the engine is told not to fetch upgrades.
    for name in STRIPPED_FIELDS:
        root.pop(name, None)
    root["EnableUpgradeDownload"] = False

    # --- Storage -----------------------------------------------------
    root["DataRootDirectory"] = data_root_directory

    # --- Exit selection ----------------------------------------------
    root["EgressRegion"] = settings.egress_region or ""

    # --- Local proxies -------------------------------------------------
    root["LocalHttpProxyPort"] = int(settings.local_http_proxy_port)
    root["LocalSocksProxyPort"] = int(settings.local_socks_proxy_port)

    # --- Transport restrictions ----------------------------------------
    if settings.limit_tunnel_protocols:
        root["LimitTunnelProtocols"] = list(settings.limit_tunnel_protocols)
    else:
        root.pop("LimitTunnelProtocols", None)

    root["UpstreamProxyUrl"] = settings.upstream_proxy_url or ""

    # Split tunnelling. The engine resolves the client's own country itself, so
    # this needs no region argument from us.
    if settings.split_tunnel_own_region:
        root["SplitTunnelOwnRegion"] = True
    else:
        root.pop("SplitTunnelOwnRegion", None)

    # "Relax timeouts" widens the engine's latency budget and removes the overall
    # establishment deadline.
    if settings.disable_timeouts:
        root["NetworkLatencyMultiplier"] = 3.0
        root["EstablishTunnelTimeoutSeconds"] = 0
    else:
        root.pop("NetworkLatencyMultiplier", None)
        root.pop("EstablishTunnelTimeoutSeconds", None)

    # --- Telemetry the UI depends on ------------------------------------
    root["EmitBytesTransferred"] = True
    root["EmitDiagnosticNotices"] = True
    root["EmitDiagnosticNetworkParameters"] = True
    root["EmitServerAlerts"] = True

    root["ClientPlatform"] = client_platform(settings.client_platform)

    return json.dumps(root, separators=(",", ":"), ensure_ascii=False)


def read_base_config(engine: paths.EnginePaths) -> str:
    try:
        return engine.base_config.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Tunnel base configuration is missing: {engine.base_config}") from None


def _parse(text: str) -> dict:
    # A config handed over as text may carry a byte order mark, and the JSON
    # reader treats it as content.
    if text.startswith("﻿"):
        text = text[1:]
    try:
        node = json.loads(text)
    except ValueError as ex:
        raise InvalidConfigError("Tunnel base configuration is not valid JSON.") from ex
    if not isinstance(node, dict):
        raise InvalidConfigError("Tunnel base configuration is not a JSON object.")
    return node


def client_platform(kind: str = ClientPlatform.WINDOWS, release: str | None = None) -> str:
    """
    <Platform>_<version>_NextVPN, the shape the Windows build sends. The server
    splits on underscores and classifies by the first part, so neither part may
    contain spaces or underscores. The version is the running kernel's.
    """
    release = platform.release() if release is None else release
    match = re.match(r"\d+(?:\.\d+)*", release or "")
    version = match.group(0) if match else "0"
    prefix = "Linux" if kind == ClientPlatform.LINUX else "Windows"
    return f"{prefix}_{version}_NextVPN"
