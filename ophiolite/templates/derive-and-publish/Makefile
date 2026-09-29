PYTHON ?= python3
.PHONY: dev live test
dev:
	$(PYTHON) -m app --fixture
live:
	$(PYTHON) -m app
test:
	$(PYTHON) -m pytest -q tests
