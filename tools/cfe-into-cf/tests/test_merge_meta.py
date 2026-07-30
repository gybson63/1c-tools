"""Tests for metadata merge and storage object list."""

from __future__ import annotations

from pathlib import Path

from cfe_into_cf.inventory import inventory_extension
from cfe_into_cf.merge_meta import merge_extension_into_main
from cfe_into_cf.storage import build_objects_xml, objects_for_lock, write_objects_file
from fixtures_builder import build_extension_dump, build_main_dump


def test_merge_own_and_adopted(tmp_path: Path) -> None:
    main = build_main_dump(tmp_path / "main")
    ext = build_extension_dump(tmp_path / "ext")
    inv = inventory_extension(ext)
    touched, warnings = merge_extension_into_main(ext, main, inv)
    assert (main / "Catalogs" / "Тст_Новый.xml").is_file()
    goods = (main / "Catalogs" / "Товары.xml").read_text(encoding="utf-8-sig")
    assert "Тст_ДопРеквизит" in goods
    module = (main / "CommonModules" / "ОбщийМодуль1" / "Ext" / "Module.bsl").read_text(
        encoding="utf-8-sig"
    )
    assert 'Сообщить("расширение");' in module
    assert "Тст_Новая" in module
    assert any(t == "Configuration.xml" or t.endswith("Тст_Новый.xml") for t in touched)
    # ObjectBelonging should be stripped from copied own object
    own_xml = (main / "Catalogs" / "Тст_Новый.xml").read_text(encoding="utf-8-sig")
    assert "ObjectBelonging" not in own_xml


def test_objects_xml_and_lock_targets(tmp_path: Path) -> None:
    ext = build_extension_dump(tmp_path / "ext")
    inv = inventory_extension(ext)
    objs, need_root = objects_for_lock(inv)
    assert need_root is True
    xml = build_objects_xml(objs, include_configuration=True, configuration_name="TestConfig")
    assert 'xmlns="http://v8.1c.ru/8.3/config/objects"' in xml
    assert 'fullName="Catalog.Товары"' in xml or "Catalog.Товары" in xml
    assert "<Configuration" in xml
    path = write_objects_file(tmp_path / "objects.xml", objs, include_configuration=True)
    assert path.is_file()
    assert path.read_text(encoding="utf-8-sig").startswith("<?xml")
