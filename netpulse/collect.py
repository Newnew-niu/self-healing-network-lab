"""State collection: run `vtysh -c "show ... json"` (and a few shell commands)
on every device and keep the raw text.

A Snapshot is just {device: {command: raw_output}}. Health checks, drift and
the exporter are pure functions of a Snapshot, which is why they can be unit
tested from saved fixtures.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from netpulse.intent import Intent
from netpulse.runner import Runner, RunnerError, fixture_name

BGP_SUMMARY = "show bgp summary json"
BGP_TABLE = "show bgp ipv4 unicast json"
BFD_PEERS = "show bfd peers json"
ISIS_NEIGHBORS = "show isis neighbor json"
OSPF_NEIGHBORS = "show ip ospf neighbor json"
LDP_NEIGHBORS = "show mpls ldp neighbor json"
INTERFACES = "show interface json"
RUNNING_CONFIG = "show running-config"
LINK_STATS = "ip -j -s link show"


def probe_command(dst_ip: str, count: int = 5) -> str:
    # `|| true`: ping exits 1 when packets are lost, which is a result, not an error.
    return f"ping -c {count} -i 0.2 -W 1 {dst_ip} || true"


@dataclass
class Snapshot:
    outputs: dict[str, dict[str, str]] = field(default_factory=dict)
    errors: dict[str, dict[str, str]] = field(default_factory=dict)

    def get(self, device: str, command: str) -> str | None:
        return self.outputs.get(device, {}).get(command)

    def json(self, device: str, command: str) -> dict | list | None:
        raw = self.get(device, command)
        if raw is None or not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None


def commands_for(intent: Intent, device: str) -> list[tuple[str, str]]:
    """[(kind, command)] where kind is 'vtysh' or 'shell'."""
    dev = intent.devices[device]
    if dev.role == "host":
        return [
            ("shell", probe_command(intent.host_ip(p.dst)))
            for p in intent.probes
            if p.src == device
        ]
    cmds = [("vtysh", INTERFACES), ("vtysh", RUNNING_CONFIG), ("shell", LINK_STATS)]
    if intent.bgp_neighbors(device):
        cmds += [("vtysh", BGP_SUMMARY), ("vtysh", BGP_TABLE)]
    if intent.settings.get("bfd", True) and (
        intent.bgp_neighbors(device) or intent.isis_neighbors(device)
    ):
        cmds.append(("vtysh", BFD_PEERS))
    if dev.role == "backbone":
        cmds.append(("vtysh", ISIS_NEIGHBORS))
        if intent.settings.get("mpls_ldp"):
            cmds.append(("vtysh", LDP_NEIGHBORS))
    if intent.tunnels_of(device):
        cmds.append(("vtysh", OSPF_NEIGHBORS))
        for t, side in intent.tunnels_of(device):
            peer_ip = t.b_ip.ip if side == "a" else t.a_ip.ip
            cmds.append(("shell", f"ping -c 3 -W 1 {peer_ip} || true"))
    return cmds


def collect(intent: Intent, runner: Runner, devices: list[str] | None = None) -> Snapshot:
    """Collect from all devices in parallel (one thread per device)."""
    names = devices or [d.name for d in intent.devices.values()]
    snap = Snapshot()

    def one(device: str) -> tuple[str, dict[str, str], dict[str, str]]:
        out: dict[str, str] = {}
        err: dict[str, str] = {}
        for kind, cmd in commands_for(intent, device):
            try:
                out[cmd] = (
                    runner.vtysh(device, cmd) if kind == "vtysh" else runner.shell(device, cmd)
                )
            except RunnerError as exc:
                err[cmd] = str(exc)
        return device, out, err

    with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
        for device, out, err in pool.map(one, names):
            snap.outputs[device] = out
            if err:
                snap.errors[device] = err
    return snap


def save_snapshot(snap: Snapshot, root: str | Path) -> None:
    root = Path(root)
    for device, outputs in snap.outputs.items():
        for cmd, text in outputs.items():
            path = root / device / fixture_name(cmd)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    if snap.errors:
        (root / "errors.json").write_text(json.dumps(snap.errors, indent=2), encoding="utf-8")


def load_snapshot(intent: Intent, root: str | Path) -> Snapshot:
    """Rebuild a Snapshot from a saved directory (the fixtures used by tests)."""
    root = Path(root)
    snap = Snapshot()
    for dev in intent.devices.values():
        for _, cmd in commands_for(intent, dev.name):
            path = root / dev.name / fixture_name(cmd)
            if path.exists():
                snap.outputs.setdefault(dev.name, {})[cmd] = path.read_text(encoding="utf-8")
    return snap
