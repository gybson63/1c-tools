"""Unit tests for ibcmd helpers that do not require a real platform install."""

from __future__ import annotations

from cfe_tools.ibcmd_build import (
    IbcmdConfig,
    _ensure_extension,
    _is_extension_already_exists_message,
    _line_has_extension_name,
    decode_ibcmd_output,
    extension_exists,
)

# Avoid depending on the source file encoding on Windows consoles.
_ERR_CREATE = (
    "\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f "
    "\u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u0438\u044f"
)
_ERR_NAME = (
    "\u041d\u0435\u0434\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u043e\u0435 "
    "\u0438\u043c\u044f \u043e\u0431\u044a\u0435\u043a\u0442\u0430"
)
_ERR_SHORT = "\u041e\u0448\u0438\u0431\u043a\u0430"
_ALREADY = "\u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442"


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

    def fake_run(_ibcmd, args, check=False):
        if "list" in args:
            return _Proc(stdout="ExtFoo\nOther\n")
        return _Proc(returncode=1)

    monkeypatch.setattr("cfe_tools.ibcmd_build.run_ibcmd", fake_run)
    assert extension_exists("ibcmd", cfg) is False

    def fake_run_exact(_ibcmd, args, check=False):
        if "list" in args:
            return _Proc(stdout="ExtFoo\nExt\nOther\n")
        return _Proc(returncode=1)

    monkeypatch.setattr("cfe_tools.ibcmd_build.run_ibcmd", fake_run_exact)
    assert extension_exists("ibcmd", cfg) is True


def test_extension_exists_via_info(monkeypatch):
    cfg = IbcmdConfig(
        ib_path="C:/ib",
        extension_name="K7_20624",
        extension_src=".",
        cfe_path="out.cfe",
        name_prefix="K7_20624_",
    )

    def fake_run(_ibcmd, args, check=False):
        if "list" in args:
            return _Proc(returncode=2, stderr="command failed")
        if "info" in args:
            return _Proc(returncode=0, stdout="[INFO] Extension: K7_20624\n")
        return _Proc(returncode=1)

    monkeypatch.setattr("cfe_tools.ibcmd_build.run_ibcmd", fake_run)
    assert extension_exists("ibcmd", cfg) is True


def test_line_has_extension_name_info_prefix() -> None:
    assert _line_has_extension_name("[INFO] Extension: K7_20624", "K7_20624")
    assert not _line_has_extension_name("[INFO] Extension: K7_206241", "K7_20624")


def test_is_extension_already_exists_message() -> None:
    assert _is_extension_already_exists_message("Расширение с таким именем уже существует!")
    assert _is_extension_already_exists_message("Extension already exists")
    assert not _is_extension_already_exists_message("ok")


def test_ensure_extension_tolerates_already_exists(monkeypatch):
    cfg = IbcmdConfig(
        ib_path="C:/ib",
        extension_name="K7_20624",
        extension_src=".",
        cfe_path="out.cfe",
        name_prefix="K7_20624_",
    )
    calls: list[list[str]] = []

    def fake_exists(_ibcmd, _cfg):
        return False

    def fake_run(_ibcmd, args, check=False):
        calls.append(list(args))
        if "create" in args:
            return _Proc(
                returncode=2,
                stdout="[INFO] Создание расширения: 'K7_20624'\n",
                stderr="Расширение с таким именем уже существует!\n",
            )
        return _Proc()

    monkeypatch.setattr("cfe_tools.ibcmd_build.extension_exists", fake_exists)
    monkeypatch.setattr("cfe_tools.ibcmd_build.run_ibcmd", fake_run)

    _ensure_extension("ibcmd", cfg, "customization")
    assert any("create" in call for call in calls)


def test_decode_ibcmd_cp866() -> None:
    assert decode_ibcmd_output(_ERR_CREATE.encode("cp866")) == _ERR_CREATE


def test_decode_ibcmd_cp1251() -> None:
    assert decode_ibcmd_output(_ERR_NAME.encode("cp1251")) == _ERR_NAME


def test_decode_ibcmd_utf8() -> None:
    assert decode_ibcmd_output(_ERR_SHORT.encode("utf-8")) == _ERR_SHORT


def test_decode_ibcmd_empty_and_str() -> None:
    assert decode_ibcmd_output(None) == ""
    assert decode_ibcmd_output(b"") == ""
    assert decode_ibcmd_output(_ALREADY) == _ALREADY
    assert decode_ibcmd_output(b"ASCII ok") == "ASCII ok"
