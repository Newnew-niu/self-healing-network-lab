"""RCA against real incidents recorded by the chaos tests (tests/fixtures/incidents)."""

import pytest

from netpulse.rca import Incident, analyse, render_report, score
from tests.conftest import FIXTURES


def load(name: str) -> Incident:
    return Incident.from_run(FIXTURES / "incidents" / f"{name}.json")


@pytest.mark.parametrize(
    "name, kind, devices, detected",
    [
        ("link_blackhole-bfd", "link", ["leaf1", "spine1"], "BFD"),
        ("node_blackhole-nobfd", "node", ["spine1"], "BGP hold timer"),
        ("core_blackhole-nobfd", "link", ["bb2", "bb3"], "BGP hold timer"),
        ("link_down-bfd", "link", ["leaf1", "spine1"], "interface down"),
    ],
)
def test_root_cause_from_real_incidents(intent, name, kind, devices, detected):
    inc = load(name)
    finding = analyse(intent, inc)
    assert finding.kind == kind
    assert finding.devices == devices
    assert detected in finding.detected_by
    assert score(finding, inc.ground_truth) is True


def test_grey_vs_hard_failure(intent):
    assert "grey" in analyse(intent, load("link_blackhole-bfd")).failure_mode
    assert "interface down" in analyse(intent, load("link_down-bfd")).failure_mode


def test_rca_ignores_missing_bfd_when_bfd_is_off(intent):
    """With BFD off every bfd_peer check says 'missing' - that is not a broken link."""
    inc = load("node_blackhole-nobfd")
    assert any(c["check"] == "bfd_peer" and not c["ok"] for c in inc.checks)
    assert analyse(intent, inc).kind == "node"


def test_report_has_required_sections(intent):
    inc = load("core_blackhole-nobfd")
    report = render_report(intent, inc, analyse(intent, inc))
    for section in ("## Summary", "## Timeline", "## Root cause", "## Fix", "**correct**"):
        assert section in report
    # timeline is sorted: recovery line comes before the later IS-IS events
    times = [line.split("|")[1].strip() for line in report.splitlines() if line.startswith("| 1")]
    assert times == sorted(times)
