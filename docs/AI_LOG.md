# AI-assisted work log

Honest record, per phase, of what the AI (Claude Code) drafted, what I changed, bugs I found in AI output,
and rough time saved. "Time saved" is a rough estimate, not a measurement, and is marked as such.

---

## Phase 1 — Environment check (2026-11-18)

**AI drafted / did**
- Environment plan, then switched recommendation from WSL2 to a VMware Ubuntu VM after detecting VMware on my PC.
- Downloaded the Ubuntu 24.04.5 ISO and verified its SHA256 against the official `SHA256SUMS`.
- Wrote the VMware `.vmx` file and created the virtual disk from the command line (`vmware-vdiskmanager`).
- Generated the SSH key; installed Docker and containerlab over SSH; ran the kernel / GRE / MPLS checks.

**What I did / changed**
- Required that all downloads and data live on D: (the AI's first plan defaulted to C:).
- Chose the VMware option; ran the Ubuntu installer myself; set username, hostname, password.
- Ran the two commands that need my password (copy SSH public key, sudoers rule).

**Bugs / inaccuracies in AI output**
- First instructions assumed WSL2 and used `/proc/config.gz` for the kernel check; on a normal Ubuntu VM the
  config is in `/boot/config-$(uname -r)`. Corrected when the plan changed.
- The installer checklist listed pages that never appeared (installer versions differ).

**Rough time saved (estimate by the AI assistant, not measured)**: about 3-4 hours. Setting up the VM,
Docker, containerlab and the kernel checks by hand, as someone new to Linux networking, would likely
take most of a day; with the AI it took about 1.5 hours of my time (mainly the Ubuntu installer).

---

## Phases 2-11 - Build, measure, document (2026-11-18)

After Phase 1 I asked the AI to build the rest end-to-end and to write the concept questions in
docs/CONCEPTS.md, instead of stopping after each phase.

**AI drafted / did**
- `intent/network.yml` design (addressing, ASNs, link types), all of `netpulse/`, templates, tests,
  Makefile, CI, Grafana dashboard, docs.
- Deployed the lab in my VM over SSH, captured fixtures, ran the chaos suite (40 runs), the remediation
  trials (10 runs), the Phase 2 lab, and took the Grafana screenshot in my browser.

**What I did / changed**
- Decided to skip the per-phase questions and review them from docs/CONCEPTS.md instead.
- Reviewed what goes into the public repository and had non-technical, personal content removed
  before publishing; chose to publish the repository with CI running on every push.

**Bugs / wrong assumptions in AI output (found by running against the real lab)**
1. Kept Docker's management default route in routers -> POP return traffic leaked out of eth0.
2. Health check expected spines to learn each other's loopback (wrong for RFC 7938, same spine ASN).
3. Chaos suite aborted after BFD was turned off: the readiness check still required BFD sessions.
4. RCA treated "BFD not configured" as broken links when BFD was off.
5. RCA matched an outdated FRR log string ("BFD down received"); FRR 10.6 says "BFD down initiated".
6. Predicted the no-BFD backbone outage would be ~30 s (IS-IS hold time); the data showed ~6 s because
   the BGP hold timer fired first. docs/CONCEPTS.md was corrected to match the data.
7. Three times an AI-written code-patching script turned a `"\n"` inside an f-string into a real line
   break, producing a SyntaxError; caught by running the CLI / ruff.
8. RCA timeline was not sorted by time; one AI-written unit test was stricter than the behaviour
   (equal timestamps) and failed.
9. Grafana legend showed "< 1 / 1+" instead of state names until the panel used value-mapping colours.
10. Ran two sync commands in parallel, so `tar` failed ("file changed as we read it") and the first
    remediation-trial run never started.

**Measured outcome**: 51 unit tests, 128 health checks, 40/40 RCA, BFD -86-87% outage on grey
failures, 10/10 config faults auto-repaired (numbers in README, sources in results/).

**Rough time saved (estimate by the AI assistant, not measured)**: about 60-80 hours. The repo has
~3,200 lines of netpulse code and templates, ~500 lines of tests and ~600 lines of docs, plus 50
fault-injection runs; writing and debugging that alone while learning BGP/IS-IS/OSPF would likely
take 2-3 weeks of full-time work. The AI built it in about a day; my time went into decisions and
reviewing the results.
