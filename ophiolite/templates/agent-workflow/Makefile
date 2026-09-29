PYTHON ?= python3
.PHONY: dev live test
dev:
	$(PYTHON) workflow.py --fixture
live:
	$(PYTHON) workflow.py
test:
	$(PYTHON) -m pytest -q tests
