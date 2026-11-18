"""Drift detection: does each router run the config the intent says it should?

FRR's `show running-config` prints blocks in its own order, so a plain text
diff would be noisy. Instead both configs are turned into a set of
"context path" lines, e.g.

    router bgp 65101 > address-family ipv4 unicast > maximum-paths 8

and the two sets are compared. Order no longer matters; content does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from netpulse.collect import RUNNING_CONFIG, Snapshot
from netpulse.intent import Intent
from netpulse.render import render_router

# Lines that are structure, not configuration.
_SKIP = {
    "!",
    "end",
    "exit",
    "exit-address-family",
    "Building configuration...",
    "Current configuration:",
}

# Lines FRR adds by itself (version banner, defaults it prints explicitly).
# Each entry is documented so nobody "fixes" drift by growing this list blindly.
IGNORE = [
    re.compile(r"^frr version "),  # banner: 10.6 in template vs 10.6.2_git running
    re.compile(r"use-underlays-nexthop-weight$"),  # printed by FRR 10.6 'datacenter' defaults
]


@dataclass
class DriftReport:
    device: str
    missing: list[str] = field(default_factory=list)  # intended but not running
    extra: list[str] = field(default_factory=list)  # running but not intended

    @property
    def drifted(self) -> bool:
        return bool(self.missing or self.extra)


def normalize(config: str) -> set[str]:
    stack: list[tuple[int, str]] = []
    result: set[str] = set()
    for raw in config.splitlines():
        if not raw.strip() or raw.strip() in _SKIP:
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = " ".join(raw.split())  # collapse internal whitespace
        if any(p.search(line) for p in IGNORE):
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        result.add(" > ".join([s for _, s in stack] + [line]))
        stack.append((indent, line))
    return result


def diff(device: str, intended: str, running: str) -> DriftReport:
    want, have = normalize(intended), normalize(running)
    return DriftReport(device, sorted(want - have), sorted(have - want))


def detect_drift(intent: Intent, snap: Snapshot) -> list[DriftReport]:
    reports = []
    for dev in intent.routers():
        running = snap.get(dev.name, RUNNING_CONFIG)
        if running is None:
            reports.append(DriftReport(dev.name, missing=["<running-config not collected>"]))
            continue
        reports.append(diff(dev.name, render_router(intent, dev.name), running))
    return reports


def format_drift(reports: list[DriftReport]) -> str:
    lines = []
    for r in reports:
        if not r.drifted:
            lines.append(f"{r.device}: in sync")
            continue
        lines.append(f"{r.device}: DRIFT")
        lines += [f"  - missing: {m}" for m in r.missing]
        lines += [f"  + extra:   {e}" for e in r.extra]
    drifted = sum(r.drifted for r in reports)
    lines.append(f"\n{len(reports)} routers, {drifted} drifted")
    return "\n".join(lines)
