"""Verify LOC reporting remains visible without turning size into a release gate."""
import pytest

from quality.check_loc import _count_loc, _report_size, report


def test_count_loc(tmp_path):
    source = tmp_path / "example.py"
    source.write_text("\n# comment\n  # indented comment\nx = 1  # inline\ny = 2\n")
    assert _count_loc(source) == 2


@pytest.mark.parametrize("count,status", [(799, "INFO"), (800, "INFO"), (801, "WARNING")])
def test_threshold_is_advisory(count, status, capsys):
    _report_size("example.py", count, 800)
    assert capsys.readouterr().out == (
        f"{status}: example.py: {count} effective LOC (advisory threshold 800)\n"
    )


def test_all_size_thresholds_report_without_blocking(tmp_path, capsys):
    for directory, count in (("agent", 25270), ("scripts", 40232)):
        folder = tmp_path / directory
        folder.mkdir()
        (folder / "example.py").write_text("x = 1\n" * count)
        cache = folder / "__pycache__"
        cache.mkdir()
        (cache / "ignored.py").write_text("x = 1\n")
    assert report(tmp_path) is None
    output = capsys.readouterr().out
    for label, count, threshold in (
        ("agent", 25270, 25269), ("agent/example.py", 25270, 800),
        ("scripts", 40232, 40231), ("scripts/example.py", 40232, 5700),
        ("agent/ + scripts/", 65502, 65500),
    ):
        assert f"WARNING: {label}: {count} effective LOC (advisory threshold {threshold})" in output


def test_missing_directory_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        report(tmp_path)


def test_unreadable_source_is_an_error(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "invalid.py").write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        report(tmp_path)
