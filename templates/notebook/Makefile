PYTHON ?= python3
.PHONY: dev live test
dev:
	$(PYTHON) dev.py
live:
	$(PYTHON) -m jupyterlab --ip=127.0.0.1 --no-browser read-and-plot.ipynb
test:
	$(PYTHON) -m pytest -q tests
