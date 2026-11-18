"""Guarded auto-remediation.

Flow:  checks -> plan() -> execute()

Guard rails (all enforced in execute()):
  1. dry-run is the default: nothing changes unless apply=True (--apply)
  2. allow-list: only action types listed in intent remediation.allowed_actions
  3. max actions per run: stop after N changes, a human must look at the rest
  4. append-only audit log of every planned, executed, blocked or suppressed action

plan() also avoids treating symptoms: a BGP session that is down *because* its
interface is down gets no action of its own - fixing the interface fixes it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from netpulse import parsers
from netpulse.audit import AuditLog
from netpulse.checks import CheckResult
from netpulse.collect import BGP_SUMMARY, Snapshot
from netpulse.intent import Intent
from netpulse.runner import DockerRunner, RunnerError

KNOWN_ACTIONS = {"interface_no_shutdown", "bgp_neighbor_no_shutdown", "clear_bgp_session"}


@dataclass(frozen=True)
class Action:
    name: str
    device: str
    target: str
    reason: str
    asn: int | None = None

    def describe(self) -> str:
        return f"{self.name} on {self.device} {self.target}"


@dataclass
class Plan:
    actions: list[Action]
    suppressed: list[str]  # failures we deliberately do not act on, and why


@dataclass(frozen=True)
class Outcome:
    action: Action
    status: str  # dry_run | executed | failed | blocked_not_allowed | blocked_limit
    detail: str = ""


def _failed(results: list[CheckResult], check: str) -> list[CheckResult]:
    return [r for r in results if r.check == check and not r.ok]


def plan(intent: Intent, results: list[CheckResult], snap: Snapshot) -> Plan:
    actions: list[Action] = []
    suppressed: list[str] = []

    # 1) Interfaces that are administratively down but should be up.
    admin_down: set[tuple[str, str]] = set()
    oper_down: set[tuple[str, str]] = set()
    for r in _failed(results, "interface_up"):
        if r.detail.startswith("admin down"):
            admin_down.add((r.device, r.target))
            actions.append(
                Action("interface_no_shutdown", r.device, r.target, "admin down, intent says up")
            )
        else:
            oper_down.add((r.device, r.target))

    # 2) BGP sessions that are not Established.
    admin_shut_peers: set[tuple[str, str]] = set()  # (device, peer_ip)
    for r in _failed(results, "bgp_session"):
        peer_ip = r.target.split("(")[-1].rstrip(")")
        peers = parsers.bgp_summary(snap.get(r.device, BGP_SUMMARY))
        p = peers.get(peer_ip)
        if p is not None and p.peer_state == "Admin":
            admin_shut_peers.add((r.device, peer_ip))
    for device, peer_ip in sorted(admin_shut_peers):
        actions.append(
            Action(
                "bgp_neighbor_no_shutdown",
                device,
                peer_ip,
                "neighbor administratively shut down, intent says it should be up",
                intent.devices[device].asn,
            )
        )

    for r in _failed(results, "bgp_session"):
        peer_ip = r.target.split("(")[-1].rstrip(")")
        if (r.device, peer_ip) in admin_shut_peers:
            continue
        cause = _explained_by(intent, r.device, peer_ip, admin_down, oper_down, admin_shut_peers)
        if cause:
            suppressed.append(f"{r.device} -> {r.target}: {r.detail}; symptom of {cause}")
            continue
        actions.append(
            Action(
                "clear_bgp_session",
                r.device,
                peer_ip,
                f"session {r.detail} while its link is up",
            )
        )
    return Plan(actions, suppressed)


def _explained_by(
    intent: Intent,
    device: str,
    peer_ip: str,
    admin_down: set[tuple[str, str]],
    oper_down: set[tuple[str, str]],
    admin_shut_peers: set[tuple[str, str]],
) -> str | None:
    """Return the root cause if this BGP failure is a consequence of another fault.

    An admin-down interface on either end is the most specific cause (the other
    end only sees "no carrier"), so it is checked before plain oper-down.
    """
    for itf in intent.interfaces(device):
        if str(itf.peer_ip.ip) == peer_ip:
            for node, port in ((device, itf.name), (itf.peer, itf.peer_interface)):
                if (node, port) in admin_down:
                    return f"interface {node}:{port} admin down"
            for node, port in ((device, itf.name), (itf.peer, itf.peer_interface)):
                if (node, port) in oper_down:
                    return f"interface {node}:{port} oper down"
            if (itf.peer, str(itf.ip.ip)) in admin_shut_peers:
                return f"neighbor shut down on {itf.peer}"
    return None


def _apply(runner: DockerRunner, action: Action) -> str:
    if action.name == "interface_no_shutdown":
        return runner.vtysh_config(action.device, [f"interface {action.target}", "no shutdown"])
    if action.name == "bgp_neighbor_no_shutdown":
        return runner.vtysh_config(
            action.device, [f"router bgp {action.asn}", f"no neighbor {action.target} shutdown"]
        )
    if action.name == "clear_bgp_session":
        return runner.vtysh(action.device, f"clear bgp {action.target}")
    raise ValueError(f"unknown action {action.name}")


def execute(
    intent: Intent,
    the_plan: Plan,
    runner: DockerRunner | None,
    audit: AuditLog,
    apply: bool = False,
) -> list[Outcome]:
    policy = intent.remediation
    allowed = set(policy.get("allowed_actions", [])) & KNOWN_ACTIONS
    limit = int(policy.get("max_actions_per_run", 3))

    audit.append(
        "run_started",
        mode="apply" if apply else "dry_run",
        planned=len(the_plan.actions),
        max_actions=limit,
        allowed=sorted(allowed),
    )
    for s in the_plan.suppressed:
        audit.append("suppressed", detail=s)

    outcomes: list[Outcome] = []
    used = 0
    for action in the_plan.actions:
        if action.name not in allowed:
            outcome = Outcome(action, "blocked_not_allowed", "action type not in allow-list")
        elif used >= limit:
            outcome = Outcome(action, "blocked_limit", f"max {limit} actions per run reached")
        elif not apply:
            used += 1
            outcome = Outcome(action, "dry_run", "would run; pass --apply to execute")
        else:
            used += 1
            assert runner is not None
            try:
                _apply(runner, action)
                outcome = Outcome(action, "executed")
            except RunnerError as exc:
                outcome = Outcome(action, "failed", str(exc))
        outcomes.append(outcome)
        audit.append("action", status=outcome.status, detail=outcome.detail, **asdict(action))
    audit.append(
        "run_finished",
        outcomes={o.status: sum(x.status == o.status for x in outcomes) for o in outcomes},
    )
    return outcomes


def format_outcomes(the_plan: Plan, outcomes: list[Outcome]) -> str:
    lines = []
    for s in the_plan.suppressed:
        lines.append(f"SUPPRESSED  {s}")
    for o in outcomes:
        lines.append(f"{o.status.upper():20} {o.action.describe():45} {o.action.reason}")
    if not outcomes:
        lines.append("nothing to remediate")
    return "\n".join(lines)
