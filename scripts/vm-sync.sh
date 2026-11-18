#!/usr/bin/env bash
# Sync the repo between the Windows checkout (D:\Desktop\self-healing-network-lab, git lives here)
# and the lab VM (~/self-healing-network-lab, where containerlab runs).
#   scripts/vm-sync.sh push   # code/docs -> VM
#   scripts/vm-sync.sh pull   # results/, logs/, reports/, test fixtures, generated configs <- VM
set -euo pipefail
VM="${VM:-newnew@192.168.58.139}"
DIR="self-healing-network-lab"
cd "$(dirname "$0")/.."
case "${1:-push}" in
  push)
    tar --exclude=.git --exclude=.venv --exclude='__pycache__' --exclude=.pytest_cache \
        --exclude=.ruff_cache --exclude=results --exclude=logs --exclude=reports \
        --exclude='clab/clab-*' -czf - . | ssh "$VM" "mkdir -p $DIR && tar -xzf - -C $DIR" ;;
  pull)
    ssh "$VM" "cd $DIR && tar -czf - --ignore-failed-read results logs reports tests/fixtures configs clab/netlab.clab.yml monitoring/prometheus.yml 2>/dev/null" | tar -xzf - ;;
  *) echo "usage: $0 push|pull" >&2; exit 2 ;;
esac
