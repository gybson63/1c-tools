"""Orchestrator offline / dry-run / accept-new-objects gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from cfe_into_cf.orchestrator import NewObjectsNotAcceptedError, run_cfe_into_cf
from fixtures_builder import build_extension_dump, build_main_dump


def test_dry_run_aborts_without_accept(tmp_path: Path) -> None:
    main = build_main_dump(tmp_path / "main")
    ext = build_extension_dump(tmp_path / "ext")
    with pytest.raises(NewObjectsNotAcceptedError) as ei:
        run_cfe_into_cf(
            extension="TestExt",
            extension_dump=str(ext),
            main_dump=str(main),
            skip_designer=True,
            dry_run=True,
            accept_new_objects=False,
            work_dir=str(tmp_path / "work"),
        )
    assert "Тст_Новый" in ei.value.alert_text


def test_offline_merge_with_accept(tmp_path: Path) -> None:
    main = build_main_dump(tmp_path / "main")
    ext = build_extension_dump(tmp_path / "ext")
    report = run_cfe_into_cf(
        extension="TestExt",
        extension_dump=str(ext),
        main_dump=str(main),
        skip_designer=True,
        accept_new_objects=True,
        work_dir=str(tmp_path / "work"),
        report_path=str(tmp_path / "report.json"),
    )
    assert report.merged is True
    assert report.loaded is False  # skip_designer
    assert "Catalog.Тст_Новый" in report.own_objects
    merged = tmp_path / "work" / "main-merged" / "Catalogs" / "Тст_Новый.xml"
    assert merged.is_file()
    assert (tmp_path / "report.json").is_file()
