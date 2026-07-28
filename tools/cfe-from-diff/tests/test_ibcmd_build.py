"""Unit tests for ibcmd helpers that do not require a real platform install."""

from __future__ import annotations

from cfe_tools.ibcmd_build import IbcmdConfig, extension_exists


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_extension_exists_exact_token(monkeypatch):
    cfg = IbcmdConfig(
        ib_path="C:/ib",
        extension_name="Ext",
        extension_src=".",
        cfe_path="out.cfe",
        name_prefix="Ext_",
    )

    def fake_run(_ibcmd, _args, _check=False):
        return _Proc(stdout="ExtFoo\nOther\n")

    monkeypatch.setattr("cfe_tools.ibcmd_build.run_ibcmd", fake_run)
    assert extension_exists("ibcmd", cfg) is False

    def fake_run_exact(_ibcmd, _args, _check=False):
        return _Proc(stdout="ExtFoo\nExt\nOther\n")

    monkeypatch.setattr("cfe_tools.ibcmd_build.run_ibcmd", fake_run_exact)
    assert extension_exists("ibcmd", cfg) is True
