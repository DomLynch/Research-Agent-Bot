from __future__ import annotations

from agent import app


def test_paused_service_copy_is_current() -> None:
    body = app._PAUSE_HTML
    assert "Research Agent service paused" in body
    assert "claim graphs, manifests, verdict JSON" in body
    assert "Proof 001" not in body
    assert "Day 5" not in body


def test_run_command_points_to_active_synthesis_entrypoints(capsys) -> None:
    rc = app.main(["run", "--topic", "rapamycin"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "scripts/run_v06_synthesis.py" in captured.err
    assert "Proof 001" not in captured.err
