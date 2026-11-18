# Incident report: 20261118T113326-link_blackhole-bfd

## Summary
- **What failed:** link failure leaf1-spine1 (grey failure: both interfaces up, but no traffic passes)
- **Impact:** host1 -> host3 lost 98 probes = **980 ms** of outage (11:33:29.556 -> 11:33:30.665 UTC); traffic then recovered on a redundant path.
- **Detected by:** BFD (sub-second failure detection)
- **BFD:** on

## Timeline (UTC)
| Time | Source | Event |
|---|---|---|
| 11:33:29.556 | probe host1 | last reply before the outage |
| 11:33:30.449 | spine1 | %NOTIFICATION(Hard Reset): sent to neighbor 10.1.1.1 6/10 (Cease/BFD Down) 0 bytes |
| 11:33:30.449 | spine1 | %ADJCHANGE: neighbor 10.1.1.1(leaf1) in vrf default Down BFD down initiated |
| 11:33:30.585 | leaf1 | %NOTIFICATION(Hard Reset): sent to neighbor 10.1.1.0 6/10 (Cease/BFD Down) 0 bytes |
| 11:33:30.585 | leaf1 | %ADJCHANGE: neighbor 10.1.1.0(spine1) in vrf default Down BFD down initiated |
| 11:33:30.665 | probe host1 | **first reply after the outage (recovered)** |

## Root cause
**link failure leaf1-spine1** - grey failure: both interfaces up, but no traffic passes.

Evidence (health checks while the fault was present):
- bgp_session on spine1 -> leaf1(10.1.1.1): Connect
- bfd_peer on spine1 -> leaf1(10.1.1.1): down
- bgp_session on leaf1 -> spine1(10.1.1.0): Connect
- bfd_peer on leaf1 -> spine1(10.1.1.0): down

## Fix / follow-up
- Link leaf1-spine1 shows UP but drops traffic: check optics / cabling / any middle box; keep the link out of service until counters are clean.
- Traffic was rerouted automatically; no customer action needed.

## Data
- Failed checks during fault: 6 of 128
- Router log events in window: 4
- RCA self-check against the injected fault (link leaf1-spine1): **correct**
