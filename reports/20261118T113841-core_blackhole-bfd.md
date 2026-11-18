# Incident report: 20261118T113841-core_blackhole-bfd

## Summary
- **What failed:** link failure bb2-bb3 (grey failure: both interfaces up, but no traffic passes)
- **Impact:** host1 -> hostpop lost 87 probes = **870 ms** of outage (11:38:44.598 -> 11:38:45.618 UTC); traffic then recovered on a redundant path.
- **Detected by:** IS-IS adjacency loss
- **BFD:** on

## Timeline (UTC)
| Time | Source | Event |
|---|---|---|
| 11:38:44.598 | probe host1 | last reply before the outage |
| 11:38:45.476 | bb3 | %ADJCHANGE: Adjacency to bb2 (eth2) for level-2 changed from Up to Down, bfd session went down |
| 11:38:45.543 | bb2 | %ADJCHANGE: Adjacency to bb3 (eth3) for level-2 changed from Up to Down, bfd session went down |
| 11:38:45.618 | probe host1 | **first reply after the outage (recovered)** |

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
- Failed checks during fault: 6 of 128
- Router log events in window: 2
- RCA self-check against the injected fault (link bb2-bb3): **correct**
