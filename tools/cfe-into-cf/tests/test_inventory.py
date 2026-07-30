"""Tests for extension inventory and new-objects alert."""

from __future__ import annotations

from pathlib import Path

from cfe_into_cf.inventory import format_new_objects_alert, inventory_extension
from fixtures_builder import build_extension_dump


def test_inventory_classifies_own_and_adopted(tmp_path: Path) -> None:
    ext = build_extension_dump(tmp_path / "ext")
    inv = inventory_extension(ext)
    own_keys = {o.key for o in inv.own_objects}
    adopted_keys = {o.key for o in inv.adopted_objects}
    assert "Catalog.Тст_Новый" in own_keys
    assert "Catalog.Товары" in adopted_keys
    assert "CommonModule.ОбщийМодуль1" in adopted_keys
    assert inv.name_prefix == "Тст_"
    assert any(m.has_change_and_control for m in inv.bsl_modules)


def test_new_objects_alert_lists_keys(tmp_path: Path) -> None:
    ext = build_extension_dump(tmp_path / "ext")
    inv = inventory_extension(ext)
    text = format_new_objects_alert(inv.own_objects)
    assert "ВНИМАНИЕ" in text
    assert "Catalog.Тст_Новый" in text
    assert str(len(inv.own_objects)) in text
