#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
# Compatibility entry point: source size is advisory.
exec .venv/bin/python quality/check_loc.py
