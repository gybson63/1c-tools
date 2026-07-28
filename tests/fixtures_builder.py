"""Minimal Designer dump fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path

CFG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Configuration uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">
\t\t<InternalInfo/>
\t\t<Properties>
\t\t\t<Name>TestConfig</Name>
\t\t\t<CompatibilityMode>Version8_3_24</CompatibilityMode>
\t\t\t<InterfaceCompatibilityMode>TaxiEnableVersion8_2</InterfaceCompatibilityMode>
\t\t\t<DefaultLanguage>Language.Русский</DefaultLanguage>
\t\t</Properties>
\t\t<ChildObjects>
\t\t\t<Language>Русский</Language>
\t\t\t<Catalog>ТестовыйСправочник</Catalog>
\t\t</ChildObjects>
\t</Configuration>
</MetaDataObject>
"""

LANG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Language uuid="11111111-2222-3333-4444-555555555555">
\t\t<Properties>
\t\t\t<Name>Русский</Name>
\t\t\t<LanguageCode>ru</LanguageCode>
\t\t</Properties>
\t</Language>
</MetaDataObject>
"""

CATALOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Catalog uuid="aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb">
\t\t<InternalInfo/>
\t\t<Properties>
\t\t\t<Name>ТестовыйСправочник</Name>
\t\t\t<Comment/>
\t\t</Properties>
\t\t<ChildObjects/>
\t</Catalog>
</MetaDataObject>
"""

BASE_BSL = """Процедура СтарыйМетод()
\tА = 1;
КонецПроцедуры

Функция НовыйМетод() Экспорт
\tВозврат 1;
КонецФункции
"""

CHANGED_BSL = """Процедура СтарыйМетод()
\tА = 2;
\tБ = 3;
КонецПроцедуры

Функция НовыйМетод() Экспорт
\tВозврат 1;
КонецФункции

Функция ДобавленныйМетод() Экспорт
\tВозврат 42;
КонецФункции
"""


def write_bom(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\n", "\r\n"), encoding="utf-8-sig")


def make_config_tree(root: Path) -> Path:
    write_bom(root / "Configuration.xml", CFG_XML)
    write_bom(root / "Languages" / "Русский.xml", LANG_XML)
    write_bom(root / "Catalogs" / "ТестовыйСправочник.xml", CATALOG_XML)
    write_bom(
        root / "Catalogs" / "ТестовыйСправочник" / "Ext" / "ManagerModule.bsl",
        BASE_BSL,
    )
    return root


def make_changes_tree(root: Path) -> Path:
    # only changed files (subset tree)
    write_bom(
        root / "Catalogs" / "ТестовыйСправочник" / "Ext" / "ManagerModule.bsl",
        CHANGED_BSL,
    )
    return root
