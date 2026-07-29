"""Build .cfe from extension XML sources using ibcmd (no Designer)."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cfe_tools.cancel import CancelledError, is_cancelled, set_kill_callback
from cfe_tools.cancel import check as cancel_check

ProgressCallback = Callable[[str], None]

# Cyrillic letters — used to score Windows console encodings (OEM/ANSI vs UTF-8).
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LOG_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")
_EXTENSION_ALREADY_EXISTS = (
    "уже существует",
    "already exists",
    "already exist",
)


class IbcmdError(Exception):
    """Raised when an ibcmd invocation fails."""


@dataclass
class IbcmdConfig:
    ib_path: str
    extension_name: str
    extension_src: str
    cfe_path: str
    name_prefix: str
    purpose: str = "customization"  # patch | add-on | customization
    ibcmd: str | None = None
    user: str | None = None
    password: str | None = None


PURPOSE_MAP = {
    "Patch": "patch",
    "Customization": "customization",
    "AddOn": "add-on",
    "patch": "patch",
    "customization": "customization",
    "add-on": "add-on",
    "Add-On": "add-on",
}


def find_ibcmd(explicit: str | None = None) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise IbcmdError(f"ibcmd not found: {explicit}")
        return str(path.resolve())

    which = shutil.which("ibcmd") or shutil.which("ibcmd.exe")
    if which:
        return which

    prog = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    root = Path(prog) / "1cv8"
    if root.is_dir():
        candidates = sorted(root.glob(r"*\bin\ibcmd.exe"), reverse=True)
        if candidates:
            return str(candidates[0])
    raise IbcmdError(
        "ibcmd not found. Pass --ibcmd or add it to PATH "
        r"(typical: C:\Program Files\1cv8\<version>\bin\ibcmd.exe)"
    )


def _conn_args(cfg: IbcmdConfig) -> list[str]:
    args = ["infobase", f"--db-path={cfg.ib_path}"]
    if cfg.user:
        args.append(f"--user={cfg.user}")
    if cfg.password is not None:
        args.append(f"--password={cfg.password}")
    return args


def _redact_args(args: list[str]) -> list[str]:
    """Mask --password=... in logged command lines."""
    out: list[str] = []
    for a in args:
        if a.startswith("--password="):
            out.append("--password=***")
        else:
            out.append(a)
    return out


def _windows_code_page_name(get_cp: Callable[[], int]) -> str | None:
    """Return ``cpNNN`` for a Win32 GetACP/GetOEMCP-style callback, or None."""
    try:
        cp = int(get_cp())
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if cp <= 0:
        return None
    return f"cp{cp}"


def _candidate_encodings() -> list[str]:
    """Order encodings for ibcmd pipe output on the current OS."""
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


def decode_ibcmd_output(data: bytes | str | None) -> str:
    """Decode ibcmd stdout/stderr (OEM/ANSI on Windows, UTF-8 elsewhere)."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if not data:
        return ""

    # Valid UTF-8 ASCII / Cyrillic wins. CP866/CP1251 Russian is almost never valid UTF-8.
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
        # Prefer fewer replacements, more Cyrillic, earlier candidate (OEM before ANSI).
        key = (-replaced, cyrillic, -index)
        if best_key is None or key > best_key:
            best_key = key
            best_text = text
    return best_text


def _subprocess_hidden_kwargs() -> dict:
    """Avoid flashing/lingering console windows for console-subsystem tools on Windows."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def run_ibcmd(ibcmd: str, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [ibcmd, *args]
    print(f"[ibcmd] {' '.join(_redact_args(cmd))}")
    cancel_check()
    # Bytes mode: ibcmd on Windows writes OEM (CP866) / ANSI (CP1251), not UTF-8.
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

    stdout = decode_ibcmd_output(stdout_b)
    stderr = decode_ibcmd_output(stderr_b)
    result = subprocess.CompletedProcess(cmd, proc.returncode or 0, stdout, stderr)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if check and result.returncode != 0:
        safe = " ".join(_redact_args(cmd))
        raise IbcmdError(
            f"ibcmd failed ({result.returncode}): {safe}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _line_has_extension_name(line: str, name: str) -> bool:
    """Match extension name in ibcmd list/info output (avoid Ext vs ExtFoo false positives)."""
    stripped = _LOG_PREFIX_RE.sub("", line.strip())
    if not stripped:
        return False
    if stripped == name or stripped.strip("'\"") == name:
        return True
    if f"--name={name}" in stripped or f"--extension={name}" in stripped:
        return True
    tokens = re.split(r"[\s,;|]+", stripped)
    if name in tokens:
        return True
    return re.search(rf"(?:^|[\s'\"=:]){re.escape(name)}(?:$|[\s'\",;|])", stripped) is not None


def _output_mentions_extension(text: str, name: str) -> bool:
    return any(_line_has_extension_name(line, name) for line in text.splitlines())


def _is_extension_already_exists_message(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in _EXTENSION_ALREADY_EXISTS)


def extension_exists(ibcmd: str, cfg: IbcmdConfig) -> bool:
    """Best-effort check via extension list and extension info."""
    name = cfg.extension_name

    list_proc = run_ibcmd(
        ibcmd,
        [*_conn_args(cfg), "config", "extension", "list"],
        check=False,
    )
    list_text = (list_proc.stdout or "") + (list_proc.stderr or "")
    if list_proc.returncode == 0 and _output_mentions_extension(list_text, name):
        return True

    info_proc = run_ibcmd(
        ibcmd,
        [*_conn_args(cfg), "config", "extension", "info", f"--name={name}"],
        check=False,
    )
    if info_proc.returncode == 0:
        return True
    info_text = (info_proc.stdout or "") + (info_proc.stderr or "")
    return _output_mentions_extension(info_text, name)


def _ensure_extension(
    ibcmd: str,
    cfg: IbcmdConfig,
    purpose: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Create extension in IB when missing; tolerate «already exists» from ibcmd."""
    name = cfg.extension_name

    def progress(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    if extension_exists(ibcmd, cfg):
        print(f"[ibcmd] Extension already exists: {name}")
        progress(f"ibcmd: расширение «{name}» уже есть в ИБ")
        return

    progress(f"ibcmd: создание расширения «{name}»…")
    proc = run_ibcmd(
        ibcmd,
        [
            *_conn_args(cfg),
            "config",
            "extension",
            "create",
            f"--name={name}",
            f"--name-prefix={cfg.name_prefix}",
            f"--purpose={purpose}",
        ],
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0 or _is_extension_already_exists_message(combined):
        if _is_extension_already_exists_message(combined):
            print(f"[ibcmd] Extension already exists: {name}")
            progress(f"ibcmd: расширение «{name}» уже есть в ИБ")
        return
    if extension_exists(ibcmd, cfg):
        print(f"[ibcmd] Extension already exists: {name}")
        progress(f"ibcmd: расширение «{name}» уже есть в ИБ")
        return

    safe = " ".join(
        _redact_args(
            [
                ibcmd,
                *_conn_args(cfg),
                "config",
                "extension",
                "create",
                f"--name={name}",
                f"--name-prefix={cfg.name_prefix}",
                f"--purpose={purpose}",
            ]
        )
    )
    raise IbcmdError(f"ibcmd failed ({proc.returncode}): {safe}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


def build_cfe(cfg: IbcmdConfig, *, on_progress: ProgressCallback | None = None) -> str:
    """Create/import/check/apply/save extension to .cfe. Returns path to .cfe."""

    def progress(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    ibcmd = find_ibcmd(cfg.ibcmd)
    ib_path = Path(cfg.ib_path)
    if not ib_path.exists():
        raise IbcmdError(f"Infobase path not found: {cfg.ib_path}")

    src = Path(cfg.extension_src)
    if not (src / "Configuration.xml").is_file():
        raise IbcmdError(f"Extension Configuration.xml not found in: {src}")

    cfe_path = Path(cfg.cfe_path)
    cfe_path.parent.mkdir(parents=True, exist_ok=True)

    purpose = PURPOSE_MAP.get(cfg.purpose, cfg.purpose.lower())

    cancel_check()
    progress("ibcmd: проверка существования расширения…")
    _ensure_extension(ibcmd, cfg, purpose, on_progress=on_progress)

    cancel_check()
    progress("ibcmd: загрузка XML расширения в ИБ…")
    run_ibcmd(
        ibcmd,
        [
            *_conn_args(cfg),
            "config",
            "import",
            f"--extension={cfg.extension_name}",
            str(src.resolve()),
        ],
    )

    cancel_check()
    progress("ibcmd: проверка конфигурации расширения…")
    run_ibcmd(
        ibcmd,
        [
            *_conn_args(cfg),
            "config",
            "check",
            f"--extension={cfg.extension_name}",
        ],
    )

    cancel_check()
    progress("ibcmd: применение расширения…")
    run_ibcmd(
        ibcmd,
        [
            *_conn_args(cfg),
            "config",
            "apply",
            f"--extension={cfg.extension_name}",
            "--force",
        ],
    )

    cancel_check()
    progress(f"ibcmd: сохранение .cfe → {cfe_path.name}…")
    if cfe_path.is_file():
        cfe_path.unlink()
        print(f"[ibcmd] Overwriting existing file: {cfe_path}")
    run_ibcmd(
        ibcmd,
        [
            *_conn_args(cfg),
            "config",
            "save",
            f"--extension={cfg.extension_name}",
            str(cfe_path.resolve()),
        ],
    )

    if not cfe_path.is_file():
        raise IbcmdError(f"CFE was not created: {cfe_path}")
    print(f"[OK] CFE saved: {cfe_path}")
    progress(f"ibcmd: файл сохранён ({cfe_path})")
    return str(cfe_path.resolve())
