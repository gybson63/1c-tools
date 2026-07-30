from pathlib import Path

from cfe_tools.bsl_methods import (
    build_extension_module,
    build_marked_body,
    diff_methods,
    parse_methods,
)
from cfe_tools.inventory import build_inventory, map_path_to_object
from fixtures_builder import BASE_BSL, CHANGED_BSL, make_changes_tree, make_config_tree


def test_parse_methods():
    methods = parse_methods(BASE_BSL)
    names = {m.name for m in methods}
    assert "СтарыйМетод" in names
    assert "НовыйМетод" in names


def test_diff_and_patch():
    diffs = {d.name: d.status for d in diff_methods(BASE_BSL, CHANGED_BSL)}
    assert diffs["СтарыйМетод"] == "changed"
    assert diffs["НовыйМетод"] == "unchanged"
    assert diffs["ДобавленныйМетод"] == "new"

    text, warnings = build_extension_module(BASE_BSL, CHANGED_BSL, "Ext_")
    assert "&ИзменениеИКонтроль" in text
    assert "#Вставка" in text or "#Удаление" in text
    assert "ДобавленныйМетод" in text
    assert "Функция Ext_СтарыйМетод" in text or "Процедура Ext_СтарыйМетод" in text
    assert not any("Skip" in w for w in warnings)


def test_marked_body_insert():
    base = ["\tА = 1;"]
    changed = ["\tА = 1;", "\tБ = 2;"]
    marked = build_marked_body(base, changed)
    assert "#Вставка" in marked
    assert "\tБ = 2;" in marked


def test_map_path():
    ref = map_path_to_object("Catalogs/ТестовыйСправочник/Ext/ManagerModule.bsl")
    assert ref is not None
    assert ref.type_name == "Catalog"
    assert ref.object_name == "ТестовыйСправочник"
    assert ref.borrow_spec == "Catalog.ТестовыйСправочник"


def test_map_template_path():
    from cfe_tools.inventory import map_path_to_template

    ref = map_path_to_object("Reports/ВоронкаПродажНовый/Templates/ОсновнаяСхемаКомпоновкиДанных/Ext/Template.xml")
    assert ref is not None
    assert ref.template_name == "ОсновнаяСхемаКомпоновкиДанных"
    assert ref.object_name == "ВоронкаПродажНовый"

    tmpl = map_path_to_template("Reports/ВоронкаПродажНовый/Templates/ОсновнаяСхемаКомпоновкиДанных/Ext/Template.xml")
    assert tmpl is not None
    assert tmpl.template_name == "ОсновнаяСхемаКомпоновкиДанных"
    assert not tmpl.is_common


def test_map_unmapped_path():
    assert map_path_to_object("README.md") is None
    assert map_path_to_object("docs/guide.md") is None


def test_inventory(tmp_path: Path):
    cfg = make_config_tree(tmp_path / "config")
    ch = make_changes_tree(tmp_path / "changes")
    inv = build_inventory(cfg, ch)
    assert inv.bsl_files
    assert any(o.object_name == "ТестовыйСправочник" for o in inv.borrow_objects)
