from netpulse.checks import run_checks


def failed(results):
    return {(r.check, r.device, r.target) for r in results if not r.ok}


def test_healthy_network_passes_every_check(intent, healthy):
    results = run_checks(intent, healthy)
    assert len(results) > 100
    assert failed(results) == set()


def test_faults_are_detected(intent, faults):
    bad = failed(run_checks(intent, faults))
    assert ("interface_up", "leaf1", "eth1") in bad
    assert ("bgp_session", "spine2", "leaf3(10.1.2.5)") in bad
    assert ("bgp_session", "leaf1", "spine1(10.1.1.0)") in bad
    assert ("bfd_peer", "leaf1", "spine1(10.1.1.0)") in bad
    # the two single faults together cut host1 off from host3
    assert ("reachability", "host1", "host3") in bad
    # ...but the POP is still reachable through the other spine
    assert ("reachability", "host1", "hostpop") not in bad


def test_admin_down_detail(intent, faults):
    r = next(
        r
        for r in run_checks(intent, faults)
        if r.check == "interface_up" and r.device == "leaf1" and r.target == "eth1"
    )
    assert r.detail.startswith("admin down")
