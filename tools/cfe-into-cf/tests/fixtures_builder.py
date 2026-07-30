"""Minimal Designer dump fixtures for cfe-into-cf tests."""

from __future__ import annotations

from pathlib import Path

CONFIG_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Configuration uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">
\t\t<InternalInfo/>
\t\t<Properties>
\t\t\t<Name>TestConfig</Name>
\t\t\t<Synonym/>
\t\t\t<Comment/>
\t\t\t<NamePrefix></NamePrefix>
\t\t\t<ConfigurationExtensionPurpose>Customization</ConfigurationExtensionPurpose>
\t\t</Properties>
\t\t<ChildObjects>
\t\t\t<Catalog>Товары</Catalog>
\t\t\t<CommonModule>ОбщийМодуль1</CommonModule>
\t\t</ChildObjects>
\t</Configuration>
</MetaDataObject>
"""

EXT_CONFIG_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Configuration uuid="11111111-2222-3333-4444-555555555555">
\t\t<InternalInfo/>
\t\t<Properties>
\t\t\t<ObjectBelonging>Own</ObjectBelonging>
\t\t\t<Name>TestExt</Name>
\t\t\t<NamePrefix>Тст_</NamePrefix>
\t\t\t<ConfigurationExtensionPurpose>Customization</ConfigurationExtensionPurpose>
\t\t</Properties>
\t\t<ChildObjects>
\t\t\t<Catalog>Товары</Catalog>
\t\t\t<Catalog>Тст_Новый</Catalog>
\t\t\t<CommonModule>ОбщийМодуль1</CommonModule>
\t\t</ChildObjects>
\t</Configuration>
</MetaDataObject>
"""

CATALOG_MAIN = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Catalog uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb">
\t\t<Properties>
\t\t\t<Name>Товары</Name>
\t\t</Properties>
\t\t<ChildObjects>
\t\t\t<Attribute uuid="cccccccc-cccc-cccc-cccc-cccccccccccc">
\t\t\t\t<Properties>
\t\t\t\t\t<Name>Код</Name>
\t\t\t\t</Properties>
\t\t\t</Attribute>
\t\t</ChildObjects>
\t</Catalog>
</MetaDataObject>
"""

CATALOG_ADOPTED = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Catalog uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb">
\t\t<InternalInfo/>
\t\t<Properties>
\t\t\t<ObjectBelonging>Adopted</ObjectBelonging>
\t\t\t<Name>Товары</Name>
\t\t</Properties>
\t\t<ChildObjects>
\t\t\t<Attribute uuid="dddddddd-dddd-dddd-dddd-dddddddddddd">
\t\t\t\t<Properties>
\t\t\t\t\t<Name>Тст_ДопРеквизит</Name>
\t\t\t\t</Properties>
\t\t\t</Attribute>
\t\t</ChildObjects>
\t</Catalog>
</MetaDataObject>
"""

CATALOG_OWN = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Catalog uuid="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee">
\t\t<Properties>
\t\t\t<ObjectBelonging>Own</ObjectBelonging>
\t\t\t<Name>Тст_Новый</Name>
\t\t</Properties>
\t\t<ChildObjects/>
\t</Catalog>
</MetaDataObject>
"""

MODULE_MAIN = """\
Процедура ПриЗаписи(Отказ)
\tСообщить("база");
КонецПроцедуры
"""

MODULE_EXT = """\
&ИзменениеИКонтроль("ПриЗаписи")
Процедура Тст_ПриЗаписи(Отказ)
#Удаление
\tСообщить("база");
#КонецУдаления
#Вставка
\tСообщить("расширение");
#КонецВставки
КонецПроцедуры

Процедура Тст_Новая()
\tСообщить("новая");
КонецПроцедуры
"""

COMMON_MODULE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<CommonModule uuid="ffffffff-ffff-ffff-ffff-ffffffffffff">
\t\t<Properties>
\t\t\t<ObjectBelonging>Adopted</ObjectBelonging>
\t\t\t<Name>ОбщийМодуль1</Name>
\t\t</Properties>
\t</CommonModule>
</MetaDataObject>
"""

COMMON_MODULE_MAIN_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<CommonModule uuid="ffffffff-ffff-ffff-ffff-ffffffffffff">
\t\t<Properties>
\t\t\t<Name>ОбщийМодуль1</Name>
\t\t</Properties>
\t</CommonModule>
</MetaDataObject>
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\n", "\r\n"), encoding="utf-8-sig")


def build_main_dump(root: Path) -> Path:
    write(root / "Configuration.xml", CONFIG_XML)
    write(root / "Catalogs" / "Товары.xml", CATALOG_MAIN)
    write(root / "CommonModules" / "ОбщийМодуль1.xml", COMMON_MODULE_MAIN_XML)
    write(root / "CommonModules" / "ОбщийМодуль1" / "Ext" / "Module.bsl", MODULE_MAIN)
    return root


def build_extension_dump(root: Path) -> Path:
    write(root / "Configuration.xml", EXT_CONFIG_XML)
    write(root / "Catalogs" / "Товары.xml", CATALOG_ADOPTED)
    write(root / "Catalogs" / "Тст_Новый.xml", CATALOG_OWN)
    write(root / "CommonModules" / "ОбщийМодуль1.xml", COMMON_MODULE_XML)
    write(root / "CommonModules" / "ОбщийМодуль1" / "Ext" / "Module.bsl", MODULE_EXT)
    return root
