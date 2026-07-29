"""Tests for git staging helpers used by the GUI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cfe_tools.git_staging import (
    CommitInfo,
    GitError,
    commit_is_mine,
    commit_parent,
    decode_git_c_quoted,
    decode_git_quoted_paths,
    export_changes_tree,
    get_file_diff,
    list_changed_files,
    list_own_commits,
    map_repo_paths_to_objects,
    normalize_dump_prefix,
    prepare_changes_from_git,
    resolve_cf_location,
    strip_dump_prefix,
)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
    )


def _init_repo(tmp: Path, *, name: str = "Test User", email: str = "test@example.com") -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", name)
    _git(repo, "config", "user.email", email)
    return repo


def _commit_file(repo: Path, rel: str, content: str, message: str) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel.replace("\\", "/"))
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_normalize_and_strip_prefix():
    assert normalize_dump_prefix("") == ""
    assert normalize_dump_prefix("src/cf") == "src/cf/"
    assert normalize_dump_prefix("src\\cf\\") == "src/cf/"
    assert strip_dump_prefix("src/cf/Catalogs/X.xml", "src/cf/") == "Catalogs/X.xml"
    assert strip_dump_prefix("SRC/CF/Catalogs/X.xml", "src/cf/") == "Catalogs/X.xml"
    assert strip_dump_prefix("Catalogs/X.xml", "") == "Catalogs/X.xml"


def test_commit_is_mine_email_or_name():
    c = CommitInfo(
        hash="a" * 40,
        short_hash="abcdef0",
        subject="fix",
        author_name="Ivan Petrov",
        author_email="ivan@corp.local",
        author_date="2026-01-01T00:00:00+00:00",
    )
    # email mismatch, name match → mine
    assert commit_is_mine(c, author_name="Ivan Petrov", author_email="other@example.com")
    # email match, name mismatch → mine
    assert commit_is_mine(c, author_name="Someone", author_email="ivan@corp.local")
    # case-insensitive
    assert commit_is_mine(c, author_name="ivan petrov", author_email="")
    assert commit_is_mine(c, author_name="", author_email="IVAN@CORP.LOCAL")
    # both mismatch → not mine
    assert not commit_is_mine(c, author_name="Other", author_email="other@example.com")
    assert not commit_is_mine(c, author_name="", author_email="")


def test_list_own_commits_matches_by_name_when_email_differs(tmp_path: Path):
    repo = _init_repo(tmp_path, name="Test User", email="test@example.com")
    _commit_file(repo, "a.txt", "1", "mine")
    # Same name, different email in config vs what was used for commit — recreate identity
    _git(repo, "config", "user.email", "alias@example.com")
    # Commit was authored as test@example.com; filter by name should still find it
    commits = list_own_commits(repo, author_name="Test User", author_email="alias@example.com")
    assert any(c.subject == "mine" for c in commits)


def test_resolve_cf_location_from_configuration_xml(tmp_path: Path):
    repo = _init_repo(tmp_path)
    cf = repo / "src" / "cf"
    cf.mkdir(parents=True)
    cfg = cf / "Configuration.xml"
    cfg.write_text("<Config/>", encoding="utf-8")
    (cf / "CommonModules").mkdir()
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init dump")

    root, prefix = resolve_cf_location(cfg)
    assert root == repo.resolve()
    assert prefix == "src/cf"

    # Dump directory still accepted if it contains Configuration.xml
    root2, prefix2 = resolve_cf_location(cf)
    assert root2 == repo.resolve()
    assert prefix2 == "src/cf"


def test_resolve_cf_location_dump_at_repo_root(tmp_path: Path):
    repo = _init_repo(tmp_path)
    cfg = repo / "Configuration.xml"
    cfg.write_text("<Config/>", encoding="utf-8")
    (repo / "CommonModules").mkdir()
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "root dump")
    root, prefix = resolve_cf_location(cfg)
    assert root == repo.resolve()
    assert prefix == ""


def test_resolve_cf_location_rejects_repo_root_without_xml(tmp_path: Path):
    repo = _init_repo(tmp_path)
    (repo / "src" / "cf").mkdir(parents=True)
    (repo / "src" / "cf" / "Configuration.xml").write_text("<Config/>", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "nested")
    with pytest.raises(GitError, match="Configuration.xml"):
        resolve_cf_location(repo)


def test_resolve_cf_location_errors(tmp_path: Path):
    lonely = tmp_path / "no-git" / "cf"
    lonely.mkdir(parents=True)
    (lonely / "Configuration.xml").write_text("<Config/>", encoding="utf-8")
    with pytest.raises(GitError, match="не найден"):
        resolve_cf_location(lonely / "Configuration.xml")
    with pytest.raises(GitError, match="не найден"):
        resolve_cf_location(tmp_path / "missing" / "Configuration.xml")


def test_list_own_commits_filters_by_identity(tmp_path: Path):
    repo = _init_repo(tmp_path)
    h1 = _commit_file(repo, "Catalogs/A.xml", "v1", "mine first")

    # Foreign author commit
    _git(repo, "config", "user.name", "Other")
    _git(repo, "config", "user.email", "other@example.com")
    _commit_file(repo, "Catalogs/B.xml", "v2", "foreign")

    # Back to original identity for a third commit
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    h3 = _commit_file(repo, "Catalogs/C.xml", "v3", "mine second")

    commits = list_own_commits(repo, author_email="test@example.com")
    subjects = [c.subject for c in commits]
    assert "mine first" in subjects
    assert "mine second" in subjects
    assert "foreign" not in subjects
    hashes = {c.hash for c in commits}
    assert h1 in hashes and h3 in hashes


def test_decode_git_quoted_cyrillic_paths() -> None:
    # "Заказ" in UTF-8 as git octal escapes
    inner = r"a/src/cf/Documents/\320\227\320\260\320\272\320\260\320\267.xml"
    assert decode_git_c_quoted(inner) == "a/src/cf/Documents/Заказ.xml"

    header = (
        r'diff --git "a/src/cf/Documents/\320\227\320\260\320\272\320\260\320\267'
        r'\320\237\320\276\320\272\321\203\320\277.xml" '
        r'"b/src/cf/Documents/\320\227\320\260\320\272\320\260\320\267'
        r'\320\237\320\276\320\272\321\203\320\277.xml"'
    )
    decoded = decode_git_quoted_paths(header)
    assert "\\320" not in decoded
    assert "ЗаказПокуп.xml" in decoded
    assert decoded.startswith("diff --git a/")


def test_get_file_diff_cyrillic_path_readable(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    path = "Documents/ЗаказПокуп.xml"
    h1 = _commit_file(repo, path, "<a/>", "base")
    h2 = _commit_file(repo, path, "<b/>", "change")
    diff = get_file_diff(repo, h1, h2, path)
    assert "\\320" not in diff
    assert "ЗаказПокуп.xml" in diff
    assert "+<b/>" in diff.replace("\r", "")


def test_list_changed_files_and_diff(tmp_path: Path):
    repo = _init_repo(tmp_path)
    h1 = _commit_file(repo, "Catalogs/Foo.xml", "<a/>", "base")
    h2 = _commit_file(repo, "Catalogs/Foo.xml", "<b/>", "change foo")
    _commit_file(repo, "README.md", "docs", "docs")

    files = list_changed_files(repo, h1, h2)
    assert files == ["Catalogs/Foo.xml"]

    # With pathspec limiting to Catalogs (h1..HEAD includes Foo change + README)
    files2 = list_changed_files(repo, h1, "HEAD", pathspec=["Catalogs"])
    assert "Catalogs/Foo.xml" in files2
    assert "README.md" not in files2

    diff = get_file_diff(repo, h1, h2, "Catalogs/Foo.xml")
    assert "-<a/>" in diff or "-<a/>" in diff.replace("\r", "")
    assert "+<b/>" in diff or "+<b/>" in diff.replace("\r", "")


def test_dump_prefix_filtering(tmp_path: Path):
    repo = _init_repo(tmp_path)
    h1 = _commit_file(repo, "src/cf/Catalogs/X.xml", "old", "base")
    h2 = _commit_file(repo, "src/cf/Catalogs/X.xml", "new", "upd")
    _commit_file(repo, "docs/note.txt", "n", "note")

    files = list_changed_files(repo, h1, h2, dump_prefix="src/cf/")
    assert files == ["src/cf/Catalogs/X.xml"]


def test_export_and_prepare_changes(tmp_path: Path):
    repo = _init_repo(tmp_path)
    h1 = _commit_file(repo, "src/cf/Catalogs/X.xml", "old-content", "base")
    h2 = _commit_file(repo, "src/cf/Catalogs/X.xml", "new-content", "upd")

    staging = tmp_path / "staging"
    result = export_changes_tree(
        repo,
        h2,
        staging,
        ["src/cf/Catalogs/X.xml"],
        dump_prefix="src/cf/",
    )
    assert result.exported == 1
    out = staging / "Catalogs" / "X.xml"
    assert out.is_file()
    assert out.read_text(encoding="utf-8") == "new-content"

    prepared = prepare_changes_from_git(
        repo,
        h1,
        h2,
        dump_prefix="src/cf/",
        staging_dir=tmp_path / "staging2",
    )
    assert prepared.exported == 1
    assert (prepared.staging_dir / "Catalogs" / "X.xml").read_text(encoding="utf-8") == "new-content"

    parent = commit_parent(repo, h2)
    assert parent == h1


def test_range_for_commit(tmp_path: Path):
    from cfe_tools.git_staging import range_for_commit, resolve_commit

    repo = _init_repo(tmp_path)
    h1 = _commit_file(repo, "a.txt", "1", "first")
    h2 = _commit_file(repo, "a.txt", "2", "second")
    short = h2[:7]
    assert resolve_commit(repo, short) == h2
    frm, to = range_for_commit(repo, short)
    assert to == h2
    assert frm == h1


def test_prepare_empty_range_raises(tmp_path: Path):
    repo = _init_repo(tmp_path)
    h = _commit_file(repo, "a.txt", "x", "only")
    with pytest.raises(GitError, match="No changed files"):
        prepare_changes_from_git(repo, h, h)


def test_prepare_pair_from_git(tmp_path: Path):
    import shutil

    from cfe_tools.git_staging import prepare_pair_from_git
    from cfe_tools.inventory import build_inventory

    repo = _init_repo(tmp_path)
    _commit_file(repo, "src/cf/Configuration.xml", "<cfg/>", "cfg")
    h_base = _commit_file(repo, "src/cf/Catalogs/X.xml", "old", "base")
    h_new = _commit_file(repo, "src/cf/Catalogs/X.xml", "new", "change")

    pair = prepare_pair_from_git(repo, h_base, h_new, dump_prefix="src/cf/")
    assert pair.config_from_git
    assert (pair.config_dir / "Catalogs" / "X.xml").read_text(encoding="utf-8") == "old"
    assert (pair.config_dir / "Configuration.xml").is_file()
    assert (pair.changes.staging_dir / "Catalogs" / "X.xml").read_text(encoding="utf-8") == "new"
    inv = build_inventory(pair.config_dir, pair.changes.staging_dir)
    assert inv.changed_files

    # Override: use already exported config dir
    override = tmp_path / "override-cfg"
    shutil.copytree(pair.config_dir, override)
    pair2 = prepare_pair_from_git(
        repo,
        h_base,
        h_new,
        dump_prefix="src/cf/",
        config_dir=override,
        changes_dir=tmp_path / "ch-out",
    )
    assert not pair2.config_from_git
    assert pair2.config_dir == override.resolve()

    for d in pair.temp_dirs:
        shutil.rmtree(d, ignore_errors=True)


def test_map_repo_paths_to_objects():
    refs, unmapped = map_repo_paths_to_objects(
        [
            "src/cf/Catalogs/Тест/Ext/ManagerModule.bsl",
            "README.md",
            "src/cf/Documents/Doc1.xml",
        ],
        dump_prefix="src/cf/",
    )
    specs = {r.borrow_spec for r in refs}
    assert "Catalog.Тест" in specs
    assert "Document.Doc1" in specs
    assert any("README" in u for u in unmapped)


def test_map_form_path():
    refs, _ = map_repo_paths_to_objects(
        ["Catalogs/Товар/Forms/ФормаЭлемента/Ext/Form/Module.bsl"],
    )
    assert any(r.form_name == "ФормаЭлемента" for r in refs)


def test_export_rejects_path_traversal(tmp_path: Path):
    repo = _init_repo(tmp_path)
    h = _commit_file(repo, "Catalogs/Safe.xml", "ok", "base")
    # Craft a tree path that would escape staging if joined naively
    staging = tmp_path / "staging"
    result = export_changes_tree(
        repo,
        h,
        staging,
        ["Catalogs/../../outside.txt", "Catalogs/Safe.xml"],
        dump_prefix="",
    )
    assert result.exported == 1
    assert (staging / "Catalogs" / "Safe.xml").is_file()
    assert not (tmp_path / "outside.txt").exists()
    assert any("unsafe" in w.lower() or "outside" in w.lower() for w in result.warnings)
