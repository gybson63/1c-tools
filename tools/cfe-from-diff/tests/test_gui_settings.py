"""Tests for GUI settings persistence."""

from __future__ import annotations

from pathlib import Path

from cfe_tools.gui_settings import load_settings, save_settings


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "gui-settings.json"
    data = {
        "git_repo": r"C:\repo",
        "ib_path": r"C:\ib",
        "ibcmd": r"C:\Program Files\1cv8\bin\ibcmd.exe",
        "skip_build": True,
        "force": False,
    }
    saved = save_settings(data, path=path)
    assert saved == path
    loaded = load_settings(path)
    assert loaded["git_repo"] == data["git_repo"]
    assert loaded["ibcmd"] == data["ibcmd"]
    assert loaded["skip_build"] is True
    assert loaded["version"] == 1


def test_load_missing_or_corrupt(tmp_path: Path):
    assert load_settings(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_settings(bad) == {}
