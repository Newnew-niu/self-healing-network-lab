# Incident report: 20261118T113656-node_blackhole-bfd

## Summary
- **What failed:** node failure of spine1 (all adjacencies of the device lost at once)
- **Impact:** host1 -> host3 lost 87 probes = **870 ms** of outage (11:36:59.590 -> 11:37:00.575 UTC); traffic then recovered on a redundant path.
- **Detected by:** BFD (sub-second failure detection)
- **BFD:** on

## Timeline (UTC)
| Time | Source | Event |
|---|---|---|
| 11:36:59.590 | probe host1 | last reply before the outage |
| 11:37:00.420 | spine1 | %NOTIFICATION(Hard Reset): received from neighbor 10.1.1.1 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.420 | spine1 | %ADJCHANGE: neighbor 10.1.1.1(leaf1) in vrf default Down BGP Notification received |
| 11:37:00.420 | leaf1 | %NOTIFICATION(Hard Reset): sent to neighbor 10.1.1.0 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.420 | leaf1 | %ADJCHANGE: neighbor 10.1.1.0(spine1) in vrf default Down BFD down initiated |
| 11:37:00.496 | spine1 | %NOTIFICATION(Hard Reset): received from neighbor 10.1.1.5 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.496 | spine1 | %ADJCHANGE: neighbor 10.1.1.5(leaf3) in vrf default Down BGP Notification received |
| 11:37:00.496 | leaf3 | %NOTIFICATION(Hard Reset): sent to neighbor 10.1.1.4 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.496 | leaf3 | %ADJCHANGE: neighbor 10.1.1.4(spine1) in vrf default Down BFD down initiated |
| 11:37:00.575 | probe host1 | **first reply after the outage (recovered)** |
| 11:37:00.613 | spine1 | %NOTIFICATION(Hard Reset): received from neighbor 10.1.1.3 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.613 | spine1 | %ADJCHANGE: neighbor 10.1.1.3(leaf2) in vrf default Down BGP Notification received |
| 11:37:00.613 | leaf2 | %NOTIFICATION(Hard Reset): sent to neighbor 10.1.1.2 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.613 | leaf2 | %ADJCHANGE: neighbor 10.1.1.2(spine1) in vrf default Down BFD down initiated |
| 11:37:00.750 | bb1 | %NOTIFICATION(Hard Reset): sent to neighbor 10.2.0.1 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.750 | bb1 | %ADJCHANGE: neighbor 10.2.0.1(spine1) in vrf default Down BFD down initiated |
| 11:37:00.751 | spine1 | %NOTIFICATION(Hard Reset): received from neighbor 10.2.0.0 6/10 (Cease/BFD Down) 0 bytes |
| 11:37:00.751 | spine1 | %ADJCHANGE: neighbor 10.2.0.0(bb1) in vrf default Down BGP Notification received |

## Root cause
**node failure of spine1** - all adjacencies of the device lost at once.

Evidence (health checks while the fault was present):
- bgp_session on spine1 -> leaf1(10.1.1.1): Connect
- bfd_peer on spine1 -> leaf1(10.1.1.1): init
- bgp_session on leaf1 -> spine1(10.1.1.0): Connect
- bfd_peer on leaf1 -> spine1(10.1.1.0): down
- bgp_session on spine1 -> leaf2(10.1.1.3): Connect
- bfd_peer on spine1 -> leaf2(10.1.1.3): init
- bgp_session on leaf2 -> spine1(10.1.1.2): Connect
- bfd_peer on leaf2 -> spine1(10.1.1.2): down
- bgp_session on spine1 -> leaf3(10.1.1.5): Connect
- bfd_peer on spine1 -> leaf3(10.1.1.5): init
- bgp_session on leaf3 -> spine1(10.1.1.4): Connect
- bfd_peer on leaf3 -> spine1(10.1.1.4): down
- bgp_session on spine1 -> bb1(10.2.0.0): Connect
- bfd_peer on spine1 -> bb1(10.2.0.0): init
- bgp_session on bb1 -> spine1(10.2.0.1): Connect
- bfd_peer on bb1 -> spine1(10.2.0.1): down

## Fix / follow-up
- Traffic already moved to the remaining spine(s) by ECMP; drain spine1 (keep its BGP sessions shut) until it is repaired.
- Investigate spine1 hardware/software (it stopped forwarding and stopped answering BFD/BGP on every port).

## Data
- Failed checks during fault: 23 of 128
- Router log events in window: 16
- RCA self-check against the injected fault (node spine1): **correct**
