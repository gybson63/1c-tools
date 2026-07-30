"""Tests for BSL merge (reverse of &ИзменениеИКонтроль)."""

from __future__ import annotations

from cfe_into_cf.merge_bsl import apply_markers_to_body, merge_extension_bsl_into_main


def test_apply_markers_replace_line() -> None:
    base = ["\tСообщить(\"база\");"]
    marked = [
        "#Удаление",
        "\tСообщить(\"база\");",
        "#КонецУдаления",
        "#Вставка",
        "\tСообщить(\"расширение\");",
        "#КонецВставки",
    ]
    result = apply_markers_to_body(base, marked)
    assert result == ["\tСообщить(\"расширение\");"]


def test_merge_change_and_control_and_new_method() -> None:
    main = (
        'Процедура ПриЗаписи(Отказ)\n'
        '\tСообщить("база");\n'
        "КонецПроцедуры\n"
    )
    ext = (
        '&ИзменениеИКонтроль("ПриЗаписи")\n'
        "Процедура Тст_ПриЗаписи(Отказ)\n"
        "#Удаление\n"
        '\tСообщить("база");\n'
        "#КонецУдаления\n"
        "#Вставка\n"
        '\tСообщить("расширение");\n'
        "#КонецВставки\n"
        "КонецПроцедуры\n"
        "\n"
        "Процедура Тст_Новая()\n"
        '\tСообщить("новая");\n'
        "КонецПроцедуры\n"
    )
    merged, warnings = merge_extension_bsl_into_main(main, ext)
    assert not warnings
    assert 'Сообщить("расширение");' in merged
    assert 'Сообщить("база");' not in merged
    assert "Процедура Тст_Новая()" in merged
    assert "&ИзменениеИКонтроль" not in merged
