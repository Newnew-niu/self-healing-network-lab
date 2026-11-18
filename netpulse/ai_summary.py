"""Optional, responsible-AI part: an LLM writes a short incident summary from
the RCA facts, and a deterministic validator decides whether it may be used.

Rules enforced by `validate()`:
  * every number in the summary must appear in the source facts
  * every IP address must appear in the source facts
  * every device-like name (letters followed by digits, e.g. "spine1") must be a
    real device from the intent AND be mentioned in the facts
Anything else is a hallucination: the summary is rejected and the rejection is
appended to logs/ai_rejections.jsonl. The LLM never sees the network directly
and never decides anything - it only rewords facts the RCA already computed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netpulse.intent import Intent
from netpulse.rca import Finding, Incident

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = (
    "You write incident summaries for network engineers. Use only the facts in the JSON "
    "you are given. Copy numbers, times, IP addresses and device names exactly as they "
    "appear there; do not round, convert units, add totals or introduce any other number "
    "or device. Write at most 4 sentences: what failed, the impact, the root cause and the "
    "fix. Plain text, no markdown."
)

_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")
_TIME = re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b")
_DEVICE = re.compile(r"\b[a-z]+\d+\b")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


@dataclass
class Validation:
    ok: bool
    problems: list[str] = field(default_factory=list)


def build_facts(inc: Incident, finding: Finding) -> dict[str, Any]:
    """The only thing the LLM gets to see."""
    return {
        "incident": inc.run_id,
        "what_failed": finding.summary,
        "failure_mode": finding.failure_mode,
        "detected_by": finding.detected_by,
        "affected_flow": f"{inc.src} -> {inc.dst}",
        "lost_probes": inc.lost,
        "outage_ms": round(inc.outage_ms),
        "outage_start_utc": inc.outage_start[11:23],
        "outage_end_utc": inc.outage_end[11:23],
        "bfd_enabled": inc.bfd,
        "evidence": finding.evidence[:8],
        "router_events": [
            f"{e['ts'][11:23]} {e['device']}: {e['message']}" for e in inc.events[:8]
        ],
    }


def _allowed(facts: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    text = json.dumps(facts)
    ips = set(_IP.findall(text))
    no_ip = _IP.sub(" ", text)
    times = set(_TIME.findall(no_ip))
    no_time = _TIME.sub(" ", no_ip)
    numbers = {_norm(n) for n in _NUMBER.findall(_DEVICE.sub(" ", no_time))}
    # parts of times are legitimate numbers too ("at 11:29:32" -> 11, 29, 32)
    for t in times:
        numbers.update(_norm(p) for p in re.split(r"[:.]", t))
    return ips, times, numbers


def _norm(n: str) -> str:
    return str(float(n)).rstrip("0").rstrip(".")


def validate(summary: str, facts: dict[str, Any], intent: Intent) -> Validation:
    problems = []
    ips, times, numbers = _allowed(facts)
    facts_text = json.dumps(facts)

    for ip in _IP.findall(summary):
        if ip not in ips:
            problems.append(f"IP {ip} is not in the source data")
    rest = _IP.sub(" ", summary)

    for t in _TIME.findall(rest):
        if t not in times and not any(t in x or x.startswith(t) for x in times):
            problems.append(f"time {t} is not in the source data")
    rest = _TIME.sub(" ", rest)

    for name in _DEVICE.findall(rest):
        in_facts = re.search(rf"\b{re.escape(name)}\b", facts_text) is not None
        if name in intent.devices:
            if not in_facts:
                problems.append(f"device '{name}' is not part of this incident")
        elif not in_facts:  # e.g. an interface name like eth1 is fine if the facts have it
            problems.append(f"name '{name}' does not exist in the network or the facts")
    rest = _DEVICE.sub(" ", rest)

    for n in _NUMBER.findall(rest):
        if _norm(n) not in numbers:
            problems.append(f"number {n} is not in the source data")

    return Validation(not problems, problems)


def call_claude(facts: dict[str, Any]) -> str:
    """Real LLM call. Needs `pip install netpulse[ai]` and Anthropic credentials."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},  # rewording given facts needs little reasoning
        # If the model declines, the API re-runs the request on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": json.dumps(facts, indent=2)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("the model declined to summarise this incident")
    return "".join(b.text for b in response.content if b.type == "text").strip()


def summarise(
    intent: Intent,
    inc: Incident,
    finding: Finding,
    rejections_log: Path,
    llm: Callable[[dict[str, Any]], str] = call_claude,
) -> tuple[str | None, Validation]:
    """Return (summary, validation). summary is None when it was rejected."""
    facts = build_facts(inc, finding)
    text = llm(facts)
    result = validate(text, facts, intent)
    if not result.ok:
        rejections_log.parent.mkdir(parents=True, exist_ok=True)
        with rejections_log.open("a", encoding="utf-8") as f:  # append-only log
            f.write(
                json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                        "incident": inc.run_id,
                        "model": MODEL,
                        "summary": text,
                        "problems": result.problems,
                    }
                )
                + "\n"
            )
        return None, result
    return text, result
