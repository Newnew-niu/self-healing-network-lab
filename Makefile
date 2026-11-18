# Run these on the Linux lab host (the Ubuntu VM), from the repo root.
PY  := .venv/bin
LAB := clab/netlab.clab.yml

.PHONY: help venv configs deploy destroy check drift remediate monitor stop-monitor \
        chaos remediation-trials report test lint

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

venv:            ## create .venv and install netpulse with dev tools
	python3 -m venv .venv && $(PY)/pip install -q -e ".[dev]"

configs:         ## rebuild every FRR config + topology + prometheus.yml from intent/network.yml
	$(PY)/netpulse configs

deploy: configs  ## (re)deploy the whole lab with containerlab
	sudo containerlab deploy -t $(LAB) --reconfigure

destroy:         ## tear the lab down
	sudo containerlab destroy -t $(LAB) --cleanup

check:           ## health checks against the intent (exit 1 on any failure)
	$(PY)/netpulse check

drift:           ## compare running configs with the intent
	$(PY)/netpulse drift

remediate:       ## plan guarded fixes (dry-run). `make remediate APPLY=1` really applies them
	$(PY)/netpulse remediate $(if $(APPLY),--apply,)

monitor:         ## start the Prometheus exporter in the background (Grafana: http://<vm-ip>:3000)
	mkdir -p logs && nohup $(PY)/netpulse exporter > logs/exporter.log 2>&1 & echo $$! > logs/exporter.pid

stop-monitor:    ## stop the exporter
	-kill $$(cat logs/exporter.pid)

chaos:           ## fault injection + convergence measurement, BFD on and off (~30 min)
	$(PY)/netpulse chaos --repeats 5 --out results/chaos

remediation-trials: ## time detection + guarded auto-repair of config faults
	$(PY)/netpulse remediation-trials --repeats 5 --out results

report:          ## RCA Markdown reports for every chaos run
	$(PY)/netpulse report

test:            ## unit tests (no lab needed)
	$(PY)/pytest -q

lint:            ## ruff lint + format check
	$(PY)/ruff check . && $(PY)/ruff format --check .
