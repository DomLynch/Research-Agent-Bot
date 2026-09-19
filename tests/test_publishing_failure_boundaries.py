"""Real process and file-boundary regressions; no provider requests."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent.publishing.io import CorruptJsonState, atomic_write_json, revision_feedback
from publishing import fresh_lane as lane


def _alive(pid: int) -> bool:
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


def test_timeout_kills_detached_descendants_but_not_unrelated_process(tmp_path: Path) -> None:
    script = tmp_path / "tree.py"
    script.write_text('''import os, signal, subprocess, sys, time
from pathlib import Path
depth = int(sys.argv[1])
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if depth:
    subprocess.Popen([sys.executable, __file__, str(depth - 1)], start_new_session=True)
Path(__file__).with_suffix(f".{depth}.pid").write_text(str(os.getpid()))
time.sleep(60)
''')
    root = subprocess.Popen([sys.executable, str(script), "2"], start_new_session=True)
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    pids = [root.pid]
    try:
        deadline = time.monotonic() + 10
        while len(list(tmp_path.glob("*.pid"))) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(list(tmp_path.glob("*.pid"))) == 3
        pids = [int(path.read_text()) for path in tmp_path.glob("*.pid")]
        assert all(_alive(pid) for pid in pids)
        lane._kill_process_group(root)
        assert root.wait(timeout=5) == -signal.SIGKILL
        deadline = time.monotonic() + 5
        while any(_alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_alive(pid) for pid in pids)
        assert sentinel.poll() is None
    finally:
        pids += [int(path.read_text()) for path in tmp_path.glob("*.pid")]
        for pid in set(pids + [sentinel.pid]):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        root.wait(timeout=5)
        sentinel.wait(timeout=5)


@pytest.mark.parametrize("feedback", ["x" * 200000, "é🧬" * 102400, ""], ids=["large-ascii", "large-unicode", "fresh"])
def test_feedback_survives_real_spawn_without_large_environment(tmp_path: Path, monkeypatch, feedback: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_v06_synthesis.py").write_text('''import json, sys
from pathlib import Path
from agent.publishing.io import revision_feedback
out = Path(sys.argv[sys.argv.index("--out-dir") + 1])
out.mkdir(exist_ok=True)
(out / "received.json").write_text(json.dumps({"feedback": revision_feedback()}))
''')
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    # These inherited values must not contaminate the current run or overflow exec.
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK", "é" * 200000)
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK_FILE", "/missing/previous-run.json")
    monkeypatch.setattr(lane, "ROOT", tmp_path)
    out = tmp_path / "run"
    assert lane._run_synthesis("test", out, dry_run=True, timeout=10, revision_feedback=feedback) == 0
    assert json.loads((out / "received.json").read_text())["feedback"] == feedback


def test_feedback_file_is_fail_closed_and_legacy_input_still_works(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_REVISION_FEEDBACK_FILE", raising=False)
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK", "legacy ask")
    assert revision_feedback() == "legacy ask"
    path = tmp_path / "feedback.json"
    monkeypatch.setenv("RESEARKA_REVISION_FEEDBACK_FILE", str(path))
    with pytest.raises(ValueError, match="missing_or_invalid"):
        revision_feedback()
    path.write_text("{broken")
    with pytest.raises(CorruptJsonState):
        revision_feedback()
    atomic_write_json(path, {"feedback": "last ask preserved 🧬"})
    assert revision_feedback() == "last ask preserved 🧬"


def test_revision_gate_replacement_failure_keeps_previous_complete_file(tmp_path: Path, monkeypatch) -> None:
    import journal_finalizer as finalizer

    path = tmp_path / "revision_coverage_gate.json"
    previous = {"passed": False, "unmet": ["source selection"]}
    fresh = {"passed": True, "unmet": [], "evidence": "é" * 200000}
    atomic_write_json(path, previous)
    monkeypatch.setattr(finalizer, "_revision_gate_report", lambda *a, **kw: fresh)
    original_replace = os.replace

    def fail_replace(source, target):
        assert json.loads(Path(source).read_text()) == fresh
        assert json.loads(Path(target).read_text()) == previous
        raise OSError("injected replacement failure")

    monkeypatch.setattr("agent.publishing.io.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        finalizer._refresh_revision_coverage_gate(tmp_path)
    assert json.loads(path.read_text()) == previous
    assert not list(tmp_path.glob(".*.tmp"))
    monkeypatch.setattr("agent.publishing.io.os.replace", original_replace)
    assert finalizer._refresh_revision_coverage_gate(tmp_path)
    assert json.loads(path.read_text()) == fresh
