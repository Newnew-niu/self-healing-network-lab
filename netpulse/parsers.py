"""Parse raw FRR / iproute2 / ping output into small, typed records.

Every function here is pure (text in, data out) and is unit tested against
outputs captured from the real lab in tests/fixtures/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BgpPeer:
    ip: str
    remote_as: int
    state: str  # "Established", "Active", "Idle", "Connect", ...
    peer_state: str  # FRR extra info, e.g. "OK" or "Admin" (administratively shut)
    prefixes_received: int
    hostname: str

    @property
    def up(self) -> bool:
        return self.state == "Established"


@dataclass(frozen=True)
class BfdPeer:
    peer: str
    interface: str
    status: str  # "up", "down", "init", "admin_down"


@dataclass(frozen=True)
class IsisAdjacency:
    neighbor: str  # hostname of the neighbour
    interface: str
    state: str  # "Up", "Initializing", "Down"


@dataclass(frozen=True)
class OspfNeighbor:
    router_id: str
    interface: str  # e.g. "gre1"
    state: str  # "Full", "ExStart", "Init", ...


@dataclass(frozen=True)
class LdpNeighbor:
    neighbor_id: str
    state: str  # "OPERATIONAL" when the session is up


@dataclass(frozen=True)
class InterfaceState:
    name: str
    admin_up: bool
    oper_up: bool


@dataclass(frozen=True)
class LinkStats:
    name: str
    flags: tuple[str, ...]
    rx_errors: int
    tx_errors: int
    rx_dropped: int
    tx_dropped: int


@dataclass(frozen=True)
class PingResult:
    sent: int
    received: int
    avg_ms: float | None

    @property
    def loss_ratio(self) -> float:
        return 1.0 if self.sent == 0 else (self.sent - self.received) / self.sent


def _load(raw: str | None) -> Any:
    if raw is None or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def bgp_summary(raw: str | None) -> dict[str, BgpPeer]:
    """`show bgp summary json` -> {peer_ip: BgpPeer} for IPv4 unicast."""
    data = _load(raw) or {}
    peers = data.get("ipv4Unicast", {}).get("peers", {})
    return {
        ip: BgpPeer(
            ip=ip,
            remote_as=int(p.get("remoteAs", 0)),
            state=p.get("state", "Unknown"),
            peer_state=p.get("peerState", ""),
            prefixes_received=int(p.get("pfxRcd", 0)),
            hostname=p.get("hostname", ""),
        )
        for ip, p in peers.items()
    }


def bgp_table_prefixes(raw: str | None) -> set[str]:
    """`show bgp ipv4 unicast json` -> set of prefixes that have a valid best path."""
    data = _load(raw) or {}
    prefixes = set()
    for prefix, paths in data.get("routes", {}).items():
        if any(p.get("valid") and p.get("bestpath") for p in paths):
            prefixes.add(prefix)
    return prefixes


def bfd_peers(raw: str | None) -> dict[str, BfdPeer]:
    data = _load(raw) or []
    return {
        p["peer"]: BfdPeer(p["peer"], p.get("interface", ""), p.get("status", "unknown"))
        for p in data
        if "peer" in p
    }


def isis_adjacencies(raw: str | None) -> dict[str, IsisAdjacency]:
    """`show isis neighbor json` -> {interface: IsisAdjacency}."""
    data = _load(raw) or {}
    result = {}
    for area in data.get("areas", []):
        for c in area.get("circuits", []):
            if "interface" in c:  # FRR adds an empty {"circuit":0} entry for passive lo
                result[c["interface"]] = IsisAdjacency(c.get("adj", ""), c["interface"], c["state"])
    return result


def ospf_neighbors(raw: str | None) -> list[OspfNeighbor]:
    data = _load(raw) or {}
    result = []
    for router_id, entries in data.get("neighbors", {}).items():
        for e in entries:
            # ifaceName looks like "gre1:172.16.0.2"; state like "Full/-"
            iface = e.get("ifaceName", "").split(":")[0]
            state = e.get("converged") or e.get("nbrState", "").split("/")[0]
            result.append(OspfNeighbor(router_id, iface, state))
    return result


def ldp_neighbors(raw: str | None) -> dict[str, LdpNeighbor]:
    data = _load(raw) or {}
    return {
        n["neighborId"]: LdpNeighbor(n["neighborId"], n.get("state", ""))
        for n in data.get("neighbors", [])
    }


def interfaces(raw: str | None) -> dict[str, InterfaceState]:
    """`show interface json` -> {name: InterfaceState}."""
    data = _load(raw) or {}
    return {
        name: InterfaceState(
            name,
            admin_up=d.get("administrativeStatus") == "up",
            oper_up=d.get("operationalStatus") == "up",
        )
        for name, d in data.items()
    }


def link_stats(raw: str | None) -> dict[str, LinkStats]:
    """`ip -j -s link show` -> {name: LinkStats} (kernel counters)."""
    data = _load(raw) or []
    result = {}
    for d in data:
        stats = d.get("stats64", {})
        rx, tx = stats.get("rx", {}), stats.get("tx", {})
        result[d["ifname"]] = LinkStats(
            d["ifname"],
            tuple(d.get("flags", [])),
            int(rx.get("errors", 0)),
            int(tx.get("errors", 0)),
            int(rx.get("dropped", 0)),
            int(tx.get("dropped", 0)),
        )
    return result


_PING_COUNTS = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")
_PING_RTT = re.compile(r"= [\d.]+/([\d.]+)/[\d.]+")


def ping(raw: str | None) -> PingResult:
    """Works for both iputils ping (hosts) and busybox ping (FRR containers)."""
    if not raw:
        return PingResult(0, 0, None)
    counts = _PING_COUNTS.search(raw)
    if not counts:
        return PingResult(0, 0, None)
    rtt = _PING_RTT.search(raw)
    return PingResult(
        int(counts.group(1)), int(counts.group(2)), float(rtt.group(1)) if rtt else None
    )
