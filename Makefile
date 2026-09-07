PYTHON ?= .venv/bin/python
JSCPD := npm exec --yes --package=jscpd@5.1.2 -- jscpd

.PHONY: quality complexity duplicates
quality: complexity duplicates
	$(PYTHON) -m ruff check agent scripts tests
	$(PYTHON) -m coverage run --branch --include='*/agent/revision_contract.py,*/scripts/revision_coverage.py' -m pytest -q tests/test_revision_coverage.py tests/test_loc_budget.py
	$(PYTHON) -m coverage report

complexity:
	$(PYTHON) quality/check_complexity.py agent scripts

duplicates:
	$(JSCPD) . --config quality/jscpd.json --baseline quality/duplication-baseline.json --fail-on-new-clones --no-tips
