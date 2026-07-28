"""Build .cfe from extension XML sources using ibcmd (no Designer)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


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


def run_ibcmd(ibcmd: str, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [ibcmd, *args]
    print(f"[ibcmd] {' '.join(_redact_args(cmd))}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)
    if check and proc.returncode != 0:
        safe = " ".join(_redact_args(cmd))
        raise IbcmdError(f"ibcmd failed ({proc.returncode}): {safe}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return proc


def extension_exists(ibcmd: str, cfg: IbcmdConfig) -> bool:
    """Best-effort check via config export attempt or extension list."""
    # ibcmd extension list if available; fall back to False
    proc = run_ibcmd(
        ibcmd,
        [*_conn_args(cfg), "config", "extension", "list"],
        check=False,
    )
    if proc.returncode != 0:
        return False
    text = (proc.stdout or "") + (proc.stderr or "")
    name = cfg.extension_name
    for line in text.splitlines():
        tokens = line.replace(",", " ").split()
        if name in tokens:
            return True
        if line.strip() == name:
            return True
    return False


def build_cfe(cfg: IbcmdConfig) -> str:
    """Create/import/check/apply/save extension to .cfe. Returns path to .cfe."""
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

    if not extension_exists(ibcmd, cfg):
        run_ibcmd(
            ibcmd,
            [
                *_conn_args(cfg),
                "config",
                "extension",
                "create",
                f"--name={cfg.extension_name}",
                f"--name-prefix={cfg.name_prefix}",
                f"--purpose={purpose}",
            ],
        )
    else:
        print(f"[ibcmd] Extension already exists: {cfg.extension_name}")

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

    run_ibcmd(
        ibcmd,
        [
            *_conn_args(cfg),
            "config",
            "check",
            f"--extension={cfg.extension_name}",
        ],
    )

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
    return str(cfe_path.resolve())
