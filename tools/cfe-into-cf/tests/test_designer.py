"""Tests for Designer helpers (no real 1cv8)."""

from __future__ import annotations

from cfe_into_cf.designer import _redact_args, decode_designer_output


def test_redact_passwords() -> None:
    args = [
        "1cv8",
        "DESIGNER",
        "/F",
        "C:\\ib",
        "/N",
        "Admin",
        "/P",
        "secret",
        "/ConfigurationRepositoryP",
        "repo-secret",
    ]
    redacted = _redact_args(args)
    assert "secret" not in redacted
    assert "repo-secret" not in redacted
    assert redacted.count("***") == 2


def test_decode_utf8() -> None:
    assert decode_designer_output("привет".encode()) == "привет"
