from netpulse.drift import detect_drift, diff, normalize


def test_order_does_not_matter():
    a = "interface eth1\n ip address 10.0.0.0/31\nexit\n!\nrouter bgp 1\n neighbor X bfd\n"
    b = "router bgp 1\n neighbor X bfd\nexit\n!\ninterface eth1\n ip address 10.0.0.0/31\n"
    assert normalize(a) == normalize(b)


def test_context_is_kept():
    lines = normalize("router bgp 1\n address-family ipv4 unicast\n  maximum-paths 8\n")
    assert "router bgp 1 > address-family ipv4 unicast > maximum-paths 8" in lines


def test_extra_and_missing_lines():
    r = diff("x", "interface eth1\n ip address 1.1.1.1/31\n", "interface eth1\n shutdown\n")
    assert r.missing == ["interface eth1 > ip address 1.1.1.1/31"]
    assert r.extra == ["interface eth1 > shutdown"]


def test_healthy_lab_has_no_drift(intent, healthy):
    assert [r.device for r in detect_drift(intent, healthy) if r.drifted] == []


def test_injected_faults_show_up_as_drift(intent, faults):
    reports = {r.device: r for r in detect_drift(intent, faults)}
    assert reports["leaf1"].extra == ["interface eth1 > shutdown"]
    assert reports["spine2"].extra == ["router bgp 65100 > neighbor 10.1.2.5 shutdown"]
    assert not reports["bb1"].drifted
