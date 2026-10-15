PY := .venv/bin/python
.PHONY: setup test lint qa site validate daily backtest

setup:            ## create the venv and install everything (no credentials needed)
	uv venv .venv --python 3.13 && uv pip install --python $(PY) -e ".[dev,fetch]"

test:             ## unit, parity, leakage, invariant, statistical and end-to-end tests
	$(PY) -m pytest -q -p no:warnings

lint:
	$(PY) -m ruff check src tests scripts

qa:               ## render the three fixture states in both modes, light and dark
	$(PY) scripts/design_qa.py

validate:         ## the claim -> evidence report (which tests back which claim, and their status)
	$(PY) scripts/validation_report.py

site:             ## build the site from the strong fixture (or FORECAST=path/to/latest.json)
	$(PY) scripts/build_site.py $(if $(FORECAST),--forecast $(FORECAST),--fixture strong) --out site/build/latest

backtest:         ## Phase 3 (needs state/ with S2S members and CDS truth)
	$(PY) scripts/run_backtest.py

history-s2s:      ## one-off S2S history pull, resumable, days of wall clock: run it locally (needs ECMWF_API_KEY)
	scripts/pull_history_s2s.sh

daily:            ## the operational run (needs ECMWF_API_KEY)
	$(PY) scripts/daily.py
