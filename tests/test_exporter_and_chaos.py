from netpulse.chaos import parse_ping_d
from netpulse.checks import run_checks
from netpulse.drift import detect_drift
from netpulse.exporter import metrics_from


def samples(intent, snap):
    out = {}
    for family in metrics_from(run_checks(intent, snap), detect_drift(intent, snap)):
        for s in family.samples:
            out[(s.name, tuple(sorted(s.labels.items())))] = s.value
    return out


def test_healthy_metrics(intent, healthy):
    m = samples(intent, healthy)
    key = ("bgp_session_up", (("device", "leaf1"), ("peer", "spine1"), ("peer_ip", "10.1.1.0")))
    assert m[key] == 1.0
    assert m[("health_checks_failed", ())] == 0.0
    assert m[("probe_loss_ratio", (("dst", "host3"), ("src", "host1")))] == 0.0
    assert (
        m[("isis_adjacency_up", (("device", "bb1"), ("interface", "eth2"), ("neighbor", "bb2")))]
        == 1.0
    )


def test_fault_metrics(intent, faults):
    m = samples(intent, faults)
    key = ("bgp_session_up", (("device", "spine2"), ("peer", "leaf3"), ("peer_ip", "10.1.2.5")))
    assert m[key] == 0.0
    assert m[("probe_loss_ratio", (("dst", "host3"), ("src", "host1")))] == 1.0
    assert m[("config_drift_lines", (("device", "leaf1"),))] == 1.0
    assert m[("health_checks_failed", ())] > 0


PING = """PING 192.168.13.2 (192.168.13.2) 56(84) bytes of data.
[1000.000] 64 bytes from 192.168.13.2: icmp_seq=1 ttl=61 time=0.1 ms
[1000.010] 64 bytes from 192.168.13.2: icmp_seq=2 ttl=61 time=0.1 ms
[1000.900] 64 bytes from 192.168.13.2: icmp_seq=92 ttl=61 time=0.1 ms
[1000.910] 64 bytes from 192.168.13.2: icmp_seq=93 ttl=61 time=0.1 ms

--- 192.168.13.2 ping statistics ---
93 packets transmitted, 4 received, 95.6989% packet loss, time 920ms
"""


def test_outage_is_lost_packets_times_interval():
    r = parse_ping_d(PING, 0.01)
    assert (r["sent"], r["received"], r["lost"]) == (93, 4, 89)
    assert r["outage_ms"] == 890.0
    # the gap is between seq 2 (t=1000.010) and seq 92 (t=1000.900)
    assert r["outage_start"].endswith("00:16:40.010+00:00")
    assert r["outage_end"].endswith("00:16:40.900+00:00")
