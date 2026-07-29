"""Guards against crashes when GUI runs under pythonw (stdout/stderr are None)."""

from __future__ import annotations

import sys


def test_borrow_main_reconfigure_with_none_stdio(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "argv", ["cfe-borrow", "-h"])

    from cfe_tools.vendor.cfe_borrow import main

    try:
        main()
    except SystemExit as exc:
        assert exc.code in (0, None)


def test_ensure_stdio_replaces_none() -> None:
    from cfe_tools.gui_app import _ensure_stdio

    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = None  # type: ignore[assignment]
        sys.stderr = None  # type: ignore[assignment]
        _ensure_stdio()
        assert sys.stdout is not None
        assert sys.stderr is not None
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        print("ok")
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
