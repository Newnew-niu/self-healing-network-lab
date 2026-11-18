from netpulse.render import node_execs, render_router, render_topology


def test_leaf_config_has_rfc7938_bgp(intent):
    conf = render_router(intent, "leaf1")
    assert "router bgp 65101" in conf
    assert " neighbor 10.1.1.0 remote-as 65100" in conf
    assert " neighbor FABRIC bfd" in conf
    assert "  network 192.168.11.0/24" in conf
    assert "  neighbor FABRIC route-map LEAF-OUT out" in conf  # leaf is never transit


def test_backbone_config_has_isis_ibgp_ldp(intent):
    conf = render_router(intent, "bb1")
    assert "router isis CORE" in conf
    assert " net 49.0001.0102.5500.0001.00" in conf
    assert " neighbor IBGP update-source lo" in conf
    assert "  neighbor IBGP next-hop-self" in conf
    assert "mpls ldp" in conf


def test_pop_never_advertises_tunnel_endpoint_into_ospf(intent):
    conf = render_router(intent, "pop1")
    assert " network 10.255.1.1/32 area 0" in conf
    assert "198.51.100.2/32 area" not in conf  # would cause recursive routing
    assert "ip route 198.51.100.1/32 203.0.113.0" in conf


def test_every_router_renders(intent):
    for dev in intent.routers():
        assert f"hostname {dev.name}" in render_router(intent, dev.name)


def test_topology_lists_every_link_and_creates_gre(intent):
    topo = render_topology(intent)
    assert topo.count("- endpoints:") == len(intent.links)
    execs = node_execs(intent)
    assert any("ip tunnel add gre1 mode gre" in c for c in execs["bb3"])
    assert "ip route del default" in execs["leaf1"]
