"""Validation of 1C extension name / NamePrefix identifiers."""

from __future__ import annotations

import pytest

from cfe_tools.orchestrator import is_valid_1c_identifier, validate_extension_names


def test_valid_identifiers() -> None:
    assert is_valid_1c_identifier("K7_20646")
    assert is_valid_1c_identifier("K7_20646_")
    assert is_valid_1c_identifier("_Ext")
    assert is_valid_1c_identifier("Расширение1")


def test_hyphen_rejected() -> None:
    assert not is_valid_1c_identifier("K7-20646")
    with pytest.raises(ValueError, match="K7-20646"):
        validate_extension_names("K7-20646")
    with pytest.raises(ValueError, match="префикс"):
        validate_extension_names("K7_20646", "K7-20646_")


def test_default_prefix_from_name() -> None:
    validate_extension_names("K7_20646")
    validate_extension_names("K7_20646", "")
