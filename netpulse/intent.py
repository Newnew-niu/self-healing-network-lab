"""Load and validate intent/network.yml, and derive per-device facts from it.

Everything else in netpulse (config generation, health checks, drift, RCA)
asks *this* module what the network is supposed to look like.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROUTER_ROLES = {"spine", "leaf", "backbone", "pop"}
BGP_ROLES = {"spine", "leaf", "backbone"}
LINK_TYPES = {"fabric", "edge", "core", "internet", "lan"}


class IntentError(ValueError):
    """The intent file is inconsistent (duplicate IP, unknown device, ...)."""


@dataclass(frozen=True)
class Device:
    name: str
    role: str
    mgmt_ip: str
    asn: int | None = None
    loopback: str | None = None
    tunnel_endpoint: str | None = None

    @property
    def is_router(self) -> bool:
        return self.role in ROUTER_ROLES

    @property
    def isis_net(self) -> str:
        """IS-IS NET derived from the loopback, e.g. 10.255.0.1 -> 49.0001.0102.5500.0001.00.

        Each octet is zero-padded to 3 digits (010.255.000.001), the 12 digits are
        regrouped in fours (0102.5500.0001) to form the 6-byte system ID.
        49.0001 is the private area ID, .00 is the NSEL (always 00 for a router).
        """
        if self.loopback is None:
            raise IntentError(f"{self.name} has no loopback")
        digits = "".join(f"{int(o):03d}" for o in self.loopback.split("."))
        system_id = ".".join(digits[i : i + 4] for i in range(0, 12, 4))
        return f"49.0001.{system_id}.00"


@dataclass(frozen=True)
class Interface:
    """One end of a link, seen from `device`."""

    device: str
    name: str
    ip: ipaddress.IPv4Interface
    link_type: str
    peer: str
    peer_interface: str
    peer_ip: ipaddress.IPv4Interface


@dataclass(frozen=True)
class Link:
    type: str
    a: str
    a_if: str
    b: str
    b_if: str
    subnet: ipaddress.IPv4Network

    @property
    def a_ip(self) -> ipaddress.IPv4Interface:
        return _nth_address(self.subnet, 0)

    @property
    def b_ip(self) -> ipaddress.IPv4Interface:
        return _nth_address(self.subnet, 1)


@dataclass(frozen=True)
class Tunnel:
    name: str
    a: str
    b: str
    subnet: ipaddress.IPv4Network
    ospf_area: int

    @property
    def a_ip(self) -> ipaddress.IPv4Interface:
        return _nth_address(self.subnet, 0)

    @property
    def b_ip(self) -> ipaddress.IPv4Interface:
        return _nth_address(self.subnet, 1)


@dataclass(frozen=True)
class BgpNeighbor:
    ip: str
    remote_as: int
    group: str  # FABRIC, EDGE or IBGP
    peer: str  # device name of the neighbour


@dataclass(frozen=True)
class Probe:
    src: str
    dst: str


@dataclass
class Intent:
    lab_name: str
    images: dict[str, str]
    mgmt: dict[str, str]
    settings: dict[str, Any]
    devices: dict[str, Device]
    links: list[Link]
    tunnels: list[Tunnel]
    probes: list[Probe]
    remediation: dict[str, Any] = field(default_factory=dict)

    # ---- derived facts -------------------------------------------------

    def routers(self) -> list[Device]:
        return [d for d in self.devices.values() if d.is_router]

    def hosts(self) -> list[Device]:
        return [d for d in self.devices.values() if d.role == "host"]

    def container(self, device: str) -> str:
        """containerlab names containers clab-<lab>-<node>."""
        return f"clab-{self.lab_name}-{device}"

    def interfaces(self, device: str) -> list[Interface]:
        """All link interfaces of a device (not loopbacks, not tunnels)."""
        result = []
        for link in self.links:
            if link.a == device:
                result.append(
                    Interface(device, link.a_if, link.a_ip, link.type, link.b, link.b_if, link.b_ip)
                )
            elif link.b == device:
                result.append(
                    Interface(device, link.b_if, link.b_ip, link.type, link.a, link.a_if, link.a_ip)
                )
        return sorted(result, key=lambda i: _if_sort_key(i.name))

    def tunnels_of(self, device: str) -> list[tuple[Tunnel, str]]:
        """(tunnel, local side 'a' or 'b') for every tunnel this device terminates."""
        out = []
        for t in self.tunnels:
            if t.a == device:
                out.append((t, "a"))
            elif t.b == device:
                out.append((t, "b"))
        return out

    def bgp_neighbors(self, device: str) -> list[BgpNeighbor]:
        dev = self.devices[device]
        if dev.role not in BGP_ROLES:
            return []
        neighbors = []
        for itf in self.interfaces(device):
            if itf.link_type in ("fabric", "edge"):
                peer = self.devices[itf.peer]
                assert peer.asn is not None
                group = "FABRIC" if itf.link_type == "fabric" else "EDGE"
                neighbors.append(BgpNeighbor(str(itf.peer_ip.ip), peer.asn, group, peer.name))
        if dev.role == "backbone":
            for other in self.routers():
                if other.role == "backbone" and other.name != device:
                    assert other.loopback and other.asn
                    neighbors.append(BgpNeighbor(other.loopback, other.asn, "IBGP", other.name))
        return neighbors

    def originated_prefixes(self, device: str) -> list[str]:
        """Prefixes this device puts into BGP with a `network` statement."""
        dev = self.devices[device]
        if dev.role not in ("leaf", "spine"):
            return []
        prefixes = [f"{dev.loopback}/32"]
        for itf in self.interfaces(device):
            if itf.link_type == "lan":
                prefixes.append(str(itf.ip.network))
        return prefixes

    def pop_prefixes(self) -> list[str]:
        """Prefixes learned from the POP via OSPF and redistributed into BGP."""
        prefixes = []
        for dev in self.routers():
            if dev.role == "pop":
                prefixes.append(f"{dev.loopback}/32")
                for itf in self.interfaces(dev.name):
                    if itf.link_type == "lan":
                        prefixes.append(str(itf.ip.network))
        return prefixes

    def expected_bgp_prefixes(self, device: str) -> set[str]:
        """Prefixes this router should have in its BGP table.

        Everything that is originated anywhere - EXCEPT prefixes originated by
        *another* device in my own AS that I only reach over eBGP. Example: both
        spines are AS 65100, so spine2's loopback can only reach spine1 through a
        leaf, with AS_PATH "651xx 65100". spine1 sees its own AS in the path and
        drops it (eBGP loop prevention). That is RFC 7938 working as designed.
        Backbone routers share an AS too, but they talk iBGP, so they do learn
        each other's routes.
        """
        me = self.devices[device]
        ibgp_peers = {n.peer for n in self.bgp_neighbors(device) if n.group == "IBGP"}
        expected: set[str] = set(self.pop_prefixes())
        for dev in self.routers():
            if dev.name != device and dev.asn == me.asn and dev.name not in ibgp_peers:
                continue
            expected.update(self.originated_prefixes(dev.name))
        return expected

    def isis_neighbors(self, device: str) -> list[Interface]:
        if self.devices[device].role != "backbone":
            return []
        return [i for i in self.interfaces(device) if i.link_type == "core"]

    def ospf_neighbors(self, device: str) -> list[tuple[str, str]]:
        """(tunnel interface, neighbour device) pairs where OSPF should be Full."""
        out = []
        for t, side in self.tunnels_of(device):
            out.append((t.name, t.b if side == "a" else t.a))
        return out

    def owner_of_ip(self, ip: str) -> tuple[str, str] | None:
        """Which (device, interface) owns an interface IP. Used to name BGP peers in RCA."""
        for link in self.links:
            if str(link.a_ip.ip) == ip:
                return link.a, link.a_if
            if str(link.b_ip.ip) == ip:
                return link.b, link.b_if
        for dev in self.devices.values():
            if ip in (dev.loopback, dev.tunnel_endpoint):
                return dev.name, "lo"
        return None

    def link_between(self, x: str, y: str) -> Link | None:
        for link in self.links:
            if {link.a, link.b} == {x, y}:
                return link
        return None

    def host_ip(self, host: str) -> str:
        itfs = self.interfaces(host)
        if not itfs:
            raise IntentError(f"host {host} has no LAN link")
        return str(itfs[0].ip.ip)

    def host_gateway(self, host: str) -> str:
        return str(self.interfaces(host)[0].peer_ip.ip)


# ---- loading ----------------------------------------------------------


def load_intent(path: str | Path = "intent/network.yml") -> Intent:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return parse_intent(raw)


def parse_intent(raw: dict[str, Any]) -> Intent:
    devices = {
        name: Device(
            name=name,
            role=spec["role"],
            mgmt_ip=spec["mgmt_ip"],
            asn=spec.get("asn"),
            loopback=spec.get("loopback"),
            tunnel_endpoint=spec.get("tunnel_endpoint"),
        )
        for name, spec in raw["devices"].items()
    }
    links = []
    for spec in raw["links"]:
        a, a_if = spec["a"].split(":")
        b, b_if = spec["b"].split(":")
        links.append(Link(spec["type"], a, a_if, b, b_if, ipaddress.IPv4Network(spec["subnet"])))
    tunnels = [
        Tunnel(t["name"], t["a"], t["b"], ipaddress.IPv4Network(t["subnet"]), int(t["ospf_area"]))
        for t in raw.get("tunnels", [])
    ]
    probes = [Probe(p["src"], p["dst"]) for p in raw.get("probes", [])]
    intent = Intent(
        lab_name=raw["lab_name"],
        images=raw["images"],
        mgmt=raw["mgmt"],
        settings=raw.get("settings", {}),
        devices=devices,
        links=links,
        tunnels=tunnels,
        probes=probes,
        remediation=raw.get("remediation", {}),
    )
    validate(intent)
    return intent


def validate(intent: Intent) -> None:
    """Catch mistakes in the intent before they become broken configs."""
    errors: list[str] = []
    seen_ips: dict[str, str] = {}
    seen_ports: set[tuple[str, str]] = set()

    def claim_ip(ip: str, owner: str) -> None:
        if ip in seen_ips:
            errors.append(f"IP {ip} used by both {seen_ips[ip]} and {owner}")
        seen_ips[ip] = owner

    for dev in intent.devices.values():
        if dev.role not in ROUTER_ROLES | {"host"}:
            errors.append(f"{dev.name}: unknown role {dev.role}")
        if dev.role in BGP_ROLES and dev.asn is None:
            errors.append(f"{dev.name}: role {dev.role} needs an asn")
        if dev.is_router and dev.loopback is None:
            errors.append(f"{dev.name}: routers need a loopback")
        if dev.loopback:
            claim_ip(dev.loopback, f"{dev.name}:lo")
        if dev.tunnel_endpoint:
            claim_ip(dev.tunnel_endpoint, f"{dev.name}:lo(tunnel)")
        claim_ip(dev.mgmt_ip, f"{dev.name}:mgmt")

    spines = {d.asn for d in intent.devices.values() if d.role == "spine"}
    if len(spines) > 1:
        errors.append("RFC 7938 style: all spines must share one ASN")
    leaf_asns = [d.asn for d in intent.devices.values() if d.role == "leaf"]
    if len(leaf_asns) != len(set(leaf_asns)):
        errors.append("RFC 7938 style: every leaf needs its own ASN")

    for link in intent.links:
        if link.type not in LINK_TYPES:
            errors.append(f"link {link.a}-{link.b}: unknown type {link.type}")
        for node, port in ((link.a, link.a_if), (link.b, link.b_if)):
            if node not in intent.devices:
                errors.append(f"link references unknown device {node}")
            if (node, port) in seen_ports:
                errors.append(f"{node}:{port} used by two links")
            seen_ports.add((node, port))
        if link.type != "lan" and link.subnet.prefixlen not in (30, 31):
            errors.append(f"link {link.a}-{link.b}: p2p links must be /30 or /31")
        claim_ip(str(link.a_ip.ip), f"{link.a}:{link.a_if}")
        claim_ip(str(link.b_ip.ip), f"{link.b}:{link.b_if}")

    for t in intent.tunnels:
        for node in (t.a, t.b):
            dev = intent.devices.get(node)
            if dev is None or dev.tunnel_endpoint is None:
                errors.append(f"tunnel {t.name}: {node} needs a tunnel_endpoint")
        claim_ip(str(t.a_ip.ip), f"{t.a}:{t.name}")
        claim_ip(str(t.b_ip.ip), f"{t.b}:{t.name}")

    for p in intent.probes:
        for node in (p.src, p.dst):
            if intent.devices.get(node) is None or intent.devices[node].role != "host":
                errors.append(f"probe {p.src}->{p.dst}: {node} is not a host")

    if errors:
        raise IntentError("invalid intent:\n  " + "\n  ".join(errors))


def _nth_address(net: ipaddress.IPv4Network, n: int) -> ipaddress.IPv4Interface:
    """n-th usable address. For /31 both addresses are usable (RFC 3021)."""
    hosts = list(net.hosts()) if net.prefixlen < 31 else list(net)
    return ipaddress.IPv4Interface(f"{hosts[n]}/{net.prefixlen}")


def _if_sort_key(name: str) -> tuple[str, int]:
    prefix = name.rstrip("0123456789")
    num = name[len(prefix) :]
    return prefix, int(num) if num else 0
