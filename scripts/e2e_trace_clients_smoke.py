#!/usr/bin/env python3
"""Live smoke test for the httpx trace-client backends.

Runs three known-good probes (verifying the wire shape matches our
mocked tests) and three known-bad probes (verifying 404/empty paths).
Prints a compact summary; exits non-zero if any probe behaves
unexpectedly.

Opt-in. Not run by CI — makes ~6 real HTTP requests against
clinicaltrials.gov, ChEMBL, and Europe PMC. Use to verify the mocked
response shapes in `tests/test_trace_clients_httpx.py` still match
the live APIs after a reviewer round or a published API change.

Usage:
  .venv/bin/python scripts/e2e_trace_clients_smoke.py
"""
from __future__ import annotations

import sys
from typing import Any

from agent.trace_clients._httpx import (
    HttpxDrugAliasClient,
    HttpxLiteratureClient,
    HttpxTrialRegistryClient,
)


def _probe(label: str, fn) -> tuple[bool, Any]:
    """Run a single probe; return (ok, result_or_error)."""
    try:
        return True, fn()
    except Exception as exc:  # noqa: BLE001 — smoke surfaces all failures
        return False, f"{type(exc).__name__}: {exc}"


def _format(record) -> str:
    if record is None:
        return "None"
    return repr(record)


def main() -> int:
    print("=" * 70)
    print("Live smoke: httpx trace clients vs CT.gov / ChEMBL / Europe PMC")
    print("=" * 70)

    failures: list[str] = []

    # --- TrialRegistry: known-good MASTERS NCT, known-bad fabricated NCT
    trial = HttpxTrialRegistryClient()
    ok, rec = _probe("CT.gov MASTERS", lambda: trial.get_trial("NCT02308228"))
    print(f"[CT.gov  good] NCT02308228 → ok={ok}: {_format(rec) if ok else rec}")
    if not ok or rec is None:
        failures.append("CT.gov MASTERS lookup did not return a record")
    elif rec.status not in ("completed", "active_not_recruiting"):
        # MASTERS is completed; tolerate 'active_not_recruiting' if CT.gov
        # decides to flip it (paper published, trial entry could lag).
        failures.append(f"CT.gov MASTERS status unexpected: {rec.status}")

    ok, rec = _probe("CT.gov fab", lambda: trial.get_trial("NCT99999999"))
    print(f"[CT.gov   bad] NCT99999999 → ok={ok}: {_format(rec) if ok else rec}")
    if not ok or rec is not None:
        failures.append("CT.gov fabricated NCT did not return None")

    # --- DrugAlias: known-good metformin, known-bad Glufomin
    chembl = HttpxDrugAliasClient()
    ok, rec = _probe("ChEMBL metformin", lambda: chembl.lookup("metformin"))
    print(f"[ChEMBL  good] metformin    → ok={ok}: {_format(rec) if ok else rec}")
    if not ok or rec is None:
        failures.append("ChEMBL metformin lookup did not return a record")
    elif rec.chembl_id is None:
        failures.append("ChEMBL metformin record had no chembl_id")

    ok, rec = _probe("ChEMBL Glufomin", lambda: chembl.lookup("Glufomin"))
    print(f"[ChEMBL   bad] Glufomin     → ok={ok}: {_format(rec) if ok else rec}")
    # Glufomin is the planted case 4 fake. ChEMBL's molecule/search may
    # return a partial-prefix hit — accept either None OR a record whose
    # canonical_name is clearly NOT 'Glufomin' (case-insensitive). The
    # citation_trace layer does the final disambiguation.
    if ok and rec is not None and rec.canonical_name.lower() == "glufomin":
        failures.append("ChEMBL Glufomin lookup unexpectedly returned an exact match")

    # --- Literature: known-good MASTERS DOI, known-bad fake DOI
    lit = HttpxLiteratureClient()
    ok, rec = _probe(
        "EuropePMC MASTERS", lambda: lit.fetch("10.1111/acel.13039"),
    )
    print(f"[EuPMC   good] 10.1111/acel.13039 → ok={ok}: {_format(rec) if ok else rec}")
    if not ok or rec is None:
        failures.append("EuropePMC MASTERS DOI did not return a record")
    elif "metformin" not in (rec.title or "").lower() + (rec.abstract or "").lower():
        failures.append("EuropePMC MASTERS record didn't mention metformin")

    ok, rec = _probe(
        "EuropePMC fake DOI", lambda: lit.fetch("10.9999/totally-fake-doi-xyz"),
    )
    print(f"[EuPMC    bad] 10.9999/totally-fake-doi-xyz → ok={ok}: {_format(rec) if ok else rec}")
    if not ok or rec is not None:
        failures.append("EuropePMC fake DOI did not return None")

    print("=" * 70)
    if failures:
        print(f"FAIL — {len(failures)} unexpected behaviors:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK — all 6 probes behaved as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
