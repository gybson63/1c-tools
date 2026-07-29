"""Tests for metadata transfer / Configuration.xml registration."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from cfe_tools.inventory import Inventory, ObjectRef
from cfe_tools.meta_transfer import create_own_objects, ensure_extension_objects_child_objects
from cfe_tools.vendor.cfe_init import create_extension


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\n", "\r\n"), encoding="utf-8-sig")


REPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
\t<Report uuid="bbbbbbbb-0000-1111-2222-cccccccccccc">
\t\t<InternalInfo>
\t\t\t<xr:GeneratedType name="ReportObject.Ext_ВоронкаПродажНовый" category="Object">
\t\t\t\t<xr:TypeId>11111111-1111-1111-1111-111111111111</xr:TypeId>
\t\t\t\t<xr:ValueId>22222222-2222-2222-2222-222222222222</xr:ValueId>
\t\t\t</xr:GeneratedType>
\t\t</InternalInfo>
\t\t<Properties>
\t\t\t<Name>Ext_ВоронкаПродажНовый</Name>
\t\t\t<Comment/>
\t\t\t<UseStandardCommands>true</UseStandardCommands>
\t\t</Properties>
\t</Report>
</MetaDataObject>
"""

REPORT_XML_BARE = """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" version="2.17" uuid="bbbbbbbb-0000-1111-2222-cccccccccccc">
\t<InternalInfo>
\t\t<xr:GeneratedType name="ReportObject.Ext_ВоронкаПродажНовый" category="Object">
\t\t\t<xr:TypeId>11111111-1111-1111-1111-111111111111</xr:TypeId>
\t\t\t<xr:ValueId>22222222-2222-2222-2222-222222222222</xr:ValueId>
\t\t</xr:GeneratedType>
\t</InternalInfo>
\t<Properties>
\t\t<Name>Ext_ВоронкаПродажНовый</Name>
\t\t<Comment/>
\t\t<UseStandardCommands>true</UseStandardCommands>
\t</Properties>
</Report>
"""


def test_create_own_report_registers_without_ns0(tmp_path: Path) -> None:
    ext = tmp_path / "ext"
    create_extension(
        name="ExtTest",
        output_dir=str(ext),
        name_prefix="Ext_",
        purpose="Customization",
        no_role=True,
    )
    changes = tmp_path / "changes"
    _write(changes / "Reports" / "Ext_ВоронкаПродажНовый.xml", REPORT_XML)

    inv = Inventory(new_objects=[ObjectRef(type_name="Report", object_name="Ext_ВоронкаПродажНовый")])
    warnings = create_own_objects(changes, ext, inv, "Ext_")
    assert not any("not found" in w for w in warnings)
    assert any("ChildObjects" in w for w in warnings)

    cfg_text = (ext / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "ns0:" not in cfg_text
    assert "&#13;" not in cfg_text
    assert "xmlns:xr=" in cfg_text or 'xmlns:xr="' in cfg_text
    assert "<Report>Ext_ВоронкаПродажНовый</Report>" in cfg_text
    # Report must stay inside ChildObjects
    co_start = cfg_text.index("<ChildObjects>")
    co_end = cfg_text.index("</ChildObjects>")
    assert "<Report>Ext_ВоронкаПродажНовый</Report>" in cfg_text[co_start:co_end]

    report_path = ext / "Reports" / "Ext_ВоронкаПродажНовый.xml"
    report_text = report_path.read_text(encoding="utf-8-sig")
    props_at = report_text.index("</Properties>")
    close_at = report_text.index("</Report>")
    assert "<ChildObjects" in report_text[props_at:close_at]

    tree = etree.parse(str(report_path))
    root = tree.getroot()
    report_el = root[0]
    tags = [etree.QName(c).localname for c in report_el if isinstance(c.tag, str)]
    assert "Properties" in tags
    assert "ChildObjects" in tags
    assert tags.index("Properties") < tags.index("ChildObjects")


def test_create_own_report_bare_root_gets_childobjects(tmp_path: Path) -> None:
    ext = tmp_path / "ext"
    create_extension(
        name="ExtTest",
        output_dir=str(ext),
        name_prefix="Ext_",
        purpose="Customization",
        no_role=True,
    )
    changes = tmp_path / "changes"
    _write(changes / "Reports" / "Ext_ВоронкаПродажНовый.xml", REPORT_XML_BARE)

    inv = Inventory(new_objects=[ObjectRef(type_name="Report", object_name="Ext_ВоронкаПродажНовый")])
    create_own_objects(changes, ext, inv, "Ext_")

    report_path = ext / "Reports" / "Ext_ВоронкаПродажНовый.xml"
    tree = etree.parse(str(report_path))
    root = tree.getroot()
    tags = [etree.QName(c).localname for c in root if isinstance(c.tag, str)]
    assert "Properties" in tags
    assert "ChildObjects" in tags
    assert tags.index("Properties") < tags.index("ChildObjects")


ADOPTED_REPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" version="2.17">
\t<Report uuid="f284048d-f0e4-4c8b-b3b1-03a6e23076b8">
\t\t<InternalInfo>
\t\t\t<xr:GeneratedType name="ReportObject.ВоронкаПродажНовый" category="Object">
\t\t\t\t<xr:TypeId>6dbb1ba5-b670-4566-bf35-f269dbe22fe6</xr:TypeId>
\t\t\t\t<xr:ValueId>4ad4f809-5da4-43d9-b385-33ffc76b8f54</xr:ValueId>
\t\t\t</xr:GeneratedType>
\t\t</InternalInfo>
\t\t<Properties>
\t\t\t<ObjectBelonging>Adopted</ObjectBelonging>
\t\t\t<Name>ВоронкаПродажНовый</Name>
\t\t\t<Comment/>
\t\t\t<ExtendedConfigurationObject>951a6ca5-cc5d-4f8d-8a59-d0b90813dd59</ExtendedConfigurationObject>
\t\t</Properties>
\t\t<ChildObjects/>
\t</Report>
</MetaDataObject>
"""

BASE_TEMPLATE_META = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" version="2.17">
\t<Template uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">
\t\t<Properties>
\t\t\t<Name>ОсновнаяСхемаКомпоновкиДанных</Name>
\t\t\t<TemplateType>DataCompositionSchema</TemplateType>
\t\t</Properties>
\t</Template>
</MetaDataObject>
"""

BASE_SKD = """<?xml version="1.0" encoding="UTF-8"?>
<DataCompositionSchema xmlns="http://v8.1c.ru/8.1/data-composition-system/schema" xmlns:dcscom="http://v8.1c.ru/8.1/data-composition-system/common" xmlns:dcscor="http://v8.1c.ru/8.1/data-composition-system/core" xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
\t<dataSource>
\t\t<name>ИсточникДанных1</name>
\t\t<dataSourceType>Local</dataSourceType>
\t</dataSource>
</DataCompositionSchema>
"""

CHANGED_SKD = """<?xml version="1.0" encoding="UTF-8"?>
<DataCompositionSchema xmlns="http://v8.1c.ru/8.1/data-composition-system/schema" xmlns:dcscom="http://v8.1c.ru/8.1/data-composition-system/common" xmlns:dcscor="http://v8.1c.ru/8.1/data-composition-system/core" xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
\t<dataSource>
\t\t<name>ИсточникДанных1</name>
\t\t<dataSourceType>Local</dataSourceType>
\t</dataSource>
\t<dataSet xsi:type="DataSetQuery">
\t\t<name>НаборДанных1</name>
\t\t<dataSource>ИсточникДанных1</dataSource>
\t\t<query>ВЫБРАТЬ 1 КАК Поле1</query>
\t</dataSet>
</DataCompositionSchema>
"""


def test_ensure_fixes_adopted_report_without_childobjects(tmp_path: Path) -> None:
    ext = tmp_path / "ext"
    create_extension(
        name="K7_20624",
        output_dir=str(ext),
        name_prefix="K7_20624_",
        purpose="Customization",
        no_role=True,
    )
    report = ext / "Reports" / "ВоронкаПродажНовый.xml"
    _write(report, ADOPTED_REPORT_XML.replace("\t\t<ChildObjects/>\n", ""))

    warnings = ensure_extension_objects_child_objects(ext)
    assert any("ChildObjects" in w and "ВоронкаПродажНовый" in w for w in warnings)

    text = report.read_text(encoding="utf-8-sig")
    assert "</Properties>" in text
    assert "<ChildObjects" in text[text.index("</Properties>") : text.index("</Report>")]


def test_apply_template_transfers_replaces_skd_wholly(tmp_path: Path) -> None:
    from cfe_tools.inventory import build_inventory
    from cfe_tools.meta_transfer import apply_template_transfers

    cfg = tmp_path / "config"
    ch = tmp_path / "changes"
    ext = tmp_path / "ext"
    create_extension(
        name="K7_20624",
        output_dir=str(ext),
        name_prefix="K7_20624_",
        purpose="Customization",
        no_role=True,
    )
    _write(ext / "Reports" / "ВоронкаПродажНовый.xml", ADOPTED_REPORT_XML)

    tmpl_rel = "Reports/ВоронкаПродажНовый/Templates/ОсновнаяСхемаКомпоновкиДанных"
    _write(
        cfg / "Reports" / "ВоронкаПродажНовый.xml",
        """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">
\t<Report uuid="951a6ca5-cc5d-4f8d-8a59-d0b90813dd59">
\t\t<Properties><Name>ВоронкаПродажНовый</Name></Properties>
\t\t<ChildObjects><Template>ОсновнаяСхемаКомпоновкиДанных</Template></ChildObjects>
\t</Report>
</MetaDataObject>
""",
    )
    _write(cfg / f"{tmpl_rel}.xml", BASE_TEMPLATE_META)
    _write(cfg / tmpl_rel / "Ext" / "Template.xml", BASE_SKD)
    # sparse changes tree: only Template.xml (as from git staging)
    _write(ch / tmpl_rel / "Ext" / "Template.xml", CHANGED_SKD)

    inv = build_inventory(cfg, ch)
    assert inv.template_files
    assert any(o.object_name == "ВоронкаПродажНовый" for o in inv.borrow_objects)

    warnings = apply_template_transfers(cfg, ch, ext, inv)
    assert not any("No Ext" in w or "missing" in w.lower() or "skip" in w.lower() for w in warnings)

    meta = ext / "Reports" / "ВоронкаПродажНовый" / "Templates" / "ОсновнаяСхемаКомпоновкиДанных.xml"
    body = (
        ext / "Reports" / "ВоронкаПродажНовый" / "Templates" / "ОсновнаяСхемаКомпоновкиДанных" / "Ext" / "Template.xml"
    )
    assert meta.is_file()
    meta_text = meta.read_text(encoding="utf-8-sig")
    assert "ObjectBelonging>Adopted" in meta_text
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in meta_text
    assert "DataCompositionSchema" in meta_text

    body_text = body.read_text(encoding="utf-8-sig")
    assert "НаборДанных1" in body_text
    assert "ВЫБРАТЬ 1" in body_text

    report_text = (ext / "Reports" / "ВоронкаПродажНовый.xml").read_text(encoding="utf-8-sig")
    assert "<Template>ОсновнаяСхемаКомпоновкиДанных</Template>" in report_text
