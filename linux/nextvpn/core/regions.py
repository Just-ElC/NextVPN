"""Exit countries and the transports the engine can be limited to."""

from __future__ import annotations

import binascii
import json
import locale
import os
from dataclasses import dataclass

from .i18n import N_, _

# The engine reports egress regions as ISO-3166-1 alpha-2 codes via the
# AvailableEgressRegions notice. Unknown codes fall back to the raw code, so a
# new region never renders as blank.
_NAMES = {
    "AE": N_("United Arab Emirates"),
    "AM": N_("Armenia"), "AR": N_("Argentina"), "AT": N_("Austria"),
    "AU": N_("Australia"), "BE": N_("Belgium"), "BG": N_("Bulgaria"),
    "BR": N_("Brazil"), "BY": N_("Belarus"), "CA": N_("Canada"),
    "CH": N_("Switzerland"), "CL": N_("Chile"), "CN": N_("China"),
    "CZ": N_("Czechia"), "DE": N_("Germany"), "DK": N_("Denmark"),
    "EE": N_("Estonia"), "ES": N_("Spain"), "FI": N_("Finland"),
    "FR": N_("France"), "GB": N_("United Kingdom"), "GE": N_("Georgia"),
    "HK": N_("Hong Kong"), "HU": N_("Hungary"), "ID": N_("Indonesia"),
    "IE": N_("Ireland"), "IL": N_("Israel"), "IN": N_("India"),
    "IR": N_("Iran"), "IS": N_("Iceland"), "IT": N_("Italy"),
    "JP": N_("Japan"), "KR": N_("South Korea"), "KZ": N_("Kazakhstan"),
    "LT": N_("Lithuania"), "LV": N_("Latvia"), "MD": N_("Moldova"),
    "MX": N_("Mexico"), "MY": N_("Malaysia"), "NL": N_("Netherlands"),
    "NO": N_("Norway"), "NZ": N_("New Zealand"), "PL": N_("Poland"),
    "PT": N_("Portugal"), "RO": N_("Romania"), "RS": N_("Serbia"),
    "RU": N_("Russia"), "SE": N_("Sweden"), "SG": N_("Singapore"),
    "SK": N_("Slovakia"), "TM": N_("Turkmenistan"), "TR": N_("Turkiye"),
    "UA": N_("Ukraine"), "US": N_("United States"), "UZ": N_("Uzbekistan"),
    "ZA": N_("South Africa"),
}


@dataclass(frozen=True)
class RegionInfo:
    """A selectable exit country. The empty code is "let the engine choose"."""

    code: str
    name: str

    @property
    def is_best(self) -> bool:
        return len(self.code) == 0

    @property
    def is_country(self) -> bool:
        return len(self.code) > 0

    @property
    def display(self) -> str:
        return self.name if self.is_best else f"{self.name} ({self.code})"


class Regions:
    @staticmethod
    def name_of(code: str) -> str:
        english = _NAMES.get(code.upper())
        return _(english) if english else code.upper()

    @staticmethod
    def best() -> RegionInfo:
        return RegionInfo("", _("Best performance"))

    @staticmethod
    def describe(code: str | None) -> RegionInfo:
        if not code:
            return Regions.best()
        return RegionInfo(code.upper(), Regions.name_of(code))

    @staticmethod
    def sorted_codes(codes) -> list[str]:
        """Alphabetical by the name the user reads, in their own language."""
        unique = sorted({c.upper() for c in codes if c})

        def key(code):
            name = Regions.name_of(code)
            try:
                return (locale.strxfrm(name), code)
            except (OSError, ValueError):
                return (name.casefold(), code)

        return sorted(unique, key=key)


@dataclass(frozen=True)
class TunnelProtocol:
    """
    A transport the engine can be limited to. Ids must match the engine's
    LimitTunnelProtocols vocabulary exactly.
    """

    id: str
    name: str
    description: str


TUNNEL_PROTOCOLS: tuple[TunnelProtocol, ...] = (
    TunnelProtocol("OSSH", "OSSH",
                   N_("Obfuscated SSH. Fastest, works on most networks.")),
    TunnelProtocol("SSH", "SSH",
                   N_("Plain SSH. Lowest overhead, most easily fingerprinted.")),
    TunnelProtocol("QUIC-OSSH", "QUIC",
                   N_("UDP based. Good on lossy or mobile links.")),
    TunnelProtocol("TLS-OSSH", "TLS",
                   N_("Wrapped in TLS so it resembles ordinary HTTPS.")),
    TunnelProtocol("UNFRONTED-MEEK-HTTPS-OSSH", "Meek HTTPS",
                   N_("HTTPS-shaped transport for restrictive networks.")),
    TunnelProtocol("FRONTED-MEEK-OSSH", N_("Meek (fronted)"),
                   N_("Routes via a CDN. Slower but very hard to block.")),
    TunnelProtocol("INPROXY-WEBRTC-OSSH", N_("In-proxy WebRTC"),
                   N_("Peer-assisted WebRTC relay. Best under heavy censorship.")),
    TunnelProtocol("CONJURE-OSSH", "Conjure",
                   N_("Refraction networking via decoy hosts.")),
    TunnelProtocol("SHADOWSOCKS-OSSH", "Shadowsocks",
                   N_("Shadowsocks-shaped transport.")),
)


def embedded_regions(server_list: os.PathLike | str) -> list[str]:
    """
    The exit countries of the servers built into the app, read straight from the
    embedded server list, so the picker is full from the very first launch,
    before the engine has run once. Each line is a hex-encoded server entry:
    four space-separated legacy fields followed by a JSON object.
    """
    found: set[str] = set()
    try:
        with open(server_list, "rb") as fh:
            lines = fh.read().split(b"\n")
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(binascii.unhexlify(line).split(b" ", 4)[4])
        except (ValueError, IndexError, binascii.Error):
            continue
        region = entry.get("region") if isinstance(entry, dict) else None
        if isinstance(region, str) and len(region) == 2 and region.isalpha():
            found.add(region.upper())
    return sorted(found)
