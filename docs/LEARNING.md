# Learning log

Concepts learned, commands run, mistakes made and how they were fixed — one section per phase.

---

## Phase 1 — Environment check (2026-11-18)

### What was built
- An Ubuntu Server 24.04.5 VM (`netlab`) in VMware Workstation 17, stored on D: (`D:\VMs\netlab`).
  8 GB RAM, 6 vCPU, 60 GB disk, NAT network, IP `192.168.58.139/24` on `ens160`.
- Passwordless SSH from Windows (ed25519 key) and passwordless sudo for the lab user (lab-only trade-off).
- Docker Engine 29.10.0 (official `get.docker.com` script, not the snap) and containerlab 0.83.0.
- Kernel modules `ip_gre`, `mpls_router`, `mpls_iptunnel` loaded at boot via `/etc/modules-load.d/netlab.conf`.

### Concepts
- **Network namespace**: a separate copy of the Linux network stack (own interfaces, routing table, ARP table).
  Every containerlab node is a container = its own namespace = behaves like its own router.
- **veth pair**: a virtual cable; whatever goes in one end comes out the other. containerlab uses these as links.
- **Control plane vs data plane**: FRR decides routes (control plane). Its `zebra` daemon installs them into the
  Linux kernel, and the kernel forwards packets and does GRE encapsulation (data plane).
  That is why the *host kernel* needs GRE/MPLS support, not just the FRR image.
- **Kernel config flags**: `=y` built in, `=m` loadable module, `is not set` = unsupported.
- **GRE overhead**: GRE tunnel MTU = 1500 − 20 (outer IPv4 header) − 4 (GRE header) = **1476**.
- **Public / private SSH key**: the public key goes into the server's `~/.ssh/authorized_keys`; the private key never
  leaves the client. `authorized_keys` must be `600` or sshd refuses it.
- **/24**: the first 24 bits are the network part, so 192.168.58.0–255 is one subnet (VM and VMnet8 share it).

### Decisions
- **VMware VM instead of WSL2**: VMware was already installed; installing WSL2 enables Hyper-V and slows VMware;
  the stock Ubuntu kernel ships MPLS modules (the WSL2 kernel may not); a separate SSH-managed Linux server is closer
  to real production work.
- **No LVM** in the installer: Ubuntu Server's default LVM layout only allocates part of the disk.
- **Everything on D:** (ISO, VM disk). Only `C:\Users\86180\.ssh` stays on C: (fixed OpenSSH location).

### Commands run and results
| Check | Command | Result |
|---|---|---|
| OS / kernel | `uname -r` | `6.8.0-149-generic`, Ubuntu 24.04.5 LTS |
| Disk | `df -h /` | 58G root, no LVM |
| Docker | `docker version` | client/server 29.10.0; `hello-world` OK |
| containerlab | `containerlab version` | 0.83.0 (2026-11-07) |
| Kernel flags | `grep ... /boot/config-$(uname -r)` | `NET_IPGRE=m`, `NET_IPGRE_DEMUX=m`, `MPLS=y`, `MPLS_ROUTING=m`, `MPLS_IPTUNNEL=m`, `NET_VRF=m` |
| GRE works | two netns + veth + `ip tunnel add gre1 mode gre` | ping 10.99.0.2: 3/3 received, 0% loss; `gre1` mtu **1476** |
| MPLS works | `modprobe mpls_router mpls_iptunnel; ls /proc/sys/net/mpls` | `conf default_ttl ip_ttl_propagate platform_labels` → MPLS stretch goal is possible |

GRE test (for re-running by hand):
```bash
sudo ip netns add a && sudo ip netns add b
sudo ip link add va type veth peer name vb
sudo ip link set va netns a && sudo ip link set vb netns b
sudo ip netns exec a ip addr add 192.0.2.1/30 dev va && sudo ip netns exec a ip link set va up
sudo ip netns exec b ip addr add 192.0.2.2/30 dev vb && sudo ip netns exec b ip link set vb up
sudo ip netns exec a ip tunnel add gre1 mode gre local 192.0.2.1 remote 192.0.2.2 ttl 64
sudo ip netns exec b ip tunnel add gre1 mode gre local 192.0.2.2 remote 192.0.2.1 ttl 64
sudo ip netns exec a ip addr add 10.99.0.1/30 dev gre1 && sudo ip netns exec a ip link set gre1 up
sudo ip netns exec b ip addr add 10.99.0.2/30 dev gre1 && sudo ip netns exec b ip link set gre1 up
sudo ip netns exec a ping -c 3 10.99.0.2
sudo ip netns del a; sudo ip netns del b
```

### Mistakes / surprises and fixes
- Installer pages differed from the checklist (e.g. no "installer update" or "Ubuntu Pro" page appeared) → pages vary by
  installer version; only Storage (no LVM), Profile, OpenSSH and snaps actually mattered.
- "Choose the base" page only offered Done/Back → the default `(X) Ubuntu Server` was already correct.
- `[FAILED] Failed unmounting cdrom.mount` at reboot → harmless; the ISO was still attached. Fix: disconnect the
  CD/DVD and untick "connect at power on".
- Automation over SSH failed on `sudo: a password is required` → added `/etc/sudoers.d/newnew` (NOPASSWD, mode 440).
  Acceptable only because the VM is on a private NAT network for lab use.

---

## Phase 2 - Two routers, one link (2026-11-18)

Lab: `labs/02-two-routers/` (r1 10.12.0.1/30, r2 10.12.0.2/30, loopbacks 1.1.1.1 / 2.2.2.2).
Output saved in `results/phase2-two-routers.txt`.

- **Subnet maths**: 10.12.0.0/30 = 4 addresses: .0 network, .1 r1, .2 r2, .3 broadcast.
  The main lab uses **/31** on router links (RFC 3021): no network/broadcast needed, both addresses usable.
- **ARP** in action: r1's ARP table for eth1 was **empty** before any traffic. After `ping 10.12.0.2`
  it held `10.12.0.2 lladdr aa:c1:ab:05:5e:46 REACHABLE` - exactly r2's eth1 MAC.
- **Connected vs static**: 10.12.0.0/30 is `C` (connected) automatically; r2's loopback 2.2.2.2 needed
  a static route (`S>* 2.2.2.2/32 via 10.12.0.2`) because it is not on a shared segment.

## Phases 3-5 - Fabric, backbone, POP (built from the intent)

Instead of hand-writing configs per phase, the whole network was described once in
`intent/network.yml` and rendered with Jinja2 (`make configs`). Concepts are in docs/CONCEPTS.md.

Commands I used most:
```bash
docker exec clab-netlab-leaf1 vtysh -c "show bgp summary"
docker exec clab-netlab-leaf1 vtysh -c "show ip route bgp"        # ECMP: two next hops
docker exec clab-netlab-bb1   vtysh -c "show isis neighbor"
docker exec clab-netlab-pop1  vtysh -c "show ip ospf neighbor"    # Full/- on gre1
docker exec clab-netlab-bb1   vtysh -c "show mpls ldp neighbor"
docker exec clab-netlab-host1 traceroute -n 192.168.30.2
```

Mistakes / surprises and fixes:
- **iBGP stuck in `Connect` right after deploy.** IS-IS had not converged, so the peer loopbacks were
  unreachable; TCP/179 could not open. It came up on its own seconds later (datacenter connect-retry 10 s).
- **POP unreachable although every protocol was up.** pop1 had two defaults: OSPF via the tunnel
  (distance 110) and Docker's management default (kernel, distance 0). The lower distance won, so return
  traffic left through eth0. Fix: `ip route del default` in every router container
  (`render.py: node_execs`). Lesson: keep management routing out of the data plane (mgmt VRF in real life).
- **Health check said spines were missing a prefix.** spine1 never has spine2's loopback: same AS
  65100, so the path via a leaf carries 65100 and eBGP loop prevention drops it. The network was right,
  my expectation was wrong; fixed in `intent.expected_bgp_prefixes()`.
- Verified path: host1 -> leaf1 -> spine2 -> bb2 -> bb3 -> (GRE) pop1 -> hostpop.
- LDP: all backbone sessions OPERATIONAL; labels are mostly `implicit-null` because in a triangle every
  router is one hop away (penultimate-hop popping).

## Phase 6 - netpulse (intent, collection, checks, tests, CI)

- Raw `vtysh -c "show ... json"` outputs from the real lab are saved under `tests/fixtures/` (healthy,
  faults, incidents). All parsing / checking / drift / remediation logic is a pure function of those,
  so 51 tests run without the lab (and in GitHub Actions).
- Two ping formats exist: iputils on the hosts ("5 received", "rtt ...") and busybox in FRR ("5 packets
  received", "round-trip ..."). The parser handles both.

## Phase 7 - Monitoring

- `make monitor` starts the exporter (every 5 s: collect -> 128 checks -> drift, ~3.8 s per cycle).
  Prometheus (in the lab) scrapes it at the management gateway 172.20.20.1:9101.
- Grafana dashboard is provisioned from JSON. Mistake: the state-timeline legend first showed threshold
  labels "< 1 / 1+" instead of "Down / Established" - fixed by colouring from value mappings.

## Phase 8 - Chaos tests

- Faults: `ip link set down` (hard) and `tc qdisc add dev X root netem loss 100%` (grey: link stays up).
- Mistakes: (1) after turning BFD off, my "wait until healthy" step demanded BFD sessions and aborted
  the suite - fixed by ignoring BFD checks in the BFD-off phase; (2) added try/finally so BFD is always
  restored to the intent afterwards.
- Surprise in the data: the backbone grey failure without BFD recovered in ~6 s, not the 30 s IS-IS hold
  time - the iBGP hold timer (9 s) fired first and BGP withdrew the routes. Read from router logs.

## Phase 9 - Remediation and drift

- The plan fixes **causes** and suppresses **symptoms**: e.g. "spine1 -> leaf1: Active; symptom of
  interface leaf1:eth1 admin down".
- Live run: 13 failed checks -> 2 executed actions -> 0 failed checks, 0 drift, audit chain intact.

## Phase 10 - RCA and AI summary

- RCA found the right component in 40/40 chaos incidents. Two bugs found by looking at real reports:
  (1) with BFD off, "missing" BFD sessions were counted as broken links; (2) FRR 10.6 logs
  "BFD down initiated" / "Cease/BFD Down", not the "BFD down received" I expected.
- The LLM summary is optional and guarded by a validator; not yet run against the real API.
