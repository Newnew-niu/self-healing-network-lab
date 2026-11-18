# Incident reports

RCA correct on **40 of 40** incidents (scored against the fault the chaos test really injected).

| Run | Inferred root cause | Detected by | Correct |
|---|---|---|---|
| [20261118T113027-link_down-bfd](20261118T113027-link_down-bfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T113056-link_down-bfd](20261118T113056-link_down-bfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T113126-link_down-bfd](20261118T113126-link_down-bfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T113155-link_down-bfd](20261118T113155-link_down-bfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T113222-link_down-bfd](20261118T113222-link_down-bfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T113251-link_blackhole-bfd](20261118T113251-link_blackhole-bfd.md) | link failure leaf1-spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113326-link_blackhole-bfd](20261118T113326-link_blackhole-bfd.md) | link failure leaf1-spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113401-link_blackhole-bfd](20261118T113401-link_blackhole-bfd.md) | link failure leaf1-spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113436-link_blackhole-bfd](20261118T113436-link_blackhole-bfd.md) | link failure leaf1-spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113511-link_blackhole-bfd](20261118T113511-link_blackhole-bfd.md) | link failure leaf1-spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113546-node_blackhole-bfd](20261118T113546-node_blackhole-bfd.md) | node failure of spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113621-node_blackhole-bfd](20261118T113621-node_blackhole-bfd.md) | node failure of spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113656-node_blackhole-bfd](20261118T113656-node_blackhole-bfd.md) | node failure of spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113731-node_blackhole-bfd](20261118T113731-node_blackhole-bfd.md) | node failure of spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113806-node_blackhole-bfd](20261118T113806-node_blackhole-bfd.md) | node failure of spine1 | BFD (sub-second failure detection) | yes |
| [20261118T113841-core_blackhole-bfd](20261118T113841-core_blackhole-bfd.md) | link failure bb2-bb3 | IS-IS adjacency loss | yes |
| [20261118T113947-core_blackhole-bfd](20261118T113947-core_blackhole-bfd.md) | link failure bb2-bb3 | IS-IS adjacency loss | yes |
| [20261118T114056-core_blackhole-bfd](20261118T114056-core_blackhole-bfd.md) | link failure bb2-bb3 | IS-IS adjacency loss | yes |
| [20261118T114203-core_blackhole-bfd](20261118T114203-core_blackhole-bfd.md) | link failure bb2-bb3 | IS-IS adjacency loss | yes |
| [20261118T114311-core_blackhole-bfd](20261118T114311-core_blackhole-bfd.md) | link failure bb2-bb3 | IS-IS adjacency loss | yes |
| [20261118T114429-link_down-nobfd](20261118T114429-link_down-nobfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T114457-link_down-nobfd](20261118T114457-link_down-nobfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T114526-link_down-nobfd](20261118T114526-link_down-nobfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T114555-link_down-nobfd](20261118T114555-link_down-nobfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T114629-link_down-nobfd](20261118T114629-link_down-nobfd.md) | link failure leaf1-spine1 | interface down event | yes |
| [20261118T114657-link_blackhole-nobfd](20261118T114657-link_blackhole-nobfd.md) | link failure leaf1-spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T114731-link_blackhole-nobfd](20261118T114731-link_blackhole-nobfd.md) | link failure leaf1-spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T114812-link_blackhole-nobfd](20261118T114812-link_blackhole-nobfd.md) | link failure leaf1-spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T114846-link_blackhole-nobfd](20261118T114846-link_blackhole-nobfd.md) | link failure leaf1-spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T114927-link_blackhole-nobfd](20261118T114927-link_blackhole-nobfd.md) | link failure leaf1-spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115002-node_blackhole-nobfd](20261118T115002-node_blackhole-nobfd.md) | node failure of spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115043-node_blackhole-nobfd](20261118T115043-node_blackhole-nobfd.md) | node failure of spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115122-node_blackhole-nobfd](20261118T115122-node_blackhole-nobfd.md) | node failure of spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115156-node_blackhole-nobfd](20261118T115156-node_blackhole-nobfd.md) | node failure of spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115231-node_blackhole-nobfd](20261118T115231-node_blackhole-nobfd.md) | node failure of spine1 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115306-core_blackhole-nobfd](20261118T115306-core_blackhole-nobfd.md) | link failure bb2-bb3 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115413-core_blackhole-nobfd](20261118T115413-core_blackhole-nobfd.md) | link failure bb2-bb3 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115516-core_blackhole-nobfd](20261118T115516-core_blackhole-nobfd.md) | link failure bb2-bb3 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115623-core_blackhole-nobfd](20261118T115623-core_blackhole-nobfd.md) | link failure bb2-bb3 | BGP hold timer expiry (no BFD) | yes |
| [20261118T115726-core_blackhole-nobfd](20261118T115726-core_blackhole-nobfd.md) | link failure bb2-bb3 | BGP hold timer expiry (no BFD) | yes |
