import copy

import pytest
import yaml

from netpulse.intent import IntentError, parse_intent
from tests.conftest import ROOT


def raw_intent() -> dict:
    return yaml.safe_load((ROOT / "intent" / "network.yml").read_text())


def test_p2p_links_use_both_addresses_of_a_31(intent):
    leaf1 = {i.name: i for i in intent.interfaces("leaf1")}
    assert str(leaf1["eth1"].ip) == "10.1.1.1/31"
    assert str(leaf1["eth1"].peer_ip) == "10.1.1.0/31"
    assert leaf1["eth1"].peer == "spine1"


def test_isis_net_is_derived_from_loopback(intent):
    assert intent.devices["bb1"].isis_net == "49.0001.0102.5500.0001.00"
    assert intent.devices["bb3"].isis_net == "49.0001.0102.5500.0003.00"


def test_bgp_neighbors_per_role(intent):
    leaf = intent.bgp_neighbors("leaf1")
    assert {(n.peer, n.remote_as, n.group) for n in leaf} == {
        ("spine1", 65100, "FABRIC"),
        ("spine2", 65100, "FABRIC"),
    }
    bb1 = {(n.peer, n.group) for n in intent.bgp_neighbors("bb1")}
    assert bb1 == {("spine1", "EDGE"), ("bb2", "IBGP"), ("bb3", "IBGP")}
    assert intent.bgp_neighbors("pop1") == []


def test_spines_do_not_expect_each_others_loopback(intent):
    """Same ASN on both spines -> eBGP loop prevention drops the other spine's /32."""
    assert "10.0.0.2/32" not in intent.expected_bgp_prefixes("spine1")
    assert "10.0.0.2/32" in intent.expected_bgp_prefixes("leaf1")
    # backbone routers share an AS but use iBGP, so they see everything
    assert intent.expected_bgp_prefixes("bb1") == intent.expected_bgp_prefixes("leaf1")


def test_pop_prefixes(intent):
    assert set(intent.pop_prefixes()) == {"10.255.1.1/32", "192.168.30.0/24"}


def test_duplicate_ip_is_rejected():
    raw = raw_intent()
    raw["devices"]["leaf2"]["loopback"] = raw["devices"]["leaf1"]["loopback"]
    with pytest.raises(IntentError, match="10.0.1.1"):
        parse_intent(raw)


def test_spines_must_share_asn():
    raw = copy.deepcopy(raw_intent())
    raw["devices"]["spine2"]["asn"] = 65199
    with pytest.raises(IntentError, match="spines must share"):
        parse_intent(raw)


def test_unknown_device_in_link_is_rejected():
    raw = raw_intent()
    raw["links"].append(
        {"type": "fabric", "a": "spine1:eth9", "b": "leaf9:eth1", "subnet": "10.9.9.0/31"}
    )
    with pytest.raises(IntentError, match="unknown device leaf9"):
        parse_intent(raw)
