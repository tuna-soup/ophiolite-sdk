PYTHON ?= python3
.PHONY: dev live test
dev:
	OPHIOLITE_PYTHON=$(PYTHON) npm run dev
live:
	OPHIOLITE_PYTHON=$(PYTHON) npm run dev:live
test:
	$(PYTHON) tools/test.py
