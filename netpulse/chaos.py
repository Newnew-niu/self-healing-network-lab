"""Chaos tests: break something, measure how long traffic is lost.

Measurement: a test host pings another host every 10 ms (`ping -D -i 0.01`).
We inject a fault a few seconds in. Every lost reply is 10 ms of outage, so
    outage_ms = lost_packets x 10 ms
The longest run of missing sequence numbers also gives the exact outage
window (start/end timestamps) that the RCA report lines up with router logs.

Faults (the fault stays in place while we measure - we measure how fast the
network routes AROUND it, not how fast someone repairs it):
  link_down          ip link set down on leaf1's uplink -> both ends lose carrier
                     instantly; BFD should make no difference here
  link_blackhole     tc netem loss 100% on both ends of a leaf-spine link: the
                     link stays "up" but drops everything (a grey failure, e.g. a
                     bad optic or a broken middle box). Only timers can detect it
  node_blackhole     the same on every interface of the spine in the path
  core_blackhole     the same on the backbone link in the path to the POP
                     (IS-IS has to notice; without BFD that is the IS-IS hold time)
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from netpulse.checks import run_checks
from netpulse.collect import collect
from netpulse.intent import Intent
from netpulse.runner import DockerRunner, RunnerError

SCENARIOS = ("link_down", "link_blackhole", "node_blackhole", "core_blackhole")
PING_INTERVAL_S = 0.01
PRE_FAULT_S = 3.0


@dataclass
class Fault:
    scenario: str
    description: str
    apply: list[tuple[str, str]]  # (device, shell command)
    restore: list[tuple[str, str]]
    ground_truth: dict  # what really broke - used only to SCORE the RCA, never by it
    src: str
    dst: str
    ping_seconds: float


@dataclass
class RunResult:
    run_id: str
    scenario: str
    bfd: bool
    target: str
    src: str
    dst: str
    sent: int
    received: int
    lost: int
    outage_ms: float
    outage_start: str
    outage_end: str
    fault_at: str
    extra: dict = field(default_factory=dict)


# ---- helpers -------------------------------------------------------------


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds")


def first_hops(runner: DockerRunner, src: str, dst_ip: str) -> list[str]:
    """ICMP traceroute (same 5-tuple hash as ping) -> list of hop IPs."""
    out = runner.shell(src, f"traceroute -I -n -q 1 -w 1 -m 8 {dst_ip}")
    hops = []
    for line in out.splitlines()[1:]:
        m = re.match(r"\s*\d+\s+(\d+\.\d+\.\d+\.\d+)", line)
        hops.append(m.group(1) if m else "*")
    return hops


def _owner(intent: Intent, ip: str) -> str:
    owner = intent.owner_of_ip(ip)
    if owner is None:
        raise RuntimeError(f"traceroute hop {ip} is not in the intent")
    return owner[0]


def _blackhole(device: str, itf: str) -> tuple[tuple[str, str], tuple[str, str]]:
    return (
        (device, f"tc qdisc add dev {itf} root netem loss 100%"),
        (device, f"tc qdisc del dev {itf} root"),
    )


def build_fault(intent: Intent, runner: DockerRunner, scenario: str) -> Fault:
    if scenario == "core_blackhole":
        src, dst = "host1", "hostpop"
    else:
        src, dst = "host1", "host3"
    hops = first_hops(runner, src, intent.host_ip(dst))
    # hop 1 = leaf1, hop 2 = the spine the flow hashed onto
    spine = _owner(intent, hops[1])
    link = intent.link_between("leaf1", spine)
    assert link is not None
    leaf_if = link.a_if if link.a == "leaf1" else link.b_if
    spine_if = link.a_if if link.a == spine else link.b_if

    if scenario == "link_down":
        return Fault(
            scenario,
            f"leaf1:{leaf_if} set down (carrier loss on leaf1-{spine})",
            [("leaf1", f"ip link set {leaf_if} down")],
            [("leaf1", f"ip link set {leaf_if} up")],
            {"kind": "link", "devices": sorted(["leaf1", spine])},
            src,
            dst,
            15.0,
        )
    if scenario == "link_blackhole":
        a1, r1 = _blackhole("leaf1", leaf_if)
        a2, r2 = _blackhole(spine, spine_if)
        return Fault(
            scenario,
            f"leaf1-{spine} link drops 100% (both directions), carrier stays up",
            [a1, a2],
            [r1, r2],
            {"kind": "link", "devices": sorted(["leaf1", spine])},
            src,
            dst,
            20.0,
        )
    if scenario == "node_blackhole":
        applies, restores = [], []
        for itf in intent.interfaces(spine):
            a, r = _blackhole(spine, itf.name)
            applies.append(a)
            restores.append(r)
        return Fault(
            scenario,
            f"{spine} drops 100% on every interface (node grey failure)",
            applies,
            restores,
            {"kind": "node", "devices": [spine]},
            src,
            dst,
            20.0,
        )
    if scenario == "core_blackhole":
        # hop 3 = the backbone router behind the spine, hop 4 = bb3's interface
        bb_in = _owner(intent, hops[2])
        bb_out = _owner(intent, hops[3])
        core = intent.link_between(bb_in, bb_out)
        if core is None or core.type != "core":
            raise RuntimeError(f"no core link {bb_in}-{bb_out} in path {hops}")
        a1, r1 = _blackhole(core.a, core.a_if)
        a2, r2 = _blackhole(core.b, core.b_if)
        return Fault(
            scenario,
            f"backbone link {core.a}-{core.b} drops 100%, carrier stays up",
            [a1, a2],
            [r1, r2],
            {"kind": "link", "devices": sorted([core.a, core.b])},
            src,
            dst,
            45.0,  # without BFD, IS-IS hold time is 30 s (hello 3 s x multiplier 10)
        )
    raise ValueError(f"unknown scenario {scenario}")


def set_bfd(intent: Intent, runner: DockerRunner, enabled: bool) -> None:
    """Turn BFD on/off on every eBGP peer-group and IS-IS interface at runtime."""
    no = "" if enabled else "no "
    for dev in intent.routers():
        groups = sorted({n.group for n in intent.bgp_neighbors(dev.name)} - {"IBGP"})
        if groups:
            runner.vtysh_config(
                dev.name, [f"router bgp {dev.asn}"] + [f"{no}neighbor {g} bfd" for g in groups]
            )
        for itf in intent.isis_neighbors(dev.name):
            runner.vtysh_config(dev.name, [f"interface {itf.name}", f"{no}isis bfd"])


def wait_healthy(
    intent: Intent, runner: DockerRunner, bfd: bool = True, timeout: float = 120.0
) -> bool:
    """Poll the health checks until everything passes. With BFD deliberately
    turned off for a test, missing BFD sessions are expected, not a failure."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        results = run_checks(intent, collect(intent, runner))
        bad = [r for r in results if not r.ok and (bfd or r.check != "bfd_peer")]
        if not bad:
            return True
        time.sleep(2)
    return False


_PING_LINE = re.compile(r"^\[(\d+\.\d+)\] \d+ bytes from .*icmp_seq=(\d+)")


def parse_ping_d(output: str, interval: float) -> dict:
    """Parse `ping -D` output: find lost seqs and the longest gap."""
    replies: dict[int, float] = {}
    sent = 0
    for line in output.splitlines():
        m = _PING_LINE.match(line)
        if m:
            replies[int(m.group(2))] = float(m.group(1))
        s = re.search(r"(\d+) packets transmitted", line)
        if s:
            sent = int(s.group(1))
    received = len(replies)
    lost = max(0, sent - received)
    start = end = None
    if replies and lost:
        seqs = sorted(replies)
        best = (0, None, None)
        for a, b in zip(seqs, seqs[1:], strict=False):
            if b - a - 1 > best[0]:
                best = (b - a - 1, replies[a], replies[b])
        _, start, end = best
    return {
        "sent": sent,
        "received": received,
        "lost": lost,
        "outage_ms": round(lost * interval * 1000, 1),
        "outage_start": _iso(start) if start else "",
        "outage_end": _iso(end) if end else "",
    }


def frr_log_window(intent: Intent, runner: DockerRunner, since: float, until: float) -> list[dict]:
    """Router log lines between two unix times, from every router's /tmp/frr.log."""
    events = []
    for dev in intent.routers():
        try:
            text = runner.shell(dev.name, "cat /tmp/frr.log")
        except RunnerError:
            continue
        for line in text.splitlines():
            m = re.match(r"^(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\.\d{3}) (\w+): \[[^\]]+\] (.*)$", line)
            if not m:
                continue
            ts = datetime.strptime(m.group(1), "%Y/%m/%d %H:%M:%S.%f").replace(tzinfo=UTC)
            if since <= ts.timestamp() <= until:
                events.append(
                    {
                        "ts": ts.isoformat(timespec="milliseconds"),
                        "device": dev.name,
                        "daemon": m.group(2),
                        "message": m.group(3),
                    }
                )
    return sorted(events, key=lambda e: e["ts"])


# ---- one run -------------------------------------------------------------


def run_once(
    intent: Intent, runner: DockerRunner, scenario: str, bfd: bool, out_dir: Path
) -> RunResult:
    fault = build_fault(intent, runner, scenario)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{scenario}-{'bfd' if bfd else 'nobfd'}"
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    count = int(fault.ping_seconds / PING_INTERVAL_S)
    dst_ip = intent.host_ip(fault.dst)
    ping = subprocess.Popen(
        [
            "docker",
            "exec",
            intent.container(fault.src),
            "ping",
            "-D",
            "-i",
            str(PING_INTERVAL_S),
            "-c",
            str(count),
            "-W",
            "1",
            dst_ip,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    started = time.time()
    time.sleep(PRE_FAULT_S)
    fault_at = time.time()
    for device, cmd in fault.apply:
        runner.shell(device, cmd)
    output, _ = ping.communicate(timeout=fault.ping_seconds + 30)

    # While the fault is STILL present: what do the health checks say?
    during = run_checks(intent, collect(intent, runner))
    ended = time.time()
    for device, cmd in fault.restore:
        runner.shell(device, cmd)

    stats = parse_ping_d(output, PING_INTERVAL_S)
    result = RunResult(
        run_id=run_id,
        scenario=scenario,
        bfd=bfd,
        target=fault.description,
        src=fault.src,
        dst=fault.dst,
        fault_at=_iso(fault_at),
        **stats,
    )
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                **asdict(result),
                "ground_truth": fault.ground_truth,
                "ping_started": _iso(started),
                "checks_during_fault": [r.to_dict() for r in during],
                "router_events": frr_log_window(intent, runner, fault_at - 1, ended),
            },
            indent=2,
        )
    )
    (run_dir / "ping.txt").write_text(output)
    return result


# ---- suite ---------------------------------------------------------------

CSV_FIELDS = [
    "run_id",
    "scenario",
    "bfd",
    "target",
    "src",
    "dst",
    "sent",
    "received",
    "lost",
    "outage_ms",
    "outage_start",
    "outage_end",
    "fault_at",
]


def run_suite(
    intent: Intent,
    scenarios: list[str],
    repeats: int,
    out_dir: Path,
    modes: tuple[bool, ...] = (True, False),
) -> list[RunResult]:
    runner = DockerRunner(intent.lab_name, timeout=60)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "convergence.csv"
    new_file = not csv_path.exists()
    results: list[RunResult] = []
    try:
        with csv_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            for bfd in modes:
                set_bfd(intent, runner, bfd)
                time.sleep(5)
                if not wait_healthy(intent, runner, bfd):
                    raise RuntimeError("lab not healthy before starting; aborting")
                for scenario in scenarios:
                    for i in range(repeats):
                        r = run_once(intent, runner, scenario, bfd, out_dir / "runs")
                        writer.writerow(asdict(r))
                        f.flush()
                        results.append(r)
                        print(
                            f"[{scenario} bfd={bfd} #{i + 1}] lost={r.lost} "
                            f"outage={r.outage_ms:.0f} ms  ({r.target})",
                            flush=True,
                        )
                        if not wait_healthy(intent, runner, bfd):
                            raise RuntimeError("lab did not recover after restore; aborting")
                        time.sleep(3)
    finally:
        # Whatever happens, leave the network as the intent says (BFD on).
        set_bfd(intent, runner, bool(intent.settings.get("bfd", True)))
    return results


def summarize(csv_path: Path) -> list[dict]:
    rows = list(csv.DictReader(csv_path.open()))
    groups: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        groups.setdefault((r["scenario"], r["bfd"]), []).append(float(r["outage_ms"]))
    summary = []
    for (scenario, bfd), vals in sorted(groups.items()):
        summary.append(
            {
                "scenario": scenario,
                "bfd": bfd,
                "runs": len(vals),
                "median_ms": round(statistics.median(vals), 1),
                "mean_ms": round(statistics.mean(vals), 1),
                "min_ms": round(min(vals), 1),
                "max_ms": round(max(vals), 1),
            }
        )
    return summary


def summary_markdown(summary: list[dict]) -> str:
    lines = [
        "| Scenario | BFD | Runs | Median outage (ms) | Min | Max |",
        "|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['scenario']} | {'on' if s['bfd'] == 'True' else 'off'} | {s['runs']} | "
            f"{s['median_ms']:.0f} | {s['min_ms']:.0f} | {s['max_ms']:.0f} |"
        )
    return "\n".join(lines)


# ---- auto-remediation trials --------------------------------------------

REMEDIATION_FAULTS = {
    # name: (device, vtysh config lines that break it)
    "interface_shutdown": ("leaf1", ["interface eth1", "shutdown"]),
    "bgp_neighbor_shutdown": ("spine2", ["router bgp 65100", "neighbor 10.1.2.5 shutdown"]),
}


def run_remediation_trials(intent: Intent, repeats: int, out_dir: Path) -> list[dict]:
    """Inject a config fault, let the netpulse loop (check -> plan -> guarded apply)
    fix it, and time detection and full recovery. Writes remediation.csv."""
    from netpulse.audit import AuditLog
    from netpulse.remediate import execute, plan

    runner = DockerRunner(intent.lab_name, timeout=60)
    audit = AuditLog(intent.remediation.get("audit_log", "logs/audit.jsonl"))
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (device, lines) in REMEDIATION_FAULTS.items():
        for i in range(repeats):
            if not wait_healthy(intent, runner):
                raise RuntimeError("lab not healthy before remediation trial")
            t0 = time.monotonic()
            runner.vtysh_config(device, lines)
            detected = repaired = None
            actions = 0
            while time.monotonic() - t0 < 120:
                snap = collect(intent, runner)
                results = run_checks(intent, snap)
                bad = [r for r in results if not r.ok]
                if not bad:
                    if detected is not None:
                        repaired = time.monotonic() - t0
                        break
                    continue  # fault not visible yet
                if detected is None:
                    detected = time.monotonic() - t0
                the_plan = plan(intent, results, snap)
                if the_plan.actions:
                    outcomes = execute(intent, the_plan, runner, audit, apply=True)
                    actions += sum(o.status == "executed" for o in outcomes)
                time.sleep(1)
            row = {
                "fault": name,
                "run": i + 1,
                "detect_s": round(detected or -1, 2),
                "recovered_s": round(repaired or -1, 2),
                "actions_executed": actions,
            }
            rows.append(row)
            print(row, flush=True)
            time.sleep(3)
    path = out_dir / "remediation.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows
