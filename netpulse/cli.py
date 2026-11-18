"""Command line entry point: `netpulse <command>`."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from netpulse.audit import AuditLog
from netpulse.checks import format_table, run_checks
from netpulse.collect import Snapshot, collect, load_snapshot, save_snapshot
from netpulse.drift import detect_drift, format_drift
from netpulse.intent import Intent, load_intent
from netpulse.remediate import execute, format_outcomes, plan
from netpulse.render import render_all
from netpulse.runner import DockerRunner


def cmd_configs(args: argparse.Namespace) -> int:
    intent = load_intent(args.intent)
    for path in render_all(intent, args.root):
        print(f"wrote {path}")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    intent = load_intent(args.intent)
    snap = collect(intent, DockerRunner(intent.lab_name))
    save_snapshot(snap, args.out)
    print(f"saved snapshot of {len(snap.outputs)} devices to {args.out}")
    for device, errs in snap.errors.items():
        for cmd, msg in errs.items():
            print(f"  ERROR {device}: {cmd}: {msg}")
    return 1 if snap.errors else 0


def _snapshot(intent: Intent, source: str | None) -> Snapshot:
    """Live collection by default; --from DIR replays saved outputs."""
    if source:
        return load_snapshot(intent, source)
    return collect(intent, DockerRunner(intent.lab_name))


def cmd_check(args: argparse.Namespace) -> int:
    intent = load_intent(args.intent)
    results = run_checks(intent, _snapshot(intent, args.source))
    print(format_table(results, only_failed=args.failed))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps([r.to_dict() for r in results], indent=2))
    return 0 if all(r.ok for r in results) else 1


def cmd_drift(args: argparse.Namespace) -> int:
    intent = load_intent(args.intent)
    reports = detect_drift(intent, _snapshot(intent, args.source))
    print(format_drift(reports))
    return 1 if any(r.drifted for r in reports) else 0


def cmd_remediate(args: argparse.Namespace) -> int:
    intent = load_intent(args.intent)
    audit = AuditLog(intent.remediation.get("audit_log", "logs/audit.jsonl"))
    snap = _snapshot(intent, args.source)
    before = run_checks(intent, snap)
    the_plan = plan(intent, before, snap)
    apply = args.apply and not args.source  # never "apply" against saved fixtures
    runner = DockerRunner(intent.lab_name) if apply else None
    outcomes = execute(intent, the_plan, runner, audit, apply=apply)
    print(format_outcomes(the_plan, outcomes))
    if not apply or not any(o.status == "executed" for o in outcomes):
        return 0
    print(f"\nwaiting {args.settle}s for protocols to converge, then re-checking...")
    time.sleep(args.settle)
    after = run_checks(intent, collect(intent, DockerRunner(intent.lab_name)))
    failed_before = sum(not r.ok for r in before)
    failed_after = sum(not r.ok for r in after)
    audit.append("verification", failed_before=failed_before, failed_after=failed_after)
    print(f"failed checks: {failed_before} before -> {failed_after} after")
    return 0 if failed_after == 0 else 1


def cmd_audit_verify(args: argparse.Namespace) -> int:
    intent = load_intent(args.intent)
    ok, msg = AuditLog(intent.remediation.get("audit_log", "logs/audit.jsonl")).verify()
    print(msg)
    return 0 if ok else 1


def cmd_exporter(args: argparse.Namespace) -> int:
    from netpulse.exporter import serve  # imported lazily: only this command needs HTTP

    intent = load_intent(args.intent)
    port = args.port or int(intent.settings.get("exporter_port", 9101))
    serve(intent, DockerRunner(intent.lab_name), port, args.interval)
    return 0


def cmd_chaos(args: argparse.Namespace) -> int:
    from netpulse.chaos import run_suite, summarize, summary_markdown

    intent = load_intent(args.intent)
    modes = {"both": (True, False), "on": (True,), "off": (False,)}[args.bfd]
    out = Path(args.out)
    run_suite(intent, args.scenarios, args.repeats, out, modes)
    summary = summarize(out / "convergence.csv")
    md = summary_markdown(summary)
    (out / "summary.md").write_text(md + "\n")
    print(md)
    return 0


def cmd_remediation_trials(args: argparse.Namespace) -> int:
    from netpulse.chaos import run_remediation_trials

    intent = load_intent(args.intent)
    run_remediation_trials(intent, args.repeats, Path(args.out))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from netpulse.rca import Incident, analyse, report_all

    intent = load_intent(args.intent)
    out = Path(args.out)
    rows = report_all(intent, Path(args.runs), out)
    scored = [r for r in rows if r["correct"] is not None]
    print(
        f"wrote {len(rows)} incident reports to {out}/ "
        f"(RCA correct on {sum(bool(r['correct']) for r in scored)} of {len(scored)})"
    )
    if args.ai:
        from netpulse.ai_summary import summarise

        log = Path("logs/ai_rejections.jsonl")
        for run_json in sorted(Path(args.runs).glob("*/run.json"))[: args.ai_limit]:
            inc = Incident.from_run(run_json)
            text, v = summarise(intent, inc, analyse(intent, inc), log)
            if text:
                with (out / f"{inc.run_id}.md").open("a") as f:
                    f.write(f"\n## AI summary (validated)\n{text}\n")
                print(f"{inc.run_id}: AI summary accepted")
            else:
                print(f"{inc.run_id}: AI summary REJECTED: {v.problems}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="netpulse", description=__doc__)
    p.add_argument("--intent", default="intent/network.yml")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("configs", help="render every config from the intent")
    s.add_argument("--root", default=".")
    s.set_defaults(func=cmd_configs)

    s = sub.add_parser("collect", help="save raw show outputs from every device")
    s.add_argument("--out", default="tests/fixtures/healthy")
    s.set_defaults(func=cmd_collect)

    s = sub.add_parser("check", help="run health checks against the intent")
    s.add_argument("--from", dest="source", help="read a saved snapshot instead of the lab")
    s.add_argument("--failed", action="store_true", help="only print failed checks")
    s.add_argument("--json", help="also write results as JSON to this file")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("drift", help="compare running configs with the intent")
    s.add_argument("--from", dest="source", help="read a saved snapshot instead of the lab")
    s.set_defaults(func=cmd_drift)

    s = sub.add_parser("remediate", help="plan (and with --apply, run) guarded fixes")
    s.add_argument("--from", dest="source", help="plan from a saved snapshot (never applies)")
    s.add_argument("--apply", action="store_true", help="really change the network")
    s.add_argument("--settle", type=float, default=10.0, help="seconds to wait before verifying")
    s.set_defaults(func=cmd_remediate)

    s = sub.add_parser("exporter", help="serve Prometheus metrics")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--interval", type=float, default=5.0)
    s.set_defaults(func=cmd_exporter)

    s = sub.add_parser("chaos", help="inject faults and measure convergence")
    s.add_argument(
        "--scenarios",
        nargs="+",
        default=["link_down", "link_blackhole", "node_blackhole", "core_blackhole"],
    )
    s.add_argument("--repeats", type=int, default=5)
    s.add_argument("--bfd", choices=["both", "on", "off"], default="both")
    s.add_argument("--out", default="results/chaos")
    s.set_defaults(func=cmd_chaos)

    s = sub.add_parser("remediation-trials", help="time detect+repair of config faults")
    s.add_argument("--repeats", type=int, default=5)
    s.add_argument("--out", default="results")
    s.set_defaults(func=cmd_remediation_trials)

    s = sub.add_parser("report", help="write RCA reports for chaos runs")
    s.add_argument("--runs", default="results/chaos/runs")
    s.add_argument("--out", default="reports")
    s.add_argument("--ai", action="store_true", help="add an LLM summary (validated)")
    s.add_argument("--ai-limit", type=int, default=8)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("audit-verify", help="check the audit log hash chain")
    s.set_defaults(func=cmd_audit_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
