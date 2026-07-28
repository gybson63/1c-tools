"""Tests for git staging helpers used by the GUI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cfe_tools.git_staging import (
    GitError,
    commit_parent,
    export_changes_tree,
    get_file_diff,
    list_changed_files,
    list_own_commits,
    map_repo_paths_to_objects,
    normalize_dump_prefix,
    prepare_changes_from_git,
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


def test_prepare_empty_range_raises(tmp_path: Path):
    repo = _init_repo(tmp_path)
    h = _commit_file(repo, "a.txt", "x", "only")
    with pytest.raises(GitError, match="No changed files"):
        prepare_changes_from_git(repo, h, h)


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
