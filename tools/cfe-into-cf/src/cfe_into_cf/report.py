"""Отчёт о переносе расширения в основную конфигурацию."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class RunReport:
    extension: str = ""
    dry_run: bool = False
    own_objects: list[str] = field(default_factory=list)
    adopted_objects: list[str] = field(default_factory=list)
    bsl_modules: list[str] = field(default_factory=list)
    lock_objects: list[str] = field(default_factory=list)
    locked: bool = False
    merged: bool = False
    loaded: bool = False
    db_updated: bool = False
    repo_committed: bool = False
    touched_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aborted_new_objects: bool = False
    work_dir: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def write_json(self, path: Path | str) -> None:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
