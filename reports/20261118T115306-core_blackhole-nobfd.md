# Incident report: 20261118T115306-core_blackhole-nobfd

## Summary
- **What failed:** link failure bb2-bb3 (grey failure: both interfaces up, but no traffic passes)
- **Impact:** host1 -> hostpop lost 821 probes = **8210 ms** of outage (11:53:09.808 -> 11:53:19.038 UTC); traffic then recovered on a redundant path.
- **Detected by:** BGP hold timer expiry (no BFD)
- **BFD:** off

## Timeline (UTC)
| Time | Source | Event |
|---|---|---|
| 11:53:09.808 | probe host1 | last reply before the outage |
| 11:53:15.850 | bb3 | %NOTIFICATION: sent to neighbor 10.255.0.2 4/0 (Hold Timer Expired) 0 bytes |
| 11:53:15.851 | bb3 | %ADJCHANGE: neighbor 10.255.0.2(bb2) in vrf default Down BGP Notification send |
| 11:53:18.852 | bb2 | %NOTIFICATION: sent to neighbor 10.255.0.3 4/0 (Hold Timer Expired) 0 bytes |
| 11:53:18.852 | bb2 | %ADJCHANGE: neighbor 10.255.0.3(bb3) in vrf default Down BGP Notification send |
| 11:53:19.038 | probe host1 | **first reply after the outage (recovered)** |
| 11:53:39.514 | bb3 | %ADJCHANGE: Adjacency to bb2 (eth2) for level-2 changed from Up to Down, holding time expired |
| 11:53:39.693 | bb2 | %ADJCHANGE: Adjacency to bb3 (eth3) for level-2 changed from Up to Down, holding time expired |
| 11:53:41.077 | bb2 | %ADJCHANGE: neighbor 10.255.0.3(bb3) in vrf default Up |
| 11:53:41.077 | bb3 | %ADJCHANGE: neighbor 10.255.0.2(bb2) in vrf default Up |

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
- Router log events in window: 10
- RCA self-check against the injected fault (link bb2-bb3): **correct**
