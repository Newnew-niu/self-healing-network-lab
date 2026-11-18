import json

from netpulse.ai_summary import build_facts, summarise, validate
from netpulse.rca import Finding, Incident

INC = Incident(
    run_id="demo",
    title="link_blackhole",
    src="host1",
    dst="host3",
    lost=80,
    outage_ms=800.0,
    outage_start="2026-11-18T11:29:26.040+00:00",
    outage_end="2026-11-18T11:29:26.850+00:00",
    checks=[],
    events=[
        {
            "ts": "2026-11-18T11:29:26.950+00:00",
            "device": "leaf1",
            "daemon": "BGP",
            "message": "%ADJCHANGE: neighbor 10.1.1.0(spine1) Down BFD down received",
        }
    ],
    bfd=True,
)
FINDING = Finding(
    "link",
    ["leaf1", "spine1"],
    "grey failure: both interfaces up, but no traffic passes",
    "BFD (sub-second failure detection)",
    ["bgp_session on leaf1 -> spine1(10.1.1.0): Active"],
)
FACTS = build_facts(INC, FINDING)

GOOD = (
    "The leaf1-spine1 link silently dropped traffic. host1 -> host3 lost 80 probes, "
    "800 ms of outage starting 11:29:26.040. BFD detected it and leaf1 withdrew routes "
    "via 10.1.1.0. Inspect the optics on that link."
)


def test_faithful_summary_passes(intent):
    assert validate(GOOD, FACTS, intent).ok


def test_invented_number_is_rejected(intent):
    v = validate(GOOD.replace("800 ms", "about 1 second (1000 ms)"), FACTS, intent)
    assert not v.ok
    assert any("1000" in p for p in v.problems)


def test_unknown_device_is_rejected(intent):
    v = validate(GOOD.replace("leaf1-spine1", "leaf1-spine3"), FACTS, intent)
    assert not v.ok
    assert any("spine3" in p for p in v.problems)


def test_real_device_not_in_incident_is_rejected(intent):
    v = validate(GOOD + " bb2 was also affected.", FACTS, intent)
    assert any("bb2" in p for p in v.problems)


def test_invented_ip_is_rejected(intent):
    v = validate(GOOD.replace("10.1.1.0", "10.9.9.9"), FACTS, intent)
    assert any("10.9.9.9" in p for p in v.problems)


def test_rejections_are_logged_and_summary_withheld(intent, tmp_path):
    log = tmp_path / "rejections.jsonl"
    text, v = summarise(intent, INC, FINDING, log, llm=lambda f: "Outage was 3 seconds on bb9.")
    assert text is None and not v.ok
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["incident"] == "demo" and rec["problems"]


def test_accepted_summary_is_returned(intent, tmp_path):
    log = tmp_path / "rejections.jsonl"
    text, v = summarise(intent, INC, FINDING, log, llm=lambda f: GOOD)
    assert text == GOOD and v.ok and not log.exists()
