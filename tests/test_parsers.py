from netpulse import parsers
from netpulse.collect import (
    BFD_PEERS,
    BGP_SUMMARY,
    BGP_TABLE,
    INTERFACES,
    ISIS_NEIGHBORS,
    LDP_NEIGHBORS,
    OSPF_NEIGHBORS,
)


def test_bgp_summary_healthy(healthy):
    peers = parsers.bgp_summary(healthy.get("leaf1", BGP_SUMMARY))
    assert set(peers) == {"10.1.1.0", "10.1.2.0"}
    assert all(p.up for p in peers.values())
    assert peers["10.1.1.0"].remote_as == 65100
    assert peers["10.1.1.0"].hostname == "spine1"


def test_bgp_summary_admin_shutdown(faults):
    p = parsers.bgp_summary(faults.get("spine2", BGP_SUMMARY))["10.1.2.5"]
    assert not p.up
    assert p.peer_state == "Admin"


def test_bgp_table_has_ecmp_route(healthy):
    assert "192.168.30.0/24" in parsers.bgp_table_prefixes(healthy.get("leaf1", BGP_TABLE))


def test_bfd_isis_ospf_ldp(healthy):
    assert parsers.bfd_peers(healthy.get("leaf1", BFD_PEERS))["10.1.1.0"].status == "up"
    adj = parsers.isis_adjacencies(healthy.get("bb1", ISIS_NEIGHBORS))
    assert adj["eth2"].neighbor == "bb2" and adj["eth2"].state == "Up"
    ospf = parsers.ospf_neighbors(healthy.get("pop1", OSPF_NEIGHBORS))
    assert ospf[0].interface == "gre1" and ospf[0].state == "Full"
    assert parsers.ldp_neighbors(healthy.get("bb1", LDP_NEIGHBORS))["10.255.0.2"].state == (
        "OPERATIONAL"
    )


def test_interface_admin_down(faults):
    itf = parsers.interfaces(faults.get("leaf1", INTERFACES))["eth1"]
    assert not itf.admin_up and not itf.oper_up


def test_ping_iputils_and_busybox():
    iputils = (
        "5 packets transmitted, 4 received, 20% packet loss, time 825ms\n"
        "rtt min/avg/max/mdev = 0.105/0.159/0.201/0.037 ms\n"
    )
    busybox = (
        "3 packets transmitted, 3 packets received, 0% packet loss\n"
        "round-trip min/avg/max = 0.069/0.118/0.160 ms\n"
    )
    a = parsers.ping(iputils)
    assert (a.sent, a.received, a.avg_ms, a.loss_ratio) == (5, 4, 0.159, 0.2)
    b = parsers.ping(busybox)
    assert (b.sent, b.received, b.avg_ms) == (3, 3, 0.118)
    assert parsers.ping("").loss_ratio == 1.0


def test_garbage_input_does_not_crash():
    assert parsers.bgp_summary("% Unknown command") == {}
    assert parsers.isis_adjacencies(None) == {}
