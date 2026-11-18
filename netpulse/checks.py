"""Health checks: compare the collected state (Snapshot) with the intent.

Each check returns CheckResult records. A check never talks to the lab - it
only reads the Snapshot - so it is deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from netpulse import parsers
from netpulse.collect import (
    BFD_PEERS,
    BGP_SUMMARY,
    BGP_TABLE,
    INTERFACES,
    ISIS_NEIGHBORS,
    LDP_NEIGHBORS,
    LINK_STATS,
    OSPF_NEIGHBORS,
    Snapshot,
    probe_command,
)
from netpulse.intent import Intent

# Above this average RTT a probe is flagged. Containers on one VM are ~0.1 ms,
# so 50 ms only fires on a real problem (e.g. injected delay).
LATENCY_THRESHOLD_MS = 50.0


@dataclass(frozen=True)
class CheckResult:
    check: str
    device: str
    target: str
    ok: bool
    detail: str
    value: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def check_bgp(intent: Intent, snap: Snapshot, device: str) -> list[CheckResult]:
    results = []
    peers = parsers.bgp_summary(snap.get(device, BGP_SUMMARY))
    for n in intent.bgp_neighbors(device):
        target = f"{n.peer}({n.ip})"
        p = peers.get(n.ip)
        if p is None:
            results.append(CheckResult("bgp_session", device, target, False, "neighbor missing"))
            continue
        if p.remote_as and p.remote_as != n.remote_as:
            results.append(
                CheckResult(
                    "bgp_session",
                    device,
                    target,
                    False,
                    f"remote AS {p.remote_as}, intent says {n.remote_as}",
                )
            )
            continue
        detail = p.state
        if p.peer_state not in ("", "OK") and p.peer_state not in p.state:
            detail = f"{p.state} ({p.peer_state})"
        results.append(
            CheckResult("bgp_session", device, target, p.up, detail, float(p.prefixes_received))
        )

    if intent.bgp_neighbors(device):
        expected = intent.expected_bgp_prefixes(device)
        have = parsers.bgp_table_prefixes(snap.get(device, BGP_TABLE))
        missing = sorted(expected - have)
        detail = "all expected prefixes present" if not missing else "missing " + ", ".join(missing)
        results.append(
            CheckResult(
                "bgp_prefixes", device, f"{len(expected)} expected", not missing, detail, len(have)
            )
        )
    return results


def check_bfd(intent: Intent, snap: Snapshot, device: str) -> list[CheckResult]:
    if not intent.settings.get("bfd", True):
        return []
    peers = parsers.bfd_peers(snap.get(device, BFD_PEERS))
    expected = [(n.peer, n.ip) for n in intent.bgp_neighbors(device) if n.group != "IBGP"]
    expected += [(i.peer, str(i.peer_ip.ip)) for i in intent.isis_neighbors(device)]
    results = []
    for peer, ip in expected:
        p = peers.get(ip)
        status = p.status if p else "missing"
        results.append(CheckResult("bfd_peer", device, f"{peer}({ip})", status == "up", status))
    return results


def check_isis(intent: Intent, snap: Snapshot, device: str) -> list[CheckResult]:
    adjs = parsers.isis_adjacencies(snap.get(device, ISIS_NEIGHBORS))
    results = []
    for itf in intent.isis_neighbors(device):
        a = adjs.get(itf.name)
        ok = a is not None and a.state == "Up" and a.neighbor == itf.peer
        detail = "no adjacency" if a is None else f"{a.state} with {a.neighbor}"
        results.append(CheckResult("isis_adjacency", device, f"{itf.name}->{itf.peer}", ok, detail))
    return results


def check_ospf(intent: Intent, snap: Snapshot, device: str) -> list[CheckResult]:
    nbrs = parsers.ospf_neighbors(snap.get(device, OSPF_NEIGHBORS))
    results = []
    for iface, peer in intent.ospf_neighbors(device):
        peer_rid = intent.devices[peer].loopback
        match = [n for n in nbrs if n.interface == iface and n.router_id == peer_rid]
        state = match[0].state if match else "missing"
        results.append(
            CheckResult("ospf_neighbor", device, f"{iface}->{peer}", state == "Full", state)
        )
    return results


def check_ldp(intent: Intent, snap: Snapshot, device: str) -> list[CheckResult]:
    if not intent.settings.get("mpls_ldp") or intent.devices[device].role != "backbone":
        return []
    nbrs = parsers.ldp_neighbors(snap.get(device, LDP_NEIGHBORS))
    results = []
    for other in intent.routers():
        if other.role == "backbone" and other.name != device:
            n = nbrs.get(other.loopback or "")
            state = n.state if n else "missing"
            results.append(
                CheckResult("ldp_neighbor", device, other.name, state == "OPERATIONAL", state)
            )
    return results


def check_tunnels(intent: Intent, snap: Snapshot, device: str) -> list[CheckResult]:
    """A GRE interface is stateless: it shows UP even if the far end is gone.
    So 'tunnel up' = interface UP *and* a ping across the tunnel works."""
    stats = parsers.link_stats(snap.get(device, LINK_STATS))
    results = []
    for t, side in intent.tunnels_of(device):
        peer_ip = t.b_ip.ip if side == "a" else t.a_ip.ip
        link = stats.get(t.name)
        if_up = link is not None and "UP" in link.flags and "LOWER_UP" in link.flags
        ping = parsers.ping(snap.get(device, f"ping -c 3 -W 1 {peer_ip} || true"))
        ok = if_up and ping.received > 0
        detail = (
            "interface missing"
            if link is None
            else f"if {'UP' if if_up else 'DOWN'}, ping {ping.received}/{ping.sent}"
        )
        results.append(CheckResult("gre_tunnel", device, t.name, ok, detail))
    return results


def check_interfaces(intent: Intent, snap: Snapshot, device: str) -> list[CheckResult]:
    states = parsers.interfaces(snap.get(device, INTERFACES))
    stats = parsers.link_stats(snap.get(device, LINK_STATS))
    results = []
    for itf in intent.interfaces(device):
        s = states.get(itf.name)
        if s is None:
            results.append(CheckResult("interface_up", device, itf.name, False, "missing"))
        else:
            if not s.admin_up:
                detail = "admin down (shutdown)"
            elif not s.oper_up:
                detail = "oper down (no carrier)"
            else:
                detail = "up"
            results.append(
                CheckResult("interface_up", device, itf.name, s.admin_up and s.oper_up, detail)
            )
        st = stats.get(itf.name)
        if st is not None:
            errors = st.rx_errors + st.tx_errors
            results.append(
                CheckResult(
                    "interface_errors",
                    device,
                    itf.name,
                    errors == 0,
                    f"rx_errors={st.rx_errors} tx_errors={st.tx_errors}",
                    float(errors),
                )
            )
    return results


def check_probes(intent: Intent, snap: Snapshot) -> list[CheckResult]:
    results = []
    for p in intent.probes:
        res = parsers.ping(snap.get(p.src, probe_command(intent.host_ip(p.dst))))
        target = p.dst
        if res.sent == 0:
            results.append(
                CheckResult("reachability", p.src, target, False, "no probe output", 1.0)
            )
            continue
        results.append(
            CheckResult(
                "reachability",
                p.src,
                target,
                res.received == res.sent,
                f"{res.received}/{res.sent} replies",
                res.loss_ratio,
            )
        )
        if res.avg_ms is not None:
            results.append(
                CheckResult(
                    "latency",
                    p.src,
                    target,
                    res.avg_ms <= LATENCY_THRESHOLD_MS,
                    f"avg {res.avg_ms:.3f} ms (limit {LATENCY_THRESHOLD_MS:.0f})",
                    res.avg_ms,
                )
            )
    return results


def run_checks(intent: Intent, snap: Snapshot) -> list[CheckResult]:
    results: list[CheckResult] = []
    for device, errs in snap.errors.items():
        for cmd, msg in errs.items():
            results.append(CheckResult("collection", device, cmd, False, msg))
    for dev in intent.routers():
        for check in (
            check_interfaces,
            check_bgp,
            check_bfd,
            check_isis,
            check_ospf,
            check_ldp,
            check_tunnels,
        ):
            results.extend(check(intent, snap, dev.name))
    results.extend(check_probes(intent, snap))
    return results


def format_table(results: list[CheckResult], only_failed: bool = False) -> str:
    rows = [r for r in results if not (only_failed and r.ok)]
    lines = [f"{'STATUS':6}  {'CHECK':16}  {'DEVICE':8}  {'TARGET':22}  DETAIL"]
    for r in rows:
        status = "OK" if r.ok else "FAIL"
        lines.append(f"{status:6}  {r.check:16}  {r.device:8}  {r.target:22}  {r.detail}")
    failed = sum(not r.ok for r in results)
    lines.append(f"\n{len(results)} checks, {failed} failed")
    return "\n".join(lines)
