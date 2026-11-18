"""Root-cause analysis for one incident, written as a Markdown report.

Input is the evidence a real NOC would have:
  * probe data (when traffic stopped / resumed, how many packets were lost)
  * health checks taken while the fault was still present
  * router log lines (BGP/IS-IS adjacency changes and their reasons)

The inference uses ONLY that evidence. The chaos test also records what it
really broke ("ground_truth"); that is used afterwards to SCORE the RCA,
never to produce it.

Reasoning, in plain words:
  1. Turn every failing adjacency (BGP, BFD, IS-IS, OSPF, LDP) and every down
     interface into a device PAIR, i.e. a link, using the intent.
  2. If several broken links share one device and that device lost ALL its
     adjacencies -> that device failed (node failure).
  3. Otherwise, if exactly one link is broken -> that link failed. If an
     interface on it is down it was a hard failure (carrier/admin); if both
     interfaces are up but nothing passes, it was a grey (silent) failure.
  4. The log reason tells us what DETECTED it: "BFD down received" vs
     "Hold Timer Expired" vs an IS-IS hold-time expiry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from netpulse.intent import Intent

ADJ_CHECKS = {"bgp_session", "bfd_peer", "isis_adjacency", "ospf_neighbor", "ldp_neighbor"}


@dataclass
class Finding:
    kind: str  # "node", "link" or "unknown"
    devices: list[str]
    failure_mode: str  # "grey failure (link up, no traffic)", "interface down", ...
    detected_by: str
    evidence: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.kind == "node":
            return f"node failure of {self.devices[0]}"
        if self.kind == "link":
            return f"link failure {self.devices[0]}-{self.devices[1]}"
        return "root cause not determined"


@dataclass
class Incident:
    run_id: str
    title: str
    src: str
    dst: str
    lost: int
    outage_ms: float
    outage_start: str
    outage_end: str
    checks: list[dict]
    events: list[dict]
    bfd: bool | None = None
    ground_truth: dict | None = None

    @classmethod
    def from_run(cls, path: Path) -> Incident:
        d = json.loads(Path(path).read_text())
        return cls(
            run_id=d["run_id"],
            title=d["scenario"],
            src=d["src"],
            dst=d["dst"],
            lost=int(d["lost"]),
            outage_ms=float(d["outage_ms"]),
            outage_start=d["outage_start"],
            outage_end=d["outage_end"],
            checks=d["checks_during_fault"],
            events=d["router_events"],
            bfd=d.get("bfd"),
            ground_truth=d.get("ground_truth"),
        )


def _peer_of(intent: Intent, check: dict) -> str | None:
    """Which device is on the other side of a failed check."""
    target = check["target"]
    if check["check"] in ("bgp_session", "bfd_peer"):
        return target.split("(")[0]
    if check["check"] in ("isis_adjacency", "ospf_neighbor"):
        return target.split("->")[-1]
    if check["check"] == "ldp_neighbor":
        return target
    if check["check"] == "interface_up":
        for itf in intent.interfaces(check["device"]):
            if itf.name == target:
                return itf.peer
    return None


def broken_pairs(intent: Intent, checks: list[dict]) -> dict[frozenset[str], list[str]]:
    """{frozenset({a, b}): [evidence lines]} for every failing adjacency/interface."""
    pairs: dict[frozenset[str], list[str]] = {}
    for c in checks:
        if c["ok"] or (c["check"] not in ADJ_CHECKS and c["check"] != "interface_up"):
            continue
        if c["check"] == "bfd_peer" and c["detail"] == "missing":
            # No BFD session configured (e.g. BFD deliberately off) is not a broken link.
            continue
        peer = _peer_of(intent, c)
        if peer is None:
            continue
        pair = frozenset({c["device"], peer})
        pairs.setdefault(pair, []).append(
            f"{c['check']} on {c['device']} -> {c['target']}: {c['detail']}"
        )
    return pairs


def _adjacent_devices(intent: Intent, device: str) -> set[str]:
    """Devices this one is supposed to have a protocol adjacency with."""
    peers = {n.peer for n in intent.bgp_neighbors(device)}
    peers |= {i.peer for i in intent.isis_neighbors(device)}
    peers |= {p for _, p in intent.ospf_neighbors(device)}
    return peers


def _detected_by(events: list[dict]) -> str:
    text = " ".join(e["message"] for e in events)
    # FRR 10.6 logs "Down BFD down initiated" and "(Cease/BFD Down)"
    if re.search(r"BFD down", text, re.IGNORECASE):
        return "BFD (sub-second failure detection)"
    if "Hold Timer Expired" in text:
        return "BGP hold timer expiry (no BFD)"
    if re.search(r"Adjacency .* changed from Up to (Down|Initializing)", text):
        return "IS-IS adjacency loss"
    if "Interface down" in text or "interface down" in text:
        return "interface down event"
    return "health checks (no protocol event in logs)"


def analyse(intent: Intent, inc: Incident) -> Finding:
    pairs = broken_pairs(intent, inc.checks)
    if_down = [c for c in inc.checks if c["check"] == "interface_up" and not c["ok"]]
    detected_by = _detected_by(inc.events)

    if not pairs:
        return Finding("unknown", [], "no failing adjacency", detected_by)

    # Node failure: one device is in every broken pair and lost all its adjacencies.
    devices_in_all = set.intersection(*(set(p) for p in pairs))
    for dev in sorted(devices_in_all):
        others = {d for p in pairs for d in p if d != dev}
        expected = _adjacent_devices(intent, dev)
        if len(pairs) >= 2 and expected and expected <= others:
            evidence = [line for lines in pairs.values() for line in lines]
            return Finding(
                "node",
                [dev],
                "all adjacencies of the device lost at once",
                detected_by,
                evidence,
            )

    if len(pairs) == 1:
        ((pair, evidence),) = pairs.items()
        a, b = sorted(pair)
        on_link = [c for c in if_down if {c["device"], _peer_of(intent, c)} == {a, b}]
        if on_link:
            mode = (
                "interface down ("
                + ", ".join(f"{c['device']}:{c['target']} {c['detail']}" for c in on_link)
                + ")"
            )
        else:
            mode = "grey failure: both interfaces up, but no traffic passes"
        return Finding("link", [a, b], mode, detected_by, evidence)

    evidence = [line for lines in pairs.values() for line in lines]
    return Finding(
        "unknown",
        sorted({d for p in pairs for d in p}),
        f"{len(pairs)} unrelated links broken",
        detected_by,
        evidence,
    )


def score(finding: Finding, ground_truth: dict | None) -> bool | None:
    if not ground_truth:
        return None
    return finding.kind == ground_truth["kind"] and sorted(finding.devices) == sorted(
        ground_truth["devices"]
    )


def _fix(finding: Finding, inc: Incident) -> list[str]:
    if finding.kind == "node":
        return [
            f"Traffic already moved to the remaining spine(s) by ECMP; drain "
            f"{finding.devices[0]} (keep its BGP sessions shut) until it is repaired.",
            f"Investigate {finding.devices[0]} hardware/software (it stopped forwarding "
            "and stopped answering BFD/BGP on every port).",
        ]
    if finding.kind == "link":
        a, b = finding.devices
        steps = []
        if "grey" in finding.failure_mode:
            steps.append(
                f"Link {a}-{b} shows UP but drops traffic: check optics / cabling / "
                "any middle box; keep the link out of service until counters are clean."
            )
        else:
            steps.append(
                f"Bring the interface on {a}-{b} back up (if it was an unintended shutdown, "
                "netpulse remediate can do this under its guard rails)."
            )
        steps.append("Traffic was rerouted automatically; no customer action needed.")
        return steps
    return ["Escalate to an engineer: the evidence does not point to a single component."]


def _fmt_time(iso: str) -> str:
    return iso[11:23] if iso else "?"


def render_report(intent: Intent, inc: Incident, finding: Finding) -> str:
    correct = score(finding, inc.ground_truth)
    failed = [c for c in inc.checks if not c["ok"]]
    lines = [
        f"# Incident report: {inc.run_id}",
        "",
        "## Summary",
        f"- **What failed:** {finding.summary} ({finding.failure_mode})",
        f"- **Impact:** {inc.src} -> {inc.dst} lost {inc.lost} probes "
        f"= **{inc.outage_ms:.0f} ms** of outage "
        f"({_fmt_time(inc.outage_start)} -> {_fmt_time(inc.outage_end)} UTC); "
        "traffic then recovered on a redundant path.",
        f"- **Detected by:** {finding.detected_by}",
        f"- **BFD:** {'on' if inc.bfd else 'off' if inc.bfd is not None else 'unknown'}",
        "",
        "## Timeline (UTC)",
        "| Time | Source | Event |",
        "|---|---|---|",
    ]
    timeline = [
        (inc.outage_start, f"probe {inc.src}", "last reply before the outage"),
        (inc.outage_end, f"probe {inc.src}", "**first reply after the outage (recovered)**"),
    ]
    for e in inc.events:
        if re.search(r"ADJCHANGE|NOTIFICATION|Adjacency|BFD", e["message"]):
            timeline.append((e["ts"], e["device"], e["message"].replace("|", "/").strip()))
    for ts, source, msg in sorted(timeline, key=lambda t: t[0]):
        lines.append(f"| {_fmt_time(ts)} | {source} | {msg} |")
    lines += [
        "",
        "## Root cause",
        f"**{finding.summary}** - {finding.failure_mode}.",
        "",
        "Evidence (health checks while the fault was present):",
    ]
    lines += [f"- {ev}" for ev in finding.evidence] or ["- none"]
    lines += [
        "",
        "## Fix / follow-up",
    ]
    lines += [f"- {s}" for s in _fix(finding, inc)]
    lines += [
        "",
        "## Data",
        f"- Failed checks during fault: {len(failed)} of {len(inc.checks)}",
        f"- Router log events in window: {len(inc.events)}",
    ]
    if correct is not None:
        gt = inc.ground_truth or {}
        lines.append(
            f"- RCA self-check against the injected fault ({gt.get('kind')} "
            f"{'-'.join(gt.get('devices', []))}): **{'correct' if correct else 'WRONG'}**"
        )
    return "\n".join(lines) + "\n"


def report_all(intent: Intent, runs_dir: Path, out_dir: Path) -> list[dict]:
    """Write one report per chaos run, plus an index. Returns per-run scores."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for run_json in sorted(runs_dir.glob("*/run.json")):
        inc = Incident.from_run(run_json)
        finding = analyse(intent, inc)
        (out_dir / f"{inc.run_id}.md").write_text(render_report(intent, inc, finding))
        rows.append(
            {
                "run_id": inc.run_id,
                "scenario": inc.title,
                "bfd": inc.bfd,
                "inferred": finding.summary,
                "detected_by": finding.detected_by,
                "truth": f"{inc.ground_truth['kind']} {'-'.join(inc.ground_truth['devices'])}"
                if inc.ground_truth
                else "",
                "correct": score(finding, inc.ground_truth),
            }
        )
    scored = [r for r in rows if r["correct"] is not None]
    n_ok = sum(bool(r["correct"]) for r in scored)
    index = [
        "# Incident reports",
        "",
        f"RCA correct on **{n_ok} of {len(scored)}** incidents "
        "(scored against the fault the chaos test really injected).",
        "",
        "| Run | Inferred root cause | Detected by | Correct |",
        "|---|---|---|---|",
    ]
    for r in rows:
        index.append(
            f"| [{r['run_id']}]({r['run_id']}.md) | {r['inferred']} | {r['detected_by']} | "
            f"{'yes' if r['correct'] else 'no'} |"
        )
    (out_dir / "index.md").write_text("\n".join(index) + "\n")
    return rows
