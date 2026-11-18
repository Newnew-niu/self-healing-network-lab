from pathlib import Path

import pytest

from netpulse.collect import Snapshot, load_snapshot
from netpulse.intent import Intent, load_intent

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def intent() -> Intent:
    return load_intent(ROOT / "intent" / "network.yml")


@pytest.fixture(scope="session")
def healthy(intent: Intent) -> Snapshot:
    """Real outputs captured from the lab with everything up."""
    return load_snapshot(intent, FIXTURES / "healthy")


@pytest.fixture(scope="session")
def faults(intent: Intent) -> Snapshot:
    """Real outputs captured with two injected faults:
    leaf1 eth1 'shutdown' and spine2 'neighbor 10.1.2.5 shutdown' (leaf3)."""
    return load_snapshot(intent, FIXTURES / "faults")
