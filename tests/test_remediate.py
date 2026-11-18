import dataclasses
import json

from netpulse.audit import AuditLog
from netpulse.checks import run_checks
from netpulse.remediate import execute, plan


def make_plan(intent, faults):
    return plan(intent, run_checks(intent, faults), faults)


def test_plan_fixes_root_causes_only(intent, faults):
    p = make_plan(intent, faults)
    assert {(a.name, a.device, a.target) for a in p.actions} == {
        ("interface_no_shutdown", "leaf1", "eth1"),
        ("bgp_neighbor_no_shutdown", "spine2", "10.1.2.5"),
    }
    # BGP sessions that are down *because* of those faults get no action
    assert len(p.suppressed) == 3
    assert not any(a.name == "clear_bgp_session" for a in p.actions)


def test_healthy_network_needs_no_action(intent, healthy):
    p = plan(intent, run_checks(intent, healthy), healthy)
    assert p.actions == [] and p.suppressed == []


def test_dry_run_is_default_and_touches_nothing(intent, faults, tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    outcomes = execute(intent, make_plan(intent, faults), runner=None, audit=audit)
    assert {o.status for o in outcomes} == {"dry_run"}


def test_allow_list_blocks_unlisted_actions(intent, faults, tmp_path):
    strict = dataclasses.replace(
        intent, remediation={**intent.remediation, "allowed_actions": ["interface_no_shutdown"]}
    )
    outcomes = execute(strict, make_plan(intent, faults), None, AuditLog(tmp_path / "a.jsonl"))
    by_name = {o.action.name: o.status for o in outcomes}
    assert by_name == {
        "interface_no_shutdown": "dry_run",
        "bgp_neighbor_no_shutdown": "blocked_not_allowed",
    }


def test_max_actions_per_run(intent, faults, tmp_path):
    one = dataclasses.replace(intent, remediation={**intent.remediation, "max_actions_per_run": 1})
    outcomes = execute(one, make_plan(intent, faults), None, AuditLog(tmp_path / "a.jsonl"))
    assert [o.status for o in outcomes] == ["dry_run", "blocked_limit"]


def test_audit_log_is_a_hash_chain(intent, faults, tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    execute(intent, make_plan(intent, faults), None, log)
    execute(intent, make_plan(intent, faults), None, log)
    assert log.verify() == (True, "chain intact")

    # tamper with one record in the middle -> detected
    lines = log.path.read_text().splitlines()
    rec = json.loads(lines[2])
    rec["detail"] = "nothing to see here"
    lines[2] = json.dumps(rec, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n")
    ok, msg = log.verify()
    assert not ok and "line 3" in msg
