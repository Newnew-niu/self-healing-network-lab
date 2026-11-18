# Concepts - questions per phase, answered with this lab

Each answer points at something you can show or run in this repo.

## Phase 1 - Environment

**Q: The FRR container is already running - why did we need GRE support in the *host* kernel?**
FRR is the control plane: it computes routes and installs them via zebra (netlink) into the Linux
kernel. The kernel is the data plane: it forwards packets and adds the GRE header. Containers share
the host kernel, so no kernel GRE module = no tunnel, whatever FRR is configured to do.

**Q: What is a network namespace, and why does containerlab need one per router?**
A separate copy of the network stack: own interfaces, routing table, ARP table, sysctls. If all
routers shared one namespace they would share one routing table - you could not have leaf1 and
spine1 disagree about a route, which is the whole point of routing protocols.

**Q: Why is the GRE tunnel MTU 1476?**
1500 (Ethernet payload) - 20 (outer IPv4 header) - 4 (GRE header). A 1500-byte packet with DF set
cannot enter the tunnel: the router drops it and sends ICMP "fragmentation needed" (PMTUD). If that
ICMP is filtered you get a "black hole" - small pings work, large transfers hang.

## Phase 2 - IP, subnets, ARP

**Q: Why /31 on point-to-point links?** RFC 3021: a link with two routers needs no network or
broadcast address, so both addresses of a /31 are usable. Halves address use vs /30.

**Q: 10.1.1.0/31 - which address does each side get here?** spine1 = 10.1.1.0, leaf1 = 10.1.1.1
(`intent.py: _nth_address`).

**Q: What does ARP do and when would you look at it?** Maps a next-hop IP to a MAC on the local
segment. If a route exists but traffic does not flow on the first hop, check `ip neigh` for
INCOMPLETE/FAILED entries.

**Q: Why did we delete the default route inside every router container?** Docker adds a kernel
default route via the management network (administrative distance 0). It beat the OSPF default from
the tunnel (distance 110), so pop1 sent return traffic out of the management port. Real-world lesson:
keep management (out-of-band) routing separate from the data plane, usually with a management VRF.

## Phase 3 - Leaf-spine eBGP

**Q: Why is the BGP session not coming up if the ASN is wrong?** The OPEN message carries the
sender's AS. If it does not match the `remote-as` configured on the receiver, the receiver sends a
NOTIFICATION (OPEN Message Error / Bad Peer AS) and the session falls back to Idle/Active - it never
reaches Established. netpulse `check` also compares `remoteAs` with the intent.

**Q: Walk through the BGP states.** Idle -> Connect (TCP to port 179) -> Active (retrying TCP) ->
OpenSent -> OpenConfirm -> Established. "Active" is NOT good: it means TCP keeps failing.
`Idle (Admin)` = someone typed `neighbor X shutdown` (we saw this in the fault fixtures).

**Q: Why do both spines share AS 65100 and every leaf have its own ASN (RFC 7938)?**
eBGP loop prevention then stops paths like leaf -> spine1 -> leaf2 -> spine2 (spine2 sees its own AS
in AS_PATH). Side effect we hit: spine1 never learns spine2's loopback - the health check expected it
and failed until we encoded the rule in `expected_bgp_prefixes()`.

**Q: How does ECMP work here?** leaf1 learns 192.168.13.0/24 from both spines with equal AS_PATH
length (65100 65103) from the same neighbouring AS, so with `maximum-paths 8` both are installed.
The kernel hashes each flow (src/dst IP) onto one next hop - one flow uses one spine, which is why
the chaos test traceroutes first to find the spine that flow actually uses.

**Q: Why the LEAF-OUT route-map?** A leaf should never be transit: it only advertises its own
loopback and host LAN. Also FRR follows RFC 8212: eBGP sends/accepts nothing without a policy.

## Phase 4 - Backbone IS-IS + iBGP

**Q: IGP vs BGP - why both?** The IGP (IS-IS) gives fast, metric-based reachability for the
backbone's own loopbacks and links. iBGP carries the external/customer prefixes and uses the
loopbacks (reachable via IS-IS) as next hops. The IGP is small and fast; BGP is big and policy-rich.

**Q: Why iBGP between loopbacks and `update-source lo`?** A loopback never goes down while any path
exists; if bb1-bb3's direct link fails, IS-IS reroutes via bb2 and the iBGP session survives.

**Q: Why `next-hop-self`?** bb1 learns 10.0.1.1/32 from spine1 with next hop 10.2.0.1. bb3 has no
route to 10.2.0.1 (edge links are not in IS-IS), so the route would be unusable. next-hop-self
rewrites it to bb1's loopback.

**Q: Why no route reflector, and what breaks without a full mesh?** iBGP does not re-advertise
iBGP-learned routes (split horizon). With 3 routers a full mesh is 3 sessions - fine. At scale use
route reflectors.

**Q: Link-state in one sentence.** Every router floods its links (LSPs) to all, each builds the same
map and runs Dijkstra (SPF) to compute shortest paths.

**Q: How is the IS-IS NET built?** 49.0001 (private area) + system ID from the loopback
(010.255.000.001 -> 0102.5500.0001) + 00 selector.

**Q: Why was iBGP stuck in Connect right after deploy?** IS-IS had not converged yet, so the
loopbacks were unreachable; TCP to port 179 could not open. It came up by itself seconds later.

## Phase 5 - GRE + OSPF

**Q: What is encapsulation?** Wrapping a packet inside another: inner IP (172.16.0.x / LAN) inside
GRE inside an outer IP (198.51.100.1 -> 198.51.100.2). Transit routers only see the outer header.

**Q: Why are the tunnel endpoints NOT advertised into OSPF?** If pop1 learned the route to the
tunnel destination *through the tunnel*, the tunnel would depend on itself -> "recursive routing",
the tunnel flaps. Endpoints are reached by static /32s over the internet link; OSPF uses `network`
statements for only the loopback and LAN.

**Q: OSPF neighbour states?** Down -> Init -> 2-Way -> ExStart -> Exchange -> Loading -> Full.
Stuck in ExStart/Exchange is the classic MTU mismatch (DBD packets too big). Both gre1 ends are 1476.

**Q: Why `ip ospf network point-to-point` on gre1?** No DR/BDR election on a 2-router link; faster.

**Q: How do we know the GRE tunnel is "up"?** We don't trust the interface flag - GRE is stateless
and shows UP even if the far end is gone. netpulse checks the flag AND pings across the tunnel.

## Phase 6 - netpulse

**Q: Why a source of truth?** Configs, topology and health-check expectations all come from one
YAML. A change happens in one place; drift detection can say what the network *should* be.

**Q: How do you test without a lab?** Raw `vtysh ... json` outputs captured from the real lab are
saved as fixtures; parsers/checks/drift/remediation are pure functions of a snapshot (44 tests).

**Q: Why compare configs as sets of "context paths" instead of a text diff?** FRR reorders blocks
in `show running-config`; a set of `router bgp 65101 > address-family ... > maximum-paths 8` lines
ignores order but keeps meaning.

## Phase 7 - Monitoring

**Q: Why does the exporter build metrics on every scrape instead of keeping Gauges?** If a BGP
session disappears from the network its time series should disappear, not freeze at its last value.

**Q: Pull vs push?** Prometheus pulls (scrapes) every 5 s; easy to see if a target is down
(`up == 0`).

## Phase 8 - Chaos + BFD

**Q: What does BFD actually buy you? Measured here.** From `results/chaos/summary.md` (5 runs
each, median): leaf-spine grey failure 6770 ms without BFD vs 890 ms with BFD; spine grey failure
6730 vs 960 ms; backbone grey failure 6260 vs 830 ms - roughly 7x faster, ~86-87% less outage.
Without BFD, BGP waits for the hold timer (keepalive 3 s / hold 9 s with `frr defaults datacenter`),
so detection lands 6-9 s after the last keepalive; BFD at 300 ms x 3 detects in ~0.9 s.

**Q: Then why did BFD make no difference for `link_down`?** If the carrier drops, both ends see the
interface go down instantly and FRR tears the session down at once (fast external failover). BFD
helps when the failure is *invisible* to the interface.

**Q: In the core (bb2-bb3 grey failure) test without BFD, what detected the failure?**
Not IS-IS. IS-IS hold time is hello 3 s x multiplier 10 = 30 s, and the logs show the adjacency only
went down ~30 s after the fault. But the iBGP session bb2-bb3 runs over the loopbacks, and IS-IS
still routed it over the broken link, so the BGP hold timer (9 s) expired first: bb2 dropped the POP
routes it had learned from bb3, spine2 withdrew them, and leaf1 moved the flow to spine1/bb1.
Median outage 6.3 s. Lesson: an IGP with slow timers can be "rescued" by BGP, but you should not rely
on it - with BFD on IS-IS the outage was 0.83 s. (See any `reports/*core_blackhole-nobfd.md`.)

**Q: How do you measure convergence?** Ping every 10 ms; outage = lost packets x 10 ms. The largest
gap in sequence numbers gives the exact outage window used by the RCA timeline.

## Phase 9 - Remediation + drift

**Q: How do you stop automation from making an outage worse?** Dry-run by default, an allow-list
of action types, a max number of actions per run, an append-only hash-chained audit log, and
verification after acting. And fix causes, not symptoms: a BGP session down because its interface is
down gets no action of its own ("SUPPRESSED ... symptom of interface leaf1:eth1 admin down").

**Q: How do you make the audit log tamper-evident?** Each record stores the SHA-256 of the previous
record; editing a line breaks the chain (`netpulse audit-verify`, tested).

## Phase 10 - RCA + AI

**Q: How does the RCA decide node vs link failure?** Map failing adjacencies to device pairs. One
device in every broken pair that lost *all* its adjacencies -> node. Exactly one pair -> link
(interface down = hard failure, interfaces up = grey failure). Log reasons ("BFD down received" vs
"Hold Timer Expired") say what detected it. It is scored against the injected fault afterwards.

**Q: How do you use an LLM responsibly here?** It only rewords facts the RCA already computed. A
deterministic validator rejects the summary if any number, IP or device name is not in the source
data, and every rejection is logged. The LLM never decides or acts.
