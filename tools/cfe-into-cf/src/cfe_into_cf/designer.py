"""Обёртка пакетного режима 1cv8 DESIGNER."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cfe_into_cf.cancel import CancelledError, is_cancelled, set_kill_callback
from cfe_into_cf.cancel import check as cancel_check

ProgressCallback = Callable[[str], None]

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


class DesignerError(Exception):
    """Raised when a Designer batch invocation fails."""


@dataclass
class IbConnection:
    """Infobase connection for Designer batch mode."""

    ib_path: str | None = None
    ib_server: str | None = None
    ib_ref: str | None = None
    user: str | None = None
    password: str | None = None


@dataclass
class RepoConnection:
    """Configuration repository (хранилище) credentials."""

    path: str
    user: str
    password: str = ""


@dataclass
class DesignerConfig:
    """Common Designer session settings."""

    connection: IbConnection
    v8_path: str | None = None
    work_dir: Path | None = None
    repo: RepoConnection | None = None


@dataclass
class DesignerResult:
    returncode: int
    log_text: str
    command: list[str] = field(default_factory=list)


def find_1cv8(explicit: str | None = None) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise DesignerError(f"1cv8 not found: {explicit}")
        return str(path.resolve())

    which = shutil.which("1cv8") or shutil.which("1cv8.exe")
    if which:
        return which

    prog = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    root = Path(prog) / "1cv8"
    if root.is_dir():
        candidates = sorted(root.glob(r"*\bin\1cv8.exe"), reverse=True)
        if candidates:
            return str(candidates[0])
    raise DesignerError(
        "1cv8 not found. Pass --1cv8 or add it to PATH "
        r"(typical: C:\Program Files\1cv8\<version>\bin\1cv8.exe)"
    )


def _redact_args(args: Sequence[str]) -> list[str]:
    """Mask passwords that follow /P and /ConfigurationRepositoryP."""
    out: list[str] = []
    redact_next = False
    for a in args:
        if redact_next:
            out.append("***")
            redact_next = False
            continue
        low = a.casefold()
        if low in {"/p", "/configurationrepositoryp"}:
            out.append(a)
            redact_next = True
            continue
        out.append(a)
    if redact_next:
        out.append("***")
    return out


def _windows_code_page_name(get_cp: Callable[[], int]) -> str | None:
    try:
        cp = int(get_cp())
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if cp <= 0:
        return None
    return f"cp{cp}"


def _candidate_encodings() -> list[str]:
    ordered: list[str] = []
    if os.name == "nt":
        try:
            import ctypes

            for getter in (ctypes.windll.kernel32.GetOEMCP, ctypes.windll.kernel32.GetACP):
                name = _windows_code_page_name(getter)
                if name and name not in ordered:
                    ordered.append(name)
        except (AttributeError, OSError):
            pass
        for fallback in ("cp866", "cp1251"):
            if fallback not in ordered:
                ordered.append(fallback)
    ordered.append("utf-8")
    return ordered


def decode_designer_output(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if not data:
        return ""
    try:
        as_utf8 = data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        if not any(b >= 0x80 for b in data) or _CYRILLIC_RE.search(as_utf8) is not None:
            return as_utf8

    best_text = ""
    best_key: tuple[int, int, int] | None = None
    for index, enc in enumerate(_candidate_encodings()):
        try:
            text = data.decode(enc)
            replaced = 0
        except UnicodeDecodeError:
            try:
                text = data.decode(enc, errors="replace")
            except LookupError:
                continue
            replaced = text.count("\ufffd")
        except LookupError:
            continue
        cyrillic = len(_CYRILLIC_RE.findall(text))
        key = (-replaced, cyrillic, -index)
        if best_key is None or key > best_key:
            best_key = key
            best_text = text
    return best_text


def _subprocess_hidden_kwargs() -> dict:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def _ib_args(conn: IbConnection) -> list[str]:
    args: list[str] = []
    if conn.ib_path:
        args.extend(["/F", str(Path(conn.ib_path).resolve())])
    elif conn.ib_server and conn.ib_ref:
        args.extend(["/S", f"{conn.ib_server}\\{conn.ib_ref}"])
    else:
        raise DesignerError("Укажите --ib-path или пару --ib-server и --ib-ref")
    if conn.user:
        args.extend(["/N", conn.user])
    if conn.password is not None and conn.password != "":
        args.extend(["/P", conn.password])
    return args


def _repo_args(repo: RepoConnection | None) -> list[str]:
    if repo is None:
        return []
    return [
        "/ConfigurationRepositoryF",
        repo.path,
        "/ConfigurationRepositoryN",
        repo.user,
        "/ConfigurationRepositoryP",
        repo.password,
    ]


def run_designer(
    cfg: DesignerConfig,
    batch_args: Sequence[str],
    *,
    check: bool = True,
    on_progress: ProgressCallback | None = None,
) -> DesignerResult:
    """Run ``1cv8 DESIGNER`` with common IB/repo flags and ``/Out`` log."""
    cancel_check()
    v8 = find_1cv8(cfg.v8_path)
    work = cfg.work_dir or Path.cwd()
    work.mkdir(parents=True, exist_ok=True)
    log_path = work / f"designer-{int(time.time() * 1000)}.log"

    cmd = [
        v8,
        "DESIGNER",
        *_ib_args(cfg.connection),
        *_repo_args(cfg.repo),
        "/DisableStartupDialogs",
        "/DisableStartupMessages",
        "/Out",
        str(log_path),
        *batch_args,
    ]

    safe = " ".join(_redact_args(cmd))
    if on_progress:
        on_progress(f"Designer: {safe}")
    print(f"[designer] {safe}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
            time.sleep(0.2)
        stdout_b, stderr_b = proc.communicate()
    finally:
        set_kill_callback(None)

    log_text = ""
    if log_path.is_file():
        raw = log_path.read_bytes()
        log_text = decode_designer_output(raw)
    stdout = decode_designer_output(stdout_b)
    stderr = decode_designer_output(stderr_b)
    combined = "\n".join(x for x in (log_text, stdout, stderr) if x).strip()

    result = DesignerResult(returncode=proc.returncode or 0, log_text=combined, command=list(cmd))
    if combined:
        print(combined)
    if check and result.returncode != 0:
        raise DesignerError(
            f"Designer failed ({result.returncode}): {safe}\nlog:\n{combined}"
        )
    return result


def dump_config_to_files(
    cfg: DesignerConfig,
    target_dir: Path,
    *,
    extension: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> DesignerResult:
    target_dir.mkdir(parents=True, exist_ok=True)
    args = ["/DumpConfigToFiles", str(target_dir), "-Format", "Hierarchical"]
    if extension:
        args.extend(["-Extension", extension])
    label = f"расширение «{extension}»" if extension else "основная конфигурация"
    if on_progress:
        on_progress(f"Выгрузка в файлы: {label}")
    return run_designer(cfg, args, on_progress=on_progress)


def load_config_from_files(
    cfg: DesignerConfig,
    source_dir: Path,
    *,
    list_file: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> DesignerResult:
    args = ["/LoadConfigFromFiles", str(source_dir), "-Format", "Hierarchical"]
    if list_file is not None:
        args.extend(["-listFile", str(list_file)])
    if on_progress:
        on_progress("Загрузка конфигурации из файлов")
    return run_designer(cfg, args, on_progress=on_progress)


def update_db_cfg(
    cfg: DesignerConfig,
    *,
    on_progress: ProgressCallback | None = None,
) -> DesignerResult:
    if on_progress:
        on_progress("Обновление конфигурации БД")
    return run_designer(cfg, ["/UpdateDBCfg"], on_progress=on_progress)


def repository_lock(
    cfg: DesignerConfig,
    objects_file: Path,
    *,
    revised: bool = True,
    on_progress: ProgressCallback | None = None,
) -> DesignerResult:
    if cfg.repo is None:
        raise DesignerError("Параметры хранилища не заданы (нужны --repo-path / --repo-user)")
    args = ["/ConfigurationRepositoryLock", "-Objects", str(objects_file)]
    if revised:
        args.append("-revised")
    if on_progress:
        on_progress(f"Захват объектов в хранилище: {objects_file.name}")
    return run_designer(cfg, args, on_progress=on_progress)


def repository_commit(
    cfg: DesignerConfig,
    objects_file: Path,
    *,
    comment: str = "",
    keep_locked: bool = False,
    on_progress: ProgressCallback | None = None,
) -> DesignerResult:
    if cfg.repo is None:
        raise DesignerError("Параметры хранилища не заданы")
    args = ["/ConfigurationRepositoryCommit", "-Objects", str(objects_file)]
    if comment:
        args.extend(["-comment", comment])
    if keep_locked:
        args.append("-keepLocked")
    if on_progress:
        on_progress("Помещение объектов в хранилище")
    return run_designer(cfg, args, on_progress=on_progress)


def repository_unlock(
    cfg: DesignerConfig,
    objects_file: Path,
    *,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> DesignerResult:
    if cfg.repo is None:
        raise DesignerError("Параметры хранилища не заданы")
    args = ["/ConfigurationRepositoryUnLock", "-Objects", str(objects_file)]
    if force:
        args.append("-force")
    if on_progress:
        on_progress("Отмена захвата объектов")
    return run_designer(cfg, args, on_progress=on_progress)
