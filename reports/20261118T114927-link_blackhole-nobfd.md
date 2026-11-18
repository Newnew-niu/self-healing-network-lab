# Incident report: 20261118T114927-link_blackhole-nobfd

## Summary
- **What failed:** link failure leaf1-spine1 (grey failure: both interfaces up, but no traffic passes)
- **Impact:** host1 -> host3 lost 559 probes = **5590 ms** of outage (11:49:30.375 -> 11:49:36.608 UTC); traffic then recovered on a redundant path.
- **Detected by:** BGP hold timer expiry (no BFD)
- **BFD:** off

## Timeline (UTC)
| Time | Source | Event |
|---|---|---|
| 11:49:30.375 | probe host1 | last reply before the outage |
| 11:49:36.481 | leaf1 | %NOTIFICATION: sent to neighbor 10.1.1.0 4/0 (Hold Timer Expired) 0 bytes |
| 11:49:36.481 | leaf1 | %ADJCHANGE: neighbor 10.1.1.0(spine1) in vrf default Down BGP Notification send |
| 11:49:36.482 | spine1 | %NOTIFICATION: sent to neighbor 10.1.1.1 4/0 (Hold Timer Expired) 0 bytes |
| 11:49:36.482 | spine1 | %ADJCHANGE: neighbor 10.1.1.1(leaf1) in vrf default Down BGP Notification send |
| 11:49:36.608 | probe host1 | **first reply after the outage (recovered)** |

## Root cause
**link failure leaf1-spine1** - grey failure: both interfaces up, but no traffic passes.

Evidence (health checks while the fault was present):
- bgp_session on spine1 -> leaf1(10.1.1.1): Connect
- bgp_session on leaf1 -> spine1(10.1.1.0): Connect

## Fix / follow-up
- Link leaf1-spine1 shows UP but drops traffic: check optics / cabling / any middle box; keep the link out of service until counters are clean.
- Traffic was rerouted automatically; no customer action needed.

## Data
- Failed checks during fault: 26 of 128
- Router log events in window: 4
- RCA self-check against the injected fault (link leaf1-spine1): **correct**
