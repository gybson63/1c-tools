"""Git helpers: own commits, changed files, diffs, and changes staging."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cfe_tools.inventory import ObjectRef


class GitError(Exception):
    """Raised when a git invocation fails or the repo is invalid."""


@dataclass(frozen=True)
class CommitInfo:
    """One commit for GUI lists."""

    hash: str
    short_hash: str
    subject: str
    author_name: str
    author_email: str
    author_date: str  # ISO-like from git %aI

    @property
    def label(self) -> str:
        return f"{self.short_hash}  {self.subject}  ({self.author_date})"


@dataclass
class StagingResult:
    staging_dir: Path
    exported: int
    repo_paths: list[str]
    dump_paths: list[str]
    warnings: list[str]


def _run_git(
    repo: str | Path,
    args: Sequence[str],
    *,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo), *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
    )
    if check and proc.returncode != 0:
        err = (proc.stderr or b"" if not text else proc.stderr) or ""
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {err.strip()}")
    return proc


def assert_git_repo(repo: str | Path) -> Path:
    path = Path(repo).resolve()
    if not path.is_dir():
        raise GitError(f"Git repo not found: {path}")
    proc = _run_git(path, ["rev-parse", "--is-inside-work-tree"], check=False)
    if proc.returncode != 0 or (proc.stdout or "").strip() != "true":
        raise GitError(f"Not a git repository: {path}")
    return path


def get_git_identity(repo: str | Path) -> tuple[str, str]:
    """Return (user.name, user.email) for the repo (local or global)."""
    repo = assert_git_repo(repo)
    name = _run_git(repo, ["config", "user.name"], check=False).stdout.strip()
    email = _run_git(repo, ["config", "user.email"], check=False).stdout.strip()
    if not name and not email:
        raise GitError("git user.name / user.email are not configured. Set them so «own commits» can be filtered.")
    return name, email


def normalize_dump_prefix(prefix: str | None) -> str:
    if not prefix:
        return ""
    p = prefix.replace("\\", "/").strip("/")
    return f"{p}/" if p else ""


def strip_dump_prefix(rel_path: str, dump_prefix: str | None) -> str:
    """Strip DumpPrefix from a repo-relative path (case-insensitive)."""
    rel = rel_path.replace("\\", "/")
    prefix = normalize_dump_prefix(dump_prefix)
    if prefix and rel.lower().startswith(prefix.lower()):
        return rel[len(prefix) :]
    return rel


def list_own_commits(
    repo: str | Path,
    *,
    max_count: int = 100,
    author_name: str | None = None,
    author_email: str | None = None,
) -> list[CommitInfo]:
    """List commits on the current branch by the configured git identity."""
    repo = assert_git_repo(repo)
    if author_name is None and author_email is None:
        author_name, author_email = get_git_identity(repo)

    # Format: hash<SOH>short<SOH>subject<SOH>name<SOH>email<SOH>date
    sep = "\x01"
    pretty = f"%H{sep}%h{sep}%s{sep}%an{sep}%ae{sep}%aI"
    args = ["log", f"--max-count={max_count}", f"--pretty=format:{pretty}"]
    # git --author is a regex/substring; prefer email, else name
    author_filter = author_email or author_name or ""
    if author_filter:
        args.append(f"--author={author_filter}")

    proc = _run_git(repo, args)
    commits: list[CommitInfo] = []
    for line in (proc.stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split(sep)
        if len(parts) < 6:
            continue
        h, short, subject, an, ae, date = (
            parts[0],
            parts[1],
            parts[2],
            parts[3],
            parts[4],
            parts[5],
        )
        # Tighten: exact email match when email is known
        if author_email and ae.lower() != author_email.lower():
            continue
        if not author_email and author_name and an != author_name:
            continue
        commits.append(
            CommitInfo(
                hash=h,
                short_hash=short,
                subject=subject,
                author_name=an,
                author_email=ae,
                author_date=date,
            )
        )
    return commits


def list_changed_files(
    repo: str | Path,
    diff_from: str,
    diff_to: str,
    *,
    dump_prefix: str | None = None,
    pathspec: Sequence[str] | None = None,
) -> list[str]:
    """Return repo-relative paths changed between From and To (ACMR only)."""
    repo = assert_git_repo(repo)
    specs: list[str] = []
    prefix = normalize_dump_prefix(dump_prefix)
    if prefix:
        specs.append(prefix)
    if pathspec:
        specs.extend(pathspec)

    args = [
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        diff_from,
        diff_to,
    ]
    if specs:
        args.append("--")
        args.extend(specs)

    proc = _run_git(repo, args)
    raw = proc.stdout or ""
    if not raw:
        return []
    return [p for p in raw.split("\0") if p]


def get_file_diff(
    repo: str | Path,
    diff_from: str,
    diff_to: str,
    rel_path: str,
    *,
    context: int = 3,
) -> str:
    """Unified diff for one file between From and To."""
    repo = assert_git_repo(repo)
    rel = rel_path.replace("\\", "/")
    args = [
        "diff",
        f"--unified={context}",
        "--no-color",
        diff_from,
        diff_to,
        "--",
        rel,
    ]
    proc = _run_git(repo, args, check=False)
    # Missing path / binary / identical → empty or non-zero is OK for display
    return proc.stdout or ""


def commit_parent(repo: str | Path, commit: str) -> str:
    """Return first parent of commit (commit~1)."""
    repo = assert_git_repo(repo)
    proc = _run_git(repo, ["rev-parse", f"{commit}^"])
    return proc.stdout.strip()


def export_blob_to_file(repo: str | Path, object_spec: str, dest_path: str | Path) -> bool:
    """Export git blob (e.g. HEAD:path/to/file) to dest_path. Binary-safe."""
    repo = assert_git_repo(repo)
    dest = Path(dest_path)
    rev_proc = _run_git(repo, ["rev-parse", object_spec], check=False)
    if rev_proc.returncode != 0 or not (rev_proc.stdout or "").strip():
        return False
    blob_hash = rev_proc.stdout.strip()

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write binary blob without going through text decoding
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", blob_hash],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return False
    dest.write_bytes(proc.stdout)
    return True


def export_changes_tree(
    repo: str | Path,
    diff_to: str,
    staging_dir: str | Path,
    rel_paths: Iterable[str],
    *,
    dump_prefix: str | None = None,
) -> StagingResult:
    """
    Wipe/recreate staging_dir and export file contents at DiffTo.

    DumpPrefix is stripped from paths written under staging so they match
    the hierarchical dump layout expected by --config.
    """
    repo = assert_git_repo(repo)
    staging = Path(staging_dir)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    prefix = normalize_dump_prefix(dump_prefix)
    warnings: list[str] = []
    repo_paths: list[str] = []
    dump_paths: list[str] = []
    exported = 0

    for rel in rel_paths:
        rel_posix = rel.replace("\\", "/")
        dump_rel = strip_dump_prefix(rel_posix, prefix)
        if not dump_rel.strip():
            continue
        dest = staging / Path(*dump_rel.split("/"))
        ok = export_blob_to_file(repo, f"{diff_to}:{rel_posix}", dest)
        if not ok:
            warnings.append(f"Skip (missing in {diff_to}): {rel_posix}")
            continue
        repo_paths.append(rel_posix)
        dump_paths.append(dump_rel)
        exported += 1

    return StagingResult(
        staging_dir=staging.resolve(),
        exported=exported,
        repo_paths=repo_paths,
        dump_paths=dump_paths,
        warnings=warnings,
    )


def prepare_changes_from_git(
    repo: str | Path,
    diff_from: str,
    diff_to: str,
    *,
    dump_prefix: str | None = None,
    pathspec: Sequence[str] | None = None,
    staging_dir: str | Path | None = None,
) -> StagingResult:
    """List ACMR changes and export DiffTo blobs into a staging directory."""
    files = list_changed_files(
        repo,
        diff_from,
        diff_to,
        dump_prefix=dump_prefix,
        pathspec=pathspec,
    )
    if not files:
        raise GitError(f"No changed files in range {diff_from}..{diff_to}")

    use_temp = staging_dir is None or str(staging_dir).strip() == ""
    if use_temp:
        staging = Path(tempfile.mkdtemp(prefix="cfe-changes-"))
    else:
        assert staging_dir is not None
        staging = Path(staging_dir)

    result = export_changes_tree(
        repo,
        diff_to,
        staging,
        files,
        dump_prefix=dump_prefix,
    )
    if result.exported == 0:
        raise GitError("Failed to export any files into staging")
    return result


def map_repo_paths_to_objects(
    repo_paths: Sequence[str],
    *,
    dump_prefix: str | None = None,
) -> tuple[list[ObjectRef], list[str]]:
    """Map git paths to ObjectRef via inventory.map_path_to_object (after prefix strip)."""
    from cfe_tools.inventory import map_path_to_object

    seen: dict[str, ObjectRef] = {}
    unmapped: list[str] = []
    for rel in repo_paths:
        dump_rel = strip_dump_prefix(rel, dump_prefix)
        ref = map_path_to_object(dump_rel)
        if ref is None:
            unmapped.append(rel)
            continue
        seen[ref.key] = ref
    return list(seen.values()), unmapped
