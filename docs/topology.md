# Topology

Generated from `intent/network.yml` (the source of truth). 9 FRR 10.6.2 routers, 3 Linux test hosts,
Prometheus + Grafana, all in containerlab on one Ubuntu 24.04 VM.

```mermaid
flowchart TB
  subgraph DC["Data-centre fabric - eBGP only (RFC 7938), ECMP, BFD"]
    spine1["spine1<br/>AS 65100<br/>lo 10.0.0.1"]
    spine2["spine2<br/>AS 65100<br/>lo 10.0.0.2"]
    leaf1["leaf1<br/>AS 65101<br/>lo 10.0.1.1"]
    leaf2["leaf2<br/>AS 65102<br/>lo 10.0.1.2"]
    leaf3["leaf3<br/>AS 65103<br/>lo 10.0.1.3"]
    host1["host1<br/>192.168.11.2/24"]
    host3["host3<br/>192.168.13.2/24"]
  end
  subgraph BB["Backbone AS 65000 - IS-IS L2 + iBGP between loopbacks + LDP"]
    bb1["bb1<br/>lo 10.255.0.1<br/>NET 49.0001.0102.5500.0001.00"]
    bb2["bb2<br/>lo 10.255.0.2<br/>NET 49.0001.0102.5500.0002.00"]
    bb3["bb3<br/>lo 10.255.0.3 + 198.51.100.1<br/>NET 49.0001.0102.5500.0003.00"]
  end
  subgraph POP["Remote POP - OSPF area 0 inside GRE"]
    pop1["pop1<br/>lo 10.255.1.1 + 198.51.100.2"]
    hostpop["hostpop<br/>192.168.30.2/24"]
  end

  spine1 ---|"10.1.1.0/31 eth1-eth1"| leaf1
  spine1 ---|"10.1.1.2/31 eth2-eth1"| leaf2
  spine1 ---|"10.1.1.4/31 eth3-eth1"| leaf3
  spine2 ---|"10.1.2.0/31 eth1-eth2"| leaf1
  spine2 ---|"10.1.2.2/31 eth2-eth2"| leaf2
  spine2 ---|"10.1.2.4/31 eth3-eth2"| leaf3
  leaf1 ---|"192.168.11.0/24 eth3"| host1
  leaf3 ---|"192.168.13.0/24 eth3"| host3
  bb1 ---|"eBGP 10.2.0.0/31 eth1-eth4"| spine1
  bb2 ---|"eBGP 10.2.0.2/31 eth1-eth4"| spine2
  bb1 ---|"IS-IS 10.3.0.0/31 eth2-eth2"| bb2
  bb2 ---|"IS-IS 10.3.0.2/31 eth3-eth2"| bb3
  bb1 ---|"IS-IS 10.3.0.4/31 eth3-eth1"| bb3
  bb3 ---|"internet 203.0.113.0/31 eth3-eth1"| pop1
  bb3 -.-|"GRE gre1 172.16.0.0/30<br/>198.51.100.1 to 198.51.100.2<br/>OSPF area 0, MTU 1476"| pop1
  pop1 ---|"192.168.30.0/24 eth2"| hostpop
```

## Address plan

| Range | Use |
|---|---|
| 10.0.0.0/24 | spine loopbacks |
| 10.0.1.0/24 | leaf loopbacks |
| 10.1.1.0/24, 10.1.2.0/24 | leaf-spine /31 links (spine1, spine2) |
| 10.2.0.0/24 | spine-backbone /31 links (eBGP) |
| 10.3.0.0/24 | backbone triangle /31 links (IS-IS) |
| 10.255.0.0/24 | backbone loopbacks (iBGP update-source, LDP transport) |
| 10.255.1.0/24 | POP loopback (advertised in OSPF) |
| 198.51.100.0/24 | GRE tunnel endpoints ("public" /32s on lo, reached by static routes, never in OSPF) |
| 203.0.113.0/31 | "internet" link bb3-pop1 |
| 172.16.0.0/30 | inside the GRE tunnel |
| 192.168.11/13/30.0/24 | host LANs (router .1, host .2) |
| 172.20.20.0/24 | containerlab management network (out of band, not routed) |

## Who runs what

| Device | Protocols |
|---|---|
| leaf1-3 | eBGP to both spines (peer-group FABRIC, BFD), originate loopback + host LAN, `LEAF-OUT` policy: only own prefixes (never transit) |
| spine1-2 | eBGP to all leaves (FABRIC) and to one backbone router (EDGE), BFD |
| bb1, bb2 | eBGP to a spine (EDGE, BFD), IS-IS L2 on the triangle (BFD), iBGP full mesh between loopbacks with next-hop-self, LDP |
| bb3 | IS-IS + iBGP + LDP, GRE to pop1, OSPF on gre1 with `default-information originate`, redistributes the POP prefixes OSPF -> BGP |
| pop1 | OSPF on gre1 (loopback + LAN only), static /32 to the far tunnel endpoint over the internet link |

## Measured healthy path (traceroute)

`host1 -> leaf1 (192.168.11.1) -> spine2 (10.1.2.0) -> bb2 (10.2.0.2) -> bb3 (10.3.0.3) -> pop1 (172.16.0.2, through GRE) -> hostpop`
