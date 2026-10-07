PY := ./.venv/bin/python
RUN ?= final

.PHONY: setup test smoke pilot estimate final validate process figures reviewer-analysis all

setup:
	python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest tests/ -q

smoke:
	$(PY) experiments/experiment.py --smoke
	$(MAKE) validate process figures RUN=smoke

pilot:
	$(PY) experiments/experiment.py --pilot

estimate:
	$(PY) analysis/estimate_runtime.py results/raw/pilot --final-config experiments/config.yaml

final:
	$(PY) experiments/experiment.py --config experiments/config.yaml

validate:
	$(PY) analysis/validate.py results/raw/$(RUN)

process:
	$(PY) analysis/process.py results/raw/$(RUN)

figures:
	$(PY) analysis/plots.py results/processed/$(RUN)

reviewer-analysis:
	$(PY) analysis/reviewer_reanalysis.py

all: test validate process figures reviewer-analysis
