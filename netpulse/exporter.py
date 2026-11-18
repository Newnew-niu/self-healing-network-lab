"""Prometheus exporter.

A background thread runs collect -> checks -> drift every `interval` seconds and
keeps the latest results. On every scrape, NetpulseCollector turns those
results into metrics. Building metrics from the latest results (instead of
updating long-lived Gauges) means a BGP session that disappears from the
network also disappears from /metrics instead of freezing at its last value.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from prometheus_client.registry import Collector

from netpulse.checks import CheckResult, run_checks
from netpulse.collect import collect
from netpulse.drift import DriftReport, detect_drift
from netpulse.intent import Intent
from netpulse.runner import Runner


@dataclass
class State:
    results: list[CheckResult] = field(default_factory=list)
    drift: list[DriftReport] = field(default_factory=list)
    duration_s: float = 0.0
    last_success: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


def _split_peer(target: str) -> tuple[str, str]:
    """'leaf1(10.1.1.1)' -> ('leaf1', '10.1.1.1')."""
    name, _, ip = target.partition("(")
    return name, ip.rstrip(")")


def _split_arrow(target: str) -> tuple[str, str]:
    """'eth2->bb2' -> ('eth2', 'bb2')."""
    left, _, right = target.partition("->")
    return left, right


def metrics_from(
    results: list[CheckResult], drift: list[DriftReport]
) -> Iterator[GaugeMetricFamily]:
    """Pure function: results -> metric families. Unit tested without HTTP."""
    bgp_up = GaugeMetricFamily(
        "bgp_session_up",
        "1 if the BGP session is Established",
        labels=["device", "peer", "peer_ip"],
    )
    bgp_pfx = GaugeMetricFamily(
        "bgp_prefixes_received",
        "Prefixes received on the BGP session",
        labels=["device", "peer", "peer_ip"],
    )
    bgp_table = GaugeMetricFamily(
        "bgp_table_prefixes", "Prefixes with a best path in the BGP table", labels=["device"]
    )
    isis = GaugeMetricFamily(
        "isis_adjacency_up",
        "1 if the IS-IS adjacency is Up",
        labels=["device", "interface", "neighbor"],
    )
    ospf = GaugeMetricFamily(
        "ospf_neighbor_full",
        "1 if the OSPF neighbour is Full",
        labels=["device", "interface", "neighbor"],
    )
    bfd = GaugeMetricFamily("bfd_peer_up", "1 if the BFD session is up", labels=["device", "peer"])
    ldp = GaugeMetricFamily(
        "ldp_neighbor_up", "1 if LDP is OPERATIONAL", labels=["device", "neighbor"]
    )
    gre = GaugeMetricFamily(
        "gre_tunnel_up", "1 if the tunnel is UP and passes traffic", labels=["device", "tunnel"]
    )
    if_up = GaugeMetricFamily(
        "interface_up", "1 if admin and oper up", labels=["device", "interface"]
    )
    if_err = GaugeMetricFamily(
        "interface_errors", "Kernel rx+tx error counter", labels=["device", "interface"]
    )
    latency = GaugeMetricFamily("probe_latency_ms", "Average ping RTT", labels=["src", "dst"])
    loss = GaugeMetricFamily("probe_loss_ratio", "Ping loss, 0..1", labels=["src", "dst"])
    drift_lines = GaugeMetricFamily(
        "config_drift_lines", "Lines differing from the intent", labels=["device"]
    )
    failed = GaugeMetricFamily("health_checks_failed", "Number of failed health checks")
    total = GaugeMetricFamily("health_checks_total", "Number of health checks run")

    for r in results:
        v = 1.0 if r.ok else 0.0
        if r.check == "bgp_session":
            peer, ip = _split_peer(r.target)
            bgp_up.add_metric([r.device, peer, ip], v)
            bgp_pfx.add_metric([r.device, peer, ip], r.value or 0.0)
        elif r.check == "bgp_prefixes":
            bgp_table.add_metric([r.device], r.value or 0.0)
        elif r.check == "isis_adjacency":
            itf, nbr = _split_arrow(r.target)
            isis.add_metric([r.device, itf, nbr], v)
        elif r.check == "ospf_neighbor":
            itf, nbr = _split_arrow(r.target)
            ospf.add_metric([r.device, itf, nbr], v)
        elif r.check == "bfd_peer":
            bfd.add_metric([r.device, _split_peer(r.target)[0]], v)
        elif r.check == "ldp_neighbor":
            ldp.add_metric([r.device, r.target], v)
        elif r.check == "gre_tunnel":
            gre.add_metric([r.device, r.target], v)
        elif r.check == "interface_up":
            if_up.add_metric([r.device, r.target], v)
        elif r.check == "interface_errors":
            if_err.add_metric([r.device, r.target], r.value or 0.0)
        elif r.check == "reachability":
            loss.add_metric([r.device, r.target], r.value if r.value is not None else 1.0)
        elif r.check == "latency":
            latency.add_metric([r.device, r.target], r.value or 0.0)

    for d in drift:
        drift_lines.add_metric([d.device], float(len(d.missing) + len(d.extra)))
    failed.add_metric([], float(sum(not r.ok for r in results)))
    total.add_metric([], float(len(results)))

    yield from (bgp_up, bgp_pfx, bgp_table, isis, ospf, bfd, ldp, gre, if_up, if_err)
    yield from (latency, loss, drift_lines, failed, total)


class NetpulseCollector(Collector):
    def __init__(self, state: State) -> None:
        self.state = state

    def collect(self) -> Iterator[GaugeMetricFamily]:
        with self.state.lock:
            results, drift = list(self.state.results), list(self.state.drift)
            duration, last = self.state.duration_s, self.state.last_success
        yield from metrics_from(results, drift)
        d = GaugeMetricFamily("netpulse_collection_seconds", "Duration of the last collection")
        d.add_metric([], duration)
        yield d
        ts = GaugeMetricFamily("netpulse_last_success_timestamp", "Unix time of last collection")
        ts.add_metric([], last)
        yield ts


def poll_forever(intent: Intent, runner: Runner, state: State, interval: float) -> None:
    while True:
        start = time.monotonic()
        try:
            snap = collect(intent, runner)
            results = run_checks(intent, snap)
            drift = detect_drift(intent, snap)
            with state.lock:
                state.results, state.drift = results, drift
                state.duration_s = time.monotonic() - start
                state.last_success = time.time()
        except Exception as exc:  # keep exporting the last good data; never die
            print(f"collection failed: {exc}", flush=True)
        time.sleep(max(0.0, interval - (time.monotonic() - start)))


def serve(intent: Intent, runner: Runner, port: int, interval: float) -> None:
    state = State()
    REGISTRY.register(NetpulseCollector(state))
    start_http_server(port, addr="0.0.0.0")
    print(f"exporter listening on :{port}, collecting every {interval}s", flush=True)
    poll_forever(intent, runner, state, interval)
