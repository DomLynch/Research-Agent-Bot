#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec .venv/bin/python -m pytest -q tests/test_loc_budget.py
