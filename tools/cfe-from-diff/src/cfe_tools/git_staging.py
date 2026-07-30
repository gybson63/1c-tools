"""Git helpers: own commits, changed files, diffs, and changes staging."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cfe_tools.cancel import CancelledError, is_cancelled, set_kill_callback
from cfe_tools.cancel import check as cancel_check

if TYPE_CHECKING:
    from cfe_tools.inventory import ObjectRef

ProgressCallback = Callable[[str], None]

# Git C-quoted string with octal bytes, e.g. "Documents/\320\227\320\260\320\272..."
_GIT_C_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_GIT_SIMPLE_ESCAPES = {
    "a": 7,
    "b": 8,
    "t": 9,
    "n": 10,
    "v": 11,
    "f": 12,
    "r": 13,
    '"': 34,
    "\\": 92,
}


class GitError(Exception):
    """Raised when a git invocation fails or the repo is invalid."""


def decode_git_c_quoted(inner: str) -> str:
    """Decode the inside of a git C-quoted string (octal escapes → UTF-8 text)."""
    raw = bytearray()
    i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch != "\\":
            raw.extend(ch.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= n:
            raw.append(ord("\\"))
            break
        esc = inner[i]
        if esc in "01234567":
            j = i
            while j < n and j < i + 3 and inner[j] in "01234567":
                j += 1
            raw.append(int(inner[i:j], 8) & 0xFF)
            i = j
            continue
        if esc in _GIT_SIMPLE_ESCAPES:
            raw.append(_GIT_SIMPLE_ESCAPES[esc])
            i += 1
            continue
        raw.extend(esc.encode("utf-8"))
        i += 1
    return raw.decode("utf-8", errors="replace")


def decode_git_quoted_paths(text: str) -> str:
    """Unquote git path strings like ``\"a/...\\320\\227...\"`` into readable UTF-8."""

    def _repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "\\" not in inner:
            return match.group(0)
        return decode_git_c_quoted(inner)

    return _GIT_C_QUOTED_RE.sub(_repl, text)


def _subprocess_hidden_kwargs() -> dict:
    """Avoid flashing/lingering console windows for console-subsystem tools on Windows."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def _run_cancellable(
    cmd: list[str],
    *,
    poll_s: float = 0.2,
) -> subprocess.CompletedProcess[str]:
    """Run a long subprocess; kill it if cancel is requested."""
    cancel_check()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_subprocess_hidden_kwargs(),
    )

    def _kill() -> None:
        if proc.poll() is None:
            proc.kill()

    set_kill_callback(_kill)
    try:
        while proc.poll() is None:
            if is_cancelled():
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)
                raise CancelledError("Операция отменена")
            time.sleep(poll_s)
        stdout, stderr = proc.communicate()
    finally:
        set_kill_callback(None)
    return subprocess.CompletedProcess(cmd, proc.returncode or 0, stdout or "", stderr or "")


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


@dataclass
class GitPairResult:
    """Base config (DiffFrom) + changes staging (DiffTo) prepared from one git repo."""

    config_dir: Path
    changes: StagingResult
    config_from_git: bool = True
    temp_dirs: list[Path] = field(default_factory=list)


def _run_git(
    repo: str | Path,
    args: Sequence[str],
    *,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    # quotepath=false → Cyrillic paths as UTF-8, not \320\227...
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=false", *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
        **_subprocess_hidden_kwargs(),
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


def find_git_root(start: str | Path) -> Path:
    """Walk up from *start* until ``.git`` is found; return work-tree root."""
    path = Path(start).resolve()
    if not path.is_dir():
        raise GitError(f"Path not found: {path}")
    cur = path
    while True:
        if (cur / ".git").exists():
            proc = _run_git(cur, ["rev-parse", "--show-toplevel"], check=False)
            top = (proc.stdout or "").strip()
            if proc.returncode == 0 and top:
                return Path(top).resolve()
            raise GitError(f"Found .git at {cur}, but cannot resolve git work tree")
        parent = cur.parent
        if parent == cur:
            raise GitError(f"Git-репозиторий не найден выше каталога: {path}")
        cur = parent


def resolve_cf_location(cf_path: str | Path) -> tuple[Path, str]:
    """Map ``Configuration.xml`` (or its dump folder) to ``(git_root, dump_prefix)``.

    *cf_path* must be the ``Configuration.xml`` file of the hierarchical CF dump,
    or (for compatibility) the dump directory that contains that file.

    *dump_prefix* is the dump folder relative to the git root (posix, no trailing
    slash), or empty when the dump is at the repo root.
    """
    path = Path(cf_path).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        raise GitError(f"Путь недоступен: {cf_path}") from exc

    if path.is_file():
        if path.name.lower() != "configuration.xml":
            raise GitError(
                f"Нужен файл Configuration.xml, выбран «{path.name}». "
                "Укажите файл выгрузки основной конфигурации, не другой файл."
            )
        cf = path.parent
    elif path.is_dir():
        cfg = path / "Configuration.xml"
        if not cfg.is_file():
            raise GitError(
                "Укажите файл Configuration.xml выгрузки CF (не каталог репозитория). "
                f"В «{path}» файл Configuration.xml не найден."
            )
        cf = path
    else:
        raise GitError(
            f"Файл Configuration.xml не найден: {path}. Выберите файл Configuration.xml из каталога выгрузки CF."
        )

    root = find_git_root(cf)
    try:
        rel = cf.relative_to(root)
    except ValueError as exc:
        raise GitError(f"Каталог CF {cf} не внутри репозитория {root}") from exc
    prefix = "" if rel == Path(".") else rel.as_posix()
    return root, prefix


def get_git_identity(repo: str | Path) -> tuple[str, str]:
    """Return (user.name, user.email) for the repo (local or global)."""
    repo = assert_git_repo(repo)
    name = _run_git(repo, ["config", "user.name"], check=False).stdout.strip()
    email = _run_git(repo, ["config", "user.email"], check=False).stdout.strip()
    if not name and not email:
        raise GitError("git user.name / user.email are not configured. Set them so «own commits» can be filtered.")
    return name, email


def commit_is_mine(
    commit: CommitInfo,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
) -> bool:
    """True if commit author matches git identity (email OR name, case-insensitive)."""
    email = (author_email or "").strip()
    name = (author_name or "").strip()
    if not email and not name:
        return False
    email_ok = bool(email) and commit.author_email.lower() == email.lower()
    name_ok = bool(name) and commit.author_name.lower() == name.lower()
    return email_ok or name_ok


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


def list_commits(
    repo: str | Path,
    *,
    max_count: int = 100,
    own_only: bool = False,
    author_name: str | None = None,
    author_email: str | None = None,
) -> list[CommitInfo]:
    """List commits on the current branch; optionally filter by git identity."""
    repo = assert_git_repo(repo)
    if own_only and author_name is None and author_email is None:
        author_name, author_email = get_git_identity(repo)

    sep = "\x01"
    # Use git's %x01 escapes — more reliable than embedding SOH in the argv on Windows
    pretty = "%H%x01%h%x01%s%x01%an%x01%ae%x01%aI"
    # When filtering «own», take a wider window then match email OR name
    fetch_count = max_count * 5 if own_only else max_count
    args = ["log", f"--max-count={fetch_count}", f"--pretty=format:{pretty}"]
    # Do not pass --author to git: email in config often differs from history;
    # filter in Python with commit_is_mine (email OR name).

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
        info = CommitInfo(
            hash=h,
            short_hash=short,
            subject=subject,
            author_name=an,
            author_email=ae,
            author_date=date,
        )
        if own_only and not commit_is_mine(info, author_name=author_name, author_email=author_email):
            continue
        commits.append(info)
        if len(commits) >= max_count:
            break
    return commits


def list_own_commits(
    repo: str | Path,
    *,
    max_count: int = 100,
    author_name: str | None = None,
    author_email: str | None = None,
) -> list[CommitInfo]:
    """List commits on the current branch by the configured git identity."""
    return list_commits(
        repo,
        max_count=max_count,
        own_only=True,
        author_name=author_name,
        author_email=author_email,
    )


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
    return decode_git_quoted_paths(proc.stdout or "")


def resolve_commit(repo: str | Path, rev: str) -> str:
    """Resolve a revision (full/short hash, tag, HEAD, …) to a full commit hash."""
    repo = assert_git_repo(repo)
    rev = rev.strip()
    if not rev:
        raise GitError("Empty revision")
    proc = _run_git(repo, ["rev-parse", "--verify", f"{rev}^{{commit}}"])
    return proc.stdout.strip()


def commit_parent(repo: str | Path, commit: str) -> str:
    """Return first parent of commit (commit~1)."""
    repo = assert_git_repo(repo)
    commit = resolve_commit(repo, commit)
    proc = _run_git(repo, ["rev-parse", f"{commit}^"], check=False)
    if proc.returncode != 0:
        raise GitError(
            f"Commit {commit[:12]} has no parent (root commit). Specify Diff From manually or choose another commit."
        )
    return proc.stdout.strip()


def range_for_commit(repo: str | Path, commit: str) -> tuple[str, str]:
    """Return (parent, commit) for a single commit id — changes introduced by that commit."""
    to_rev = resolve_commit(repo, commit)
    from_rev = commit_parent(repo, to_rev)
    return from_rev, to_rev


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
        **_subprocess_hidden_kwargs(),
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

    staging_resolved = staging.resolve()
    for rel in rel_paths:
        rel_posix = rel.replace("\\", "/")
        dump_rel = strip_dump_prefix(rel_posix, prefix)
        if not dump_rel.strip():
            continue
        parts = [p for p in dump_rel.split("/") if p and p != "."]
        if not parts or any(p == ".." for p in parts):
            warnings.append(f"Skip unsafe path: {dump_rel}")
            continue
        dest = staging.joinpath(*parts)
        try:
            if not dest.resolve().is_relative_to(staging_resolved):
                warnings.append(f"Skip path outside staging: {dump_rel}")
                continue
        except OSError:
            warnings.append(f"Skip unresolvable path: {dump_rel}")
            continue
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


def export_tree_at_revision(
    repo: str | Path,
    rev: str,
    dest_dir: str | Path,
    *,
    dump_prefix: str | None = None,
) -> Path:
    """
    Export hierarchical dump tree at ``rev`` into ``dest_dir`` via ``git archive``.

    If DumpPrefix is set, only that subtree is exported and lands at the root of dest
    (so dest looks like a Designer dump: Catalogs/, Configuration.xml, …).
    """
    repo = assert_git_repo(repo)
    dest = Path(dest_dir)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    prefix = normalize_dump_prefix(dump_prefix).rstrip("/")
    treeish = f"{rev}:{prefix}" if prefix else rev

    if prefix:
        probe = _run_git(repo, ["ls-tree", "-d", "--name-only", rev, "--", prefix], check=False)
        if probe.returncode != 0 or not (probe.stdout or "").strip():
            # Also accept a blob-less path that is a tree via ls-tree without -d
            probe2 = _run_git(repo, ["ls-tree", "--name-only", rev, "--", prefix], check=False)
            if probe2.returncode != 0 or not (probe2.stdout or "").strip():
                raise GitError(
                    f"Cannot export dump at {treeish!r}. "
                    "Check Diff From and DumpPrefix (path to CF dump inside the repo)."
                )
    else:
        probe = _run_git(repo, ["rev-parse", "--verify", f"{rev}^{{commit}}"], check=False)
        if probe.returncode != 0:
            raise GitError(f"Cannot resolve revision {rev!r}")

    cancel_check()
    fd, zip_name = tempfile.mkstemp(prefix="cfe-archive-", suffix=".zip")
    os.close(fd)
    zip_path = Path(zip_name)
    try:
        arch = _run_cancellable(
            [
                "git",
                "-C",
                str(repo),
                "archive",
                "--format=zip",
                "-o",
                str(zip_path),
                treeish,
            ]
        )
        if arch.returncode != 0:
            err = (arch.stderr or arch.stdout or "").strip()
            raise GitError(f"git archive failed for {treeish}: {err}")
        cancel_check()
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
    finally:
        with contextlib.suppress(OSError):
            zip_path.unlink(missing_ok=True)

    return dest.resolve()


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


def prepare_pair_from_git(
    repo: str | Path,
    diff_from: str,
    diff_to: str,
    *,
    dump_prefix: str | None = None,
    pathspec: Sequence[str] | None = None,
    config_dir: str | Path | None = None,
    changes_dir: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> GitPairResult:
    """
    Prepare both sides from one git repository:

    - config = full dump tree at DiffFrom (or use existing config_dir override)
    - changes = ACMR files at DiffTo
    """
    temp_dirs: list[Path] = []
    cancel_check()

    def progress(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    try:
        use_temp_config = config_dir is None or str(config_dir).strip() == ""
        if use_temp_config:
            cfg = Path(tempfile.mkdtemp(prefix="cfe-config-"))
            temp_dirs.append(cfg)
            progress(f"Выгрузка базы из git ({diff_from})…")
            export_tree_at_revision(repo, diff_from, cfg, dump_prefix=dump_prefix)
            config_from_git = True
        else:
            assert config_dir is not None
            cfg = Path(config_dir).resolve()
            if not cfg.is_dir():
                raise GitError(f"Config override not found: {cfg}")
            config_from_git = False

        cancel_check()
        use_temp_changes = changes_dir is None or str(changes_dir).strip() == ""
        staging_arg: str | Path | None = None if use_temp_changes else changes_dir
        progress(f"Подготовка изменений из git ({diff_from}…{diff_to})…")
        changes = prepare_changes_from_git(
            repo,
            diff_from,
            diff_to,
            dump_prefix=dump_prefix,
            pathspec=pathspec,
            staging_dir=staging_arg,
        )
        if use_temp_changes:
            temp_dirs.append(changes.staging_dir)

        return GitPairResult(
            config_dir=cfg.resolve(),
            changes=changes,
            config_from_git=config_from_git,
            temp_dirs=temp_dirs,
        )
    except Exception:
        for d in temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        raise


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
