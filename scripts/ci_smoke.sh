#!/usr/bin/env bash
set -euo pipefail

# Local CI smoke test — mirrors the GitHub CI gate steps.
# Usage: bash scripts/ci_smoke.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export PYTHONPATH="$PROJECT_DIR"

cd "$PROJECT_DIR"

echo "=== 1. ruff check ==="
"$PROJECT_DIR/.venv/bin/python" -m ruff check .

echo ""
echo "=== 2. type check ==="
"$PROJECT_DIR/.venv/bin/python" -m mypy agent scripts

echo ""
echo "=== 3. LOC budgets ==="
"$PROJECT_DIR/.venv/bin/python" -m pytest -q tests/test_loc_budget.py

echo ""
echo "=== 4. unit tests (skip gold_smoke + full_matrix) ==="
"$PROJECT_DIR/.venv/bin/python" -m pytest tests/ -v --tb=short -m "not gold_smoke and not full_matrix"

echo ""
echo "=== CI smoke passed ==="
