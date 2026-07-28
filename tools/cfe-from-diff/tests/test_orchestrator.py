from pathlib import Path

import pytest

from cfe_tools.git_staging import prepare_changes_from_git
from cfe_tools.orchestrator import run_cfe_from_diff
from fixtures_builder import CHANGED_BSL, make_changes_tree, make_config_tree, write_bom


def test_end_to_end_skip_build(tmp_path: Path):
    cfg = make_config_tree(tmp_path / "config")
    ch = make_changes_tree(tmp_path / "changes")
    out = tmp_path / "ext"

    report = run_cfe_from_diff(
        name="TestExt",
        config=cfg,
        changes=ch,
        output=out,
        skip_build=True,
        purpose="Patch",
        prefix="TestExt_",
        report_path=tmp_path / "report.json",
    )

    assert (out / "Configuration.xml").is_file()
    assert (out / "Catalogs" / "ТестовыйСправочник.xml").is_file()
    bsl = out / "Catalogs" / "ТестовыйСправочник" / "Ext" / "ManagerModule.bsl"
    assert bsl.is_file()
    content = bsl.read_text(encoding="utf-8-sig")
    assert "&ИзменениеИКонтроль" in content
    assert "ДобавленныйМетод" in content
    assert "Catalog.ТестовыйСправочник" in report.borrowed
    assert (tmp_path / "report.json").is_file()


def test_dry_run(tmp_path: Path):
    cfg = make_config_tree(tmp_path / "config")
    ch = make_changes_tree(tmp_path / "changes")
    report = run_cfe_from_diff(
        name="TestExt",
        config=cfg,
        changes=ch,
        output=tmp_path / "ext",
        dry_run=True,
        skip_build=True,
    )
    assert report.borrowed
    assert not (tmp_path / "ext" / "Configuration.xml").exists()


def test_git_staging_then_dry_run(tmp_path: Path):
    """GUI-style flow: export DiffTo blobs, then inventory via dry-run."""
    import shutil
    import subprocess

    # Base config lives outside the git repo (as --config usually does)
    cfg = make_config_tree(tmp_path / "config-base")

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True, capture_output=True)

    # Dump inside repo starts as a copy of base, then we change BSL
    dump = repo / "dump"
    shutil.copytree(cfg, dump)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    h1 = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    write_bom(
        dump / "Catalogs" / "ТестовыйСправочник" / "Ext" / "ManagerModule.bsl",
        CHANGED_BSL,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "change bsl"], cwd=repo, check=True, capture_output=True)
    h2 = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    staging = prepare_changes_from_git(
        repo,
        h1,
        h2,
        dump_prefix="dump/",
        staging_dir=tmp_path / "staging",
    )
    assert staging.exported >= 1

    report = run_cfe_from_diff(
        name="TestExt",
        config=cfg,
        changes=staging.staging_dir,
        output=tmp_path / "ext",
        dry_run=True,
        skip_build=True,
    )
    assert any("ТестовыйСправочник" in b for b in report.borrowed)
    assert report.bsl_files


def test_force_refuses_wipe_when_output_equals_config(tmp_path: Path):
    from cfe_tools.vendor.cfe_init import CfeInitError

    cfg = make_config_tree(tmp_path / "config")
    ch = make_changes_tree(tmp_path / "changes")
    # Pretend config is also an extension output
    (cfg / "Configuration.xml").write_text(
        (cfg / "Configuration.xml").read_text(encoding="utf-8-sig"),
        encoding="utf-8-sig",
    )

    with pytest.raises(CfeInitError, match="Refusing to delete"):
        run_cfe_from_diff(
            name="TestExt",
            config=cfg,
            changes=ch,
            output=cfg,
            skip_build=True,
            force_output=True,
        )


def test_force_allows_clean_rerun(tmp_path: Path):
    cfg = make_config_tree(tmp_path / "config")
    ch = make_changes_tree(tmp_path / "changes")
    out = tmp_path / "ext"

    run_cfe_from_diff(
        name="TestExt",
        config=cfg,
        changes=ch,
        output=out,
        skip_build=True,
        purpose="Patch",
        prefix="TestExt_",
    )
    report = run_cfe_from_diff(
        name="TestExt",
        config=cfg,
        changes=ch,
        output=out,
        skip_build=True,
        purpose="Patch",
        prefix="TestExt_",
        force_output=True,
    )
    assert (out / "Configuration.xml").is_file()
    assert report.borrowed


def test_validate_errors_skip_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_config_tree(tmp_path / "config")
    ch = make_changes_tree(tmp_path / "changes")
    out = tmp_path / "ext"
    built = {"called": False}

    monkeypatch.setattr("cfe_tools.orchestrator.validate_extension", lambda *_a, **_k: 3)

    def fake_build(*_a, **_k):
        built["called"] = True
        return "x.cfe"

    monkeypatch.setattr("cfe_tools.orchestrator.build_cfe", fake_build)

    report = run_cfe_from_diff(
        name="TestExt",
        config=cfg,
        changes=ch,
        output=out,
        cfe=tmp_path / "out.cfe",
        ib_path=tmp_path / "ib",
        skip_build=False,
        purpose="Patch",
        prefix="TestExt_",
    )
    assert report.validate_errors == 3
    assert report.built is False
    assert built["called"] is False
    assert any("Skipping ibcmd build" in w for w in report.warnings)
