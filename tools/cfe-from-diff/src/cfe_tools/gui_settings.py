"""Persist GUI form settings between sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SETTINGS_VERSION = 1


def settings_path() -> Path:
    """User-writable settings file (not inside the tool install tree)."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "cfe-tools" / "gui-settings.json"


# Keys persisted automatically (password intentionally excluded).
PERSIST_STRINGS = (
    "name",
    "purpose",
    "prefix",
    "config",
    "output",
    "ib_path",
    "ibcmd",
    "user",
)

PERSIST_BOOLS = (
    "skip_build",
    "force",
    "own_commits_only",
)


def load_settings(path: Path | None = None) -> dict[str, Any]:
    p = path or settings_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_settings(data: dict[str, Any], path: Path | None = None) -> Path:
    p = path or settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SETTINGS_VERSION, **data}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p
