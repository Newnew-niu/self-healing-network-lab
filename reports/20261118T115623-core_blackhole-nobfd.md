# Incident report: 20261118T115623-core_blackhole-nobfd

## Summary
- **What failed:** link failure bb2-bb3 (grey failure: both interfaces up, but no traffic passes)
- **Impact:** host1 -> hostpop lost 754 probes = **7540 ms** of outage (11:56:26.527 -> 11:56:35.044 UTC); traffic then recovered on a redundant path.
- **Detected by:** BGP hold timer expiry (no BFD)
- **BFD:** off

## Timeline (UTC)
| Time | Source | Event |
|---|---|---|
| 11:56:26.527 | probe host1 | last reply before the outage |
| 11:56:34.857 | bb3 | %NOTIFICATION: sent to neighbor 10.255.0.2 4/0 (Hold Timer Expired) 0 bytes |
| 11:56:34.857 | bb3 | %ADJCHANGE: neighbor 10.255.0.2(bb2) in vrf default Down BGP Notification send |
| 11:56:34.863 | bb2 | %NOTIFICATION: sent to neighbor 10.255.0.3 4/0 (Hold Timer Expired) 0 bytes |
| 11:56:34.863 | bb2 | %ADJCHANGE: neighbor 10.255.0.3(bb3) in vrf default Down BGP Notification send |
| 11:56:35.044 | probe host1 | **first reply after the outage (recovered)** |
| 11:56:54.435 | bb3 | %ADJCHANGE: Adjacency to bb2 (eth2) for level-2 changed from Up to Down, holding time expired |
| 11:56:54.626 | bb2 | %ADJCHANGE: Adjacency to bb3 (eth3) for level-2 changed from Up to Down, holding time expired |
| 11:56:57.109 | bb2 | %NOTIFICATION: sent to neighbor 10.255.0.3 6/7 (Cease/Connection Collision Resolution) 0 bytes |
| 11:56:57.109 | bb2 | %NOTIFICATION: sent to neighbor 10.255.0.3 6/7 (Cease/Connection Collision Resolution) 0 bytes |
| 11:56:57.109 | bb3 | %NOTIFICATION: sent to neighbor 10.255.0.2 6/7 (Cease/Connection Collision Resolution) 0 bytes |
| 11:56:57.109 | bb3 | %ADJCHANGE: neighbor 10.255.0.2(bb2) in vrf default Up |
| 11:56:57.110 | bb2 | %ADJCHANGE: neighbor 10.255.0.3(bb3) in vrf default Up |

## Root cause
**link failure bb2-bb3** - grey failure: both interfaces up, but no traffic passes.

Evidence (health checks while the fault was present):
- isis_adjacency on bb2 -> eth3->bb3: no adjacency
- ldp_neighbor on bb2 -> bb3: missing
- isis_adjacency on bb3 -> eth2->bb2: no adjacency
- ldp_neighbor on bb3 -> bb2: missing

## Fix / follow-up
- Link bb2-bb3 shows UP but drops traffic: check optics / cabling / any middle box; keep the link out of service until counters are clean.
- Traffic was rerouted automatically; no customer action needed.

## Data
- Failed checks during fault: 26 of 128
- Router log events in window: 13
- RCA self-check against the injected fault (link bb2-bb3): **correct**
