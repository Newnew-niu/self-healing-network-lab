# Incident report: 20261118T115043-node_blackhole-nobfd

## Summary
- **What failed:** node failure of spine1 (all adjacencies of the device lost at once)
- **Impact:** host1 -> host3 lost 730 probes = **7300 ms** of outage (11:50:46.149 -> 11:50:54.379 UTC); traffic then recovered on a redundant path.
- **Detected by:** BGP hold timer expiry (no BFD)
- **BFD:** off

## Timeline (UTC)
| Time | Source | Event |
|---|---|---|
| 11:50:46.149 | probe host1 | last reply before the outage |
| 11:50:53.790 | spine1 | %NOTIFICATION: received from neighbor 10.1.1.1 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:53.790 | spine1 | %ADJCHANGE: neighbor 10.1.1.1(leaf1) in vrf default Down BGP Notification received |
| 11:50:53.790 | leaf1 | %NOTIFICATION: sent to neighbor 10.1.1.0 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:53.790 | leaf1 | %ADJCHANGE: neighbor 10.1.1.0(spine1) in vrf default Down BGP Notification send |
| 11:50:54.299 | spine1 | %NOTIFICATION: received from neighbor 10.2.0.0 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:54.299 | spine1 | %ADJCHANGE: neighbor 10.2.0.0(bb1) in vrf default Down BGP Notification received |
| 11:50:54.299 | leaf3 | %NOTIFICATION: sent to neighbor 10.1.1.4 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:54.299 | bb1 | %NOTIFICATION: sent to neighbor 10.2.0.1 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:54.299 | bb1 | %ADJCHANGE: neighbor 10.2.0.1(spine1) in vrf default Down BGP Notification send |
| 11:50:54.300 | spine1 | %NOTIFICATION: received from neighbor 10.1.1.5 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:54.300 | spine1 | %ADJCHANGE: neighbor 10.1.1.5(leaf3) in vrf default Down BGP Notification received |
| 11:50:54.300 | leaf2 | %NOTIFICATION: sent to neighbor 10.1.1.2 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:54.300 | leaf2 | %ADJCHANGE: neighbor 10.1.1.2(spine1) in vrf default Down BGP Notification send |
| 11:50:54.300 | leaf3 | %ADJCHANGE: neighbor 10.1.1.4(spine1) in vrf default Down BGP Notification send |
| 11:50:54.301 | spine1 | %NOTIFICATION: received from neighbor 10.1.1.3 4/0 (Hold Timer Expired) 0 bytes |
| 11:50:54.301 | spine1 | %ADJCHANGE: neighbor 10.1.1.3(leaf2) in vrf default Down BGP Notification received |
| 11:50:54.379 | probe host1 | **first reply after the outage (recovered)** |

## Root cause
**node failure of spine1** - all adjacencies of the device lost at once.

Evidence (health checks while the fault was present):
- bgp_session on spine1 -> leaf1(10.1.1.1): Connect
- bgp_session on leaf1 -> spine1(10.1.1.0): Connect
- bgp_session on spine1 -> leaf2(10.1.1.3): Connect
- bgp_session on leaf2 -> spine1(10.1.1.2): Connect
- bgp_session on spine1 -> leaf3(10.1.1.5): Connect
- bgp_session on leaf3 -> spine1(10.1.1.4): Connect
- bgp_session on spine1 -> bb1(10.2.0.0): Connect
- bgp_session on bb1 -> spine1(10.2.0.1): Connect

## Fix / follow-up
- Traffic already moved to the remaining spine(s) by ECMP; drain spine1 (keep its BGP sessions shut) until it is repaired.
- Investigate spine1 hardware/software (it stopped forwarding and stopped answering BFD/BGP on every port).

## Data
- Failed checks during fault: 37 of 128
- Router log events in window: 16
- RCA self-check against the injected fault (node spine1): **correct**
