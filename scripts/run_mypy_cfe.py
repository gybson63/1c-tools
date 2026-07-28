"""Run mypy for tools/cfe-from-diff from the repository root."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    pkg = root / "tools" / "cfe-from-diff"
    env = os.environ.copy()
    # Ensure the package is importable the same way as local `cd tools/cfe-from-diff && mypy`
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file=pyproject.toml",
            "--explicit-package-bases",
            "-p",
            "cfe_tools",
        ],
        cwd=pkg,
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
