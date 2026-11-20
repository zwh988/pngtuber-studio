"""The app shell's console-free startup helpers (backend/main.py)."""

import io
import sys
from pathlib import Path

import pytest

from backend import main
from backend.app import APP_NAME
from backend.settings import app_data_dir


def test_names_match_the_app() -> None:
    assert main.APP_NAME == APP_NAME
    assert main.log_path() == app_data_dir() / main.LOG_NAME


def test_ensure_stdio_fills_missing_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "sub" / "app.log"
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    main.ensure_stdio(log)
    try:
        print("hello")
        sys.stderr.write("oops\n")
        sys.stderr.flush()
        assert log.read_text(encoding="utf-8") == "hello\noops\n"
    finally:
        sys.stderr.close()


def test_ensure_stdio_keeps_real_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    main.ensure_stdio(tmp_path / "app.log")
    assert sys.stdout is out and sys.stderr is err
    assert not (tmp_path / "app.log").exists()


def test_log_exception_appends_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    log = tmp_path / "app.log"
    try:
        raise ValueError("boom")
    except ValueError:
        main.log_exception(log, "failed")
    text = log.read_text(encoding="utf-8")
    assert "failed" in text and "ValueError: boom" in text
    assert "ValueError: boom" in err.getvalue()


def test_splash_escapes_the_error() -> None:
    page = main.splash_html("Could not start", "<script>x</script>")
    assert "&lt;script&gt;" in page and "<script>" not in page
    assert 'class="error"' in page
    assert "data:image/png;base64," in page
    assert 'class="busy"' in main.splash_html()
