"""Transfer metadata changes (attributes, forms, new objects) into extension XML."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from lxml import etree

from cfe_tools.inventory import DIR_TO_TYPE, Inventory, map_path_to_template, object_exists_in_config
from cfe_tools.vendor.cfe_borrow import (
    MD_NS,
    TYPE_ORDER,
    XMLNS_DECL,
    detect_format_version,
    expand_self_closing,
    get_child_indent,
    insert_before_closing,
    insert_before_ref,
    localname,
    new_guid,
    save_text_bom,
    save_xml_bom,
)

# Own metadata objects that must have ChildObjects after Properties for ibcmd import.
_OBJECT_CLOSE_RE = re.compile(
    r"</(Catalog|Document|Enum|Report|DataProcessor|ExchangePlan|"
    r"ChartOfAccounts|ChartOfCharacteristicTypes|ChartOfCalculationTypes|"
    r"BusinessProcess|Task|InformationRegister|AccumulationRegister|"
    r"AccountingRegister|CalculationRegister|Constant|CommonForm|"
    r"CommonCommand|CommonTemplate|CommonPicture|Role|Subsystem|"
    r"SessionParameter|FilterCriterion|EventSubscription|ScheduledJob|"
    r"FunctionalOption|FunctionalOptionsParameter|DefinedType|SettingsStorage|"
    r"CommandGroup|WebService|HTTPService|WSReference|XDTOPackage|"
    r"StyleItem|Style|Language|DocumentJournal|Sequence|DocumentNumerator|"
    r"CommonModule|CommonAttribute)\s*>",
    re.IGNORECASE,
)
_PROPERTIES_CLOSE_RE = re.compile(r"</Properties\s*>", re.IGNORECASE)
_CHILD_OBJECTS_RE = re.compile(r"<ChildObjects(\s[^>]*)?\s*(/>|>)", re.IGNORECASE)

CHILD_PROPERTY_TAGS = {
    "Attribute",
    "TabularSection",
    "Dimension",
    "Resource",
    "Form",
    "Template",
    "Command",
    "EnumValue",
}


def describe_object_xml_structure(path: Path) -> str:
    """Short human-readable structure summary for logs / diagnostics."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return f"{path.name}: cannot read ({exc})"

    root_m = re.search(r"<(MetaDataObject|Report|Catalog|Document|DataProcessor)\b", text)
    root_name = root_m.group(1) if root_m else "?"

    tags: list[str] = []
    try:
        tree = _parse_xml(path)
        obj_el = _object_element(tree.getroot())
        if obj_el is not None:
            tags = [localname(c) for c in obj_el if isinstance(c.tag, str)]
    except etree.XMLSyntaxError as exc:
        return f"{path.name}: XML parse error: {exc}"

    props_m = _PROPERTIES_CLOSE_RE.search(text)
    close_m = None
    for m in _OBJECT_CLOSE_RE.finditer(text):
        close_m = m
    between = ""
    has_co_after_props = False
    if props_m and close_m and props_m.end() <= close_m.start():
        between = text[props_m.end() : close_m.start()]
        has_co_after_props = _CHILD_OBJECTS_RE.search(between) is not None

    snippet = ""
    if props_m:
        start = max(0, props_m.start() - 40)
        end = min(len(text), props_m.end() + 120)
        snippet = text[start:end].replace("\r\n", "\n").replace("\r", "\n")
        snippet = re.sub(r"\n+", "\n", snippet).strip()

    return (
        f"{path.name}: root={root_name}; children={tags or ['?']}; "
        f"ChildObjects_after_Properties={has_co_after_props}"
        + (f"; around_Properties=\n<<<\n{snippet}\n>>>" if snippet else "")
    )


def diagnose_own_object_files(extension_root: Path) -> list[str]:
    """Return diagnostics for object XML files under the extension (Reports, Catalogs, …)."""
    lines: list[str] = []
    for folder in sorted(DIR_TO_TYPE):
        d = extension_root / folder
        if not d.is_dir():
            continue
        for xml in sorted(d.glob("*.xml")):
            lines.append(describe_object_xml_structure(xml))
    return lines


def _parse_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False)
    return etree.parse(str(path), parser)


def _find_child_objects(root: etree._Element) -> etree._Element | None:
    """Return the object's own ChildObjects (not nested TabularSection ones)."""
    obj_el = _object_element(root)
    if obj_el is not None:
        for sub in obj_el:
            if isinstance(sub.tag, str) and localname(sub) == "ChildObjects":
                return sub
    # Fallback: first ChildObjects in document order
    for el in root.iter():
        if isinstance(el.tag, str) and localname(el) == "ChildObjects":
            return el
    return None


def _object_element(root: etree._Element) -> etree._Element | None:
    """Return object element (Report/Catalog/...) for MetaDataObject or bare-object XML."""
    if isinstance(root.tag, str) and localname(root) != "MetaDataObject":
        return root
    for child in root:
        if isinstance(child.tag, str):
            return child
    return None


def _child_names(child_objects: etree._Element) -> set[str]:
    names: set[str] = set()
    for ch in list(child_objects):
        if not isinstance(ch.tag, str):
            continue
        text = (ch.text or "").strip()
        if text:
            names.add(f"{localname(ch)}:{text}")
            continue
        name_el = None
        for sub in ch.iter():
            if isinstance(sub.tag, str) and localname(sub) == "Name" and sub.text:
                name_el = sub
                break
        if name_el is not None and name_el.text:
            names.add(f"{localname(ch)}:{name_el.text.strip()}")
    return names


def _type_dir(type_name: str) -> str | None:
    for folder, tname in DIR_TO_TYPE.items():
        if tname == type_name:
            return folder
    return None


def transfer_new_attributes(
    config_root: Path,
    changes_root: Path,
    extension_root: Path,
    inventory: Inventory,
) -> list[str]:
    """Copy new ChildObjects entries from changed object XML into borrowed extension XML."""
    warnings: list[str] = []
    for fc in inventory.object_xml_files:
        if fc.kind not in ("added", "modified"):
            continue
        from cfe_tools.inventory import map_path_to_object

        ref = map_path_to_object(fc.rel_path)
        if ref is None or not object_exists_in_config(config_root, ref):
            continue
        dir_name = _type_dir(ref.type_name)
        if not dir_name:
            continue
        base_xml = config_root / fc.rel_path
        ch_xml = changes_root / fc.rel_path
        ext_xml = extension_root / dir_name / f"{ref.object_name}.xml"
        if not ext_xml.is_file() or not ch_xml.is_file() or not base_xml.is_file():
            warnings.append(f"Skip attribute transfer, missing files for {fc.rel_path}")
            continue
        try:
            base_tree = _parse_xml(base_xml)
            ch_tree = _parse_xml(ch_xml)
            ext_tree = _parse_xml(ext_xml)
        except etree.XMLSyntaxError as exc:
            warnings.append(f"XML parse error for {fc.rel_path}: {exc}")
            continue

        base_co = _find_child_objects(base_tree.getroot())
        ch_co = _find_child_objects(ch_tree.getroot())
        ext_co = _find_child_objects(ext_tree.getroot())
        if ch_co is None:
            continue
        if ext_co is None:
            obj_el = None
            for el in ext_tree.getroot():
                if isinstance(el.tag, str) and localname(el) != "MetaDataObject":
                    obj_el = el
                    break
            if obj_el is None:
                warnings.append(f"No object element in {ext_xml}")
                continue
            ext_co = etree.SubElement(obj_el, f"{{{MD_NS}}}ChildObjects")

        base_names = _child_names(base_co) if base_co is not None else set()
        added = 0
        for ch in list(ch_co):
            if not isinstance(ch.tag, str):
                continue
            tag = localname(ch)
            if tag not in CHILD_PROPERTY_TAGS:
                continue
            text = (ch.text or "").strip()
            key = None
            if text:
                key = f"{tag}:{text}"
            else:
                name_el = None
                for sub in ch.iter():
                    if isinstance(sub.tag, str) and localname(sub) == "Name" and sub.text:
                        name_el = sub
                        break
                if name_el is not None and name_el.text:
                    key = f"{tag}:{name_el.text.strip()}"
            if not key or key in base_names:
                continue
            if tag == "Form" and text:
                continue
            ext_co.append(ch)
            added += 1
        if added:
            save_xml_bom(ext_tree, str(ext_xml))
            warnings.append(f"Transferred {added} new child object(s) into {ext_xml.name}")
    return warnings


def apply_form_xml_changes(
    config_root: Path,
    changes_root: Path,
    extension_root: Path,
    inventory: Inventory,
) -> list[str]:
    """Replace borrowed Form.xml with changed version, preserving BaseForm from base."""
    warnings: list[str] = []
    for fc in inventory.form_xml_files:
        if fc.kind not in ("added", "modified"):
            continue
        from cfe_tools.inventory import map_path_to_object

        ref = map_path_to_object(fc.rel_path)
        if ref is None or not ref.form_name:
            continue
        dir_name = _type_dir(ref.type_name)
        if not dir_name:
            continue
        ext_form = extension_root / dir_name / ref.object_name / "Forms" / ref.form_name / "Ext" / "Form.xml"
        ch_form = Path(fc.change_abs) if fc.change_abs else changes_root / fc.rel_path
        base_form = config_root / fc.rel_path
        if not ch_form.is_file():
            warnings.append(f"Changed form missing: {fc.rel_path}")
            continue
        if not ext_form.is_file():
            warnings.append(f"Borrowed form not found yet: {ext_form}")
            continue

        try:
            ch_tree = _parse_xml(ch_form)
            ch_root = ch_tree.getroot()
        except etree.XMLSyntaxError as exc:
            warnings.append(f"Form parse error {fc.rel_path}: {exc}")
            continue

        for el in list(ch_root):
            if isinstance(el.tag, str) and localname(el) == "BaseForm":
                ch_root.remove(el)

        if base_form.is_file():
            try:
                base_tree = _parse_xml(base_form)
                base_root = base_tree.getroot()
                ns = etree.QName(base_root).namespace or ""
                tag = f"{{{ns}}}BaseForm" if ns else "BaseForm"
                base_form_el = etree.Element(tag)
                for child in list(base_root):
                    if isinstance(child.tag, str) and localname(child) == "BaseForm":
                        continue
                    base_form_el.append(child)
                ch_root.append(base_form_el)
            except etree.XMLSyntaxError as exc:
                warnings.append(f"Base form parse error {fc.rel_path}: {exc}")

        ext_form.parent.mkdir(parents=True, exist_ok=True)
        # Form.xml in Designer dumps is typically UTF-8 without BOM
        xml_bytes = etree.tostring(ch_tree, xml_declaration=True, encoding="UTF-8")
        xml_bytes = xml_bytes.replace(
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b'<?xml version="1.0" encoding="utf-8"?>',
        )
        if not xml_bytes.endswith(b"\n"):
            xml_bytes += b"\n"
        ext_form.write_bytes(xml_bytes)
    return warnings


def _read_template_meta_props(meta_path: Path) -> tuple[str, str | None]:
    """Return (uuid, TemplateType or None) from Templates/Name.xml."""
    tree = _parse_xml(meta_path)
    root = tree.getroot()
    tmpl_el = _object_element(root)
    if tmpl_el is None:
        raise ValueError(f"No Template element in {meta_path}")
    source_uuid = tmpl_el.get("uuid") or ""
    if not source_uuid:
        raise ValueError(f"No uuid on Template in {meta_path}")
    template_type: str | None = None
    for props in tmpl_el:
        if not isinstance(props.tag, str) or localname(props) != "Properties":
            continue
        for prop in props:
            if isinstance(prop.tag, str) and localname(prop) == "TemplateType":
                template_type = (prop.text or "").strip() or None
                break
    return source_uuid, template_type


def _build_adopted_template_xml(
    template_name: str,
    source_uuid: str,
    template_type: str | None,
    format_version: str,
) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<MetaDataObject {XMLNS_DECL} version="{format_version}">',
        f'\t<Template uuid="{new_guid()}">',
        "\t\t<InternalInfo/>",
        "\t\t<Properties>",
        "\t\t\t<ObjectBelonging>Adopted</ObjectBelonging>",
        f"\t\t\t<Name>{template_name}</Name>",
        "\t\t\t<Comment/>",
        f"\t\t\t<ExtendedConfigurationObject>{source_uuid}</ExtendedConfigurationObject>",
    ]
    if template_type:
        lines.append(f"\t\t\t<TemplateType>{template_type}</TemplateType>")
    lines.extend(
        [
            "\t\t</Properties>",
            "\t</Template>",
            "</MetaDataObject>",
            "",
        ]
    )
    return "\n".join(lines)


def _register_template_in_object(object_xml: Path, template_name: str) -> None:
    """Ensure <Template>Name</Template> is listed in the parent object's ChildObjects."""
    tree = _parse_xml(object_xml)
    root = tree.getroot()
    obj_el = _object_element(root)
    if obj_el is None:
        raise ValueError(f"No object element in {object_xml}")

    child_objs = None
    for sub in obj_el:
        if isinstance(sub.tag, str) and localname(sub) == "ChildObjects":
            child_objs = sub
            break
    if child_objs is None:
        child_objs = etree.SubElement(obj_el, f"{{{MD_NS}}}ChildObjects")
        prev = child_objs.getprevious()
        if prev is not None:
            child_objs.tail = "\r\n\t"
            prev.tail = "\r\n\t\t"

    for c in child_objs:
        if isinstance(c.tag, str) and localname(c) == "Template" and (c.text or "") == template_name:
            save_xml_bom(tree, str(object_xml))
            return

    if len(child_objs) == 0 and not (child_objs.text and child_objs.text.strip()):
        # Expand self-closing / empty ChildObjects
        expand_self_closing(child_objs, "\t\t")
        child_objs.text = "\r\n\t\t\t"

    tmpl_el = etree.Element(f"{{{MD_NS}}}Template")
    tmpl_el.text = template_name
    insert_before_closing(child_objs, tmpl_el, "\t\t\t")
    save_xml_bom(tree, str(object_xml))


def _overlay_copy_tree(base_dir: Path | None, overlay_dir: Path | None, dst_dir: Path) -> bool:
    """Copy base tree then overlay changed files. Returns True if anything was copied."""
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    copied = False
    if base_dir is not None and base_dir.is_dir():
        shutil.copytree(base_dir, dst_dir)
        copied = True
    if overlay_dir is not None and overlay_dir.is_dir():
        if not dst_dir.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)
        for src in overlay_dir.rglob("*"):
            if not src.is_file():
                continue
            target = dst_dir / src.relative_to(overlay_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied = True
    return copied


def apply_template_transfers(
    config_root: Path,
    changes_root: Path,
    extension_root: Path,
    inventory: Inventory,
) -> list[str]:
    """Adopt changed templates into the extension and replace Ext content wholesale.

    SKD / Template.xml has no #Вставка markers — the whole XML (and sibling Ext files)
    is copied from the changes tree (overlaying the base dump when sparse).
    """
    warnings: list[str] = []
    seen: dict[str, object] = {}
    format_version = detect_format_version(str(extension_root))

    for fc in inventory.template_files:
        if fc.kind not in ("added", "modified"):
            continue
        ref = map_path_to_template(fc.rel_path)
        if ref is None or ref.key in seen:
            continue
        seen[ref.key] = ref

        if ref.is_common:
            parent_xml = extension_root / "CommonTemplates" / f"{ref.template_name}.xml"
            cfg_ext = config_root / "CommonTemplates" / ref.template_name
            ch_ext = changes_root / "CommonTemplates" / ref.template_name
            dst_ext = extension_root / "CommonTemplates" / ref.template_name
            if not parent_xml.is_file():
                warnings.append(f"CommonTemplate not borrowed yet, skip Ext replace: {ref.template_name}")
                continue
            if not _overlay_copy_tree(
                cfg_ext if cfg_ext.is_dir() else None,
                ch_ext if ch_ext.is_dir() else None,
                dst_ext,
            ):
                warnings.append(f"No Ext content for CommonTemplate.{ref.template_name}")
                continue
            continue

        parent_xml = extension_root / ref.type_dir / f"{ref.object_name}.xml"
        if not parent_xml.is_file():
            warnings.append(
                f"Parent object not in extension, skip template {ref.type_dir}/{ref.object_name}/{ref.template_name}"
            )
            continue

        cfg_meta = config_root / ref.type_dir / ref.object_name / "Templates" / f"{ref.template_name}.xml"
        ch_meta = changes_root / ref.type_dir / ref.object_name / "Templates" / f"{ref.template_name}.xml"
        cfg_ext = config_root / ref.type_dir / ref.object_name / "Templates" / ref.template_name
        ch_ext = changes_root / ref.type_dir / ref.object_name / "Templates" / ref.template_name
        dst_meta = extension_root / ref.type_dir / ref.object_name / "Templates" / f"{ref.template_name}.xml"
        dst_ext = extension_root / ref.type_dir / ref.object_name / "Templates" / ref.template_name

        dst_meta.parent.mkdir(parents=True, exist_ok=True)

        if cfg_meta.is_file():
            try:
                source_uuid, template_type = _read_template_meta_props(cfg_meta)
            except (etree.XMLSyntaxError, ValueError) as exc:
                warnings.append(f"Template meta error {cfg_meta}: {exc}")
                continue
            save_text_bom(
                str(dst_meta),
                _build_adopted_template_xml(ref.template_name, source_uuid, template_type, format_version),
            )
        elif ch_meta.is_file():
            # New own template — copy metadata as-is from changes.
            shutil.copy2(ch_meta, dst_meta)
            warnings.append(f"Own template (not in base CF): {ref.type_dir}/{ref.object_name}/{ref.template_name}")
        else:
            warnings.append(
                f"Template metadata missing in config and changes: "
                f"{ref.type_dir}/{ref.object_name}/Templates/{ref.template_name}.xml"
            )
            continue

        try:
            _register_template_in_object(parent_xml, ref.template_name)
        except ValueError as exc:
            warnings.append(str(exc))
            continue

        if not _overlay_copy_tree(
            cfg_ext if cfg_ext.is_dir() else None,
            ch_ext if ch_ext.is_dir() else None,
            dst_ext,
        ):
            warnings.append(f"No Ext content for template {ref.type_dir}/{ref.object_name}/{ref.template_name}")

    return warnings


def create_own_objects(
    changes_root: Path,
    extension_root: Path,
    inventory: Inventory,
    name_prefix: str,
) -> list[str]:
    """Copy brand-new objects into extension as Own (best-effort file copy + ChildObjects)."""
    warnings: list[str] = []
    for ref in inventory.new_objects:
        dir_name = _type_dir(ref.type_name)
        if not dir_name:
            warnings.append(f"Unsupported new object type: {ref.type_name}.{ref.object_name}")
            continue
        src_meta = changes_root / dir_name / f"{ref.object_name}.xml"
        src_dir = changes_root / dir_name / ref.object_name
        if not src_meta.is_file():
            warnings.append(f"New object metadata not found: {src_meta}")
            continue

        if not ref.object_name.startswith(name_prefix):
            warnings.append(
                f"New object {ref.type_name}.{ref.object_name} has no NamePrefix; "
                f"copied as-is (platform may require prefix {name_prefix})"
            )

        dst_meta = extension_root / dir_name / f"{ref.object_name}.xml"
        dst_dir = extension_root / dir_name / ref.object_name
        dst_meta.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_meta, dst_meta)
        if src_dir.is_dir():
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)

        warnings.append(f"Own object source: {describe_object_xml_structure(src_meta)}")
        added = _ensure_own_object_child_objects(dst_meta)
        if added:
            warnings.append(f"Added missing ChildObjects to {dst_meta.name}")
        warnings.append(f"Own object result: {describe_object_xml_structure(dst_meta)}")
        _register_child_object(extension_root, ref.type_name, ref.object_name)
    return warnings


def _ensure_own_object_child_objects(object_xml: Path) -> bool:
    """Ensure Properties is followed by ChildObjects (required by ibcmd import).

    Uses text injection (not lxml rewrite) to preserve Designer namespaces/formatting.
    Returns True when ChildObjects was inserted.
    """
    raw = object_xml.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")

    props = list(_PROPERTIES_CLOSE_RE.finditer(text))
    if not props:
        raise ValueError(f"No </Properties> in object metadata: {object_xml}")

    # Use the last Properties close before the object close tag when possible.
    close = None
    for m in _OBJECT_CLOSE_RE.finditer(text):
        close = m
    if close is None:
        raise ValueError(f"No object closing tag in metadata: {object_xml}")

    props_m = None
    for m in props:
        if m.end() <= close.start():
            props_m = m
    if props_m is None:
        raise ValueError(f"No </Properties> before object close in: {object_xml}")

    between = text[props_m.end() : close.start()]
    if _CHILD_OBJECTS_RE.search(between):
        return False

    # Insert canonical empty ChildObjects right after Properties.
    nl = "\r\n" if "\r\n" in text else "\n"
    # Indent like Designer: two tabs under Report/Catalog.
    insertion = f"{nl}\t\t<ChildObjects/>"
    new_text = text[: props_m.end()] + insertion + text[props_m.end() :]
    data = new_text.encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    object_xml.write_bytes(data)

    # Verify — do not silently leave a broken file for ibcmd.
    verify = object_xml.read_text(encoding="utf-8-sig")
    props2 = list(_PROPERTIES_CLOSE_RE.finditer(verify))
    close2 = None
    for m in _OBJECT_CLOSE_RE.finditer(verify):
        close2 = m
    if not props2 or close2 is None:
        raise ValueError(f"Failed to verify ChildObjects injection: {object_xml}")
    props_m2 = None
    for m in props2:
        if m.end() <= close2.start():
            props_m2 = m
    if props_m2 is None or not _CHILD_OBJECTS_RE.search(verify[props_m2.end() : close2.start()]):
        raise ValueError(f"ChildObjects missing after Properties in: {object_xml}")
    return True


def _strip_cr_whitespace(el: etree._Element) -> None:
    """Remove CR from text/tails so lxml does not serialize them as &#13;."""
    if el.text:
        el.text = el.text.replace("\r", "")
    if el.tail:
        el.tail = el.tail.replace("\r", "")
    for child in el:
        _strip_cr_whitespace(child)


def _register_child_object(extension_root: Path, type_name: str, object_name: str) -> None:
    """Register object in Configuration.xml ChildObjects using lxml (keeps 1C namespaces)."""
    cfg = extension_root / "Configuration.xml"
    if not cfg.is_file():
        return
    tree = _parse_xml(cfg)
    root = tree.getroot()

    cfg_el = None
    for el in root:
        if isinstance(el.tag, str) and localname(el) == "Configuration":
            cfg_el = el
            break
    if cfg_el is None:
        return

    child_objs_el = None
    for el in cfg_el:
        if isinstance(el.tag, str) and localname(el) == "ChildObjects":
            child_objs_el = el
            break
    if child_objs_el is None:
        return

    for child in child_objs_el:
        if isinstance(child.tag, str) and localname(child) == type_name and (child.text or "").strip() == object_name:
            return

    # Avoid &#13; entities from CR in Designer dumps — use LF-only whitespace tails.
    _strip_cr_whitespace(child_objs_el)
    cfg_indent = get_child_indent(cfg_el).replace("\r", "")
    if len(child_objs_el) == 0 and not (child_objs_el.text and child_objs_el.text.strip()):
        expand_self_closing(child_objs_el, cfg_indent)
    ci = get_child_indent(child_objs_el).replace("\r", "")

    if type_name not in TYPE_ORDER:
        # Unknown type: append at end
        new_el = etree.Element(f"{{{MD_NS}}}{type_name}")
        new_el.text = object_name
        insert_before_closing(child_objs_el, new_el, ci)
        _strip_cr_whitespace(child_objs_el)
        save_xml_bom(tree, str(cfg))
        return

    type_idx = TYPE_ORDER.index(type_name)
    insert_before = None
    for child in child_objs_el:
        if not isinstance(child.tag, str):
            continue
        child_type_name = localname(child)
        if child_type_name not in TYPE_ORDER:
            continue
        child_type_idx = TYPE_ORDER.index(child_type_name)
        if child_type_name == type_name:
            if (child.text or "") > object_name and insert_before is None:
                insert_before = child
        elif child_type_idx > type_idx and insert_before is None:
            insert_before = child

    new_el = etree.Element(f"{{{MD_NS}}}{type_name}")
    new_el.text = object_name
    if insert_before is not None:
        insert_before_ref(child_objs_el, new_el, insert_before, ci)
    else:
        insert_before_closing(child_objs_el, new_el, ci)

    _strip_cr_whitespace(child_objs_el)
    save_xml_bom(tree, str(cfg))


def ensure_extension_objects_child_objects(extension_root: Path) -> list[str]:
    """Ensure object XMLs that require ChildObjects have it after Properties.

    Covers borrowed (Adopted) Reports/DataProcessors/etc. — ibcmd rejects them without
    ChildObjects. Languages and similar types are skipped.
    """
    from cfe_tools.vendor.cfe_borrow import TYPES_WITH_CHILD_OBJECTS

    warnings: list[str] = []
    for folder, type_name in sorted(DIR_TO_TYPE.items()):
        if type_name not in TYPES_WITH_CHILD_OBJECTS:
            continue
        d = extension_root / folder
        if not d.is_dir():
            continue
        for xml in sorted(d.glob("*.xml")):
            try:
                if _ensure_own_object_child_objects(xml):
                    warnings.append(f"Added missing ChildObjects to {folder}/{xml.name}")
            except ValueError as exc:
                warnings.append(str(exc))
    return warnings


def apply_metadata_transfers(
    config_root: Path,
    changes_root: Path,
    extension_root: Path,
    inventory: Inventory,
    name_prefix: str,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(transfer_new_attributes(config_root, changes_root, extension_root, inventory))
    warnings.extend(apply_form_xml_changes(config_root, changes_root, extension_root, inventory))
    warnings.extend(apply_template_transfers(config_root, changes_root, extension_root, inventory))
    warnings.extend(create_own_objects(changes_root, extension_root, inventory, name_prefix))
    # Safety net: borrowed Reports/etc. may lack ChildObjects if vendor borrow omitted them.
    warnings.extend(ensure_extension_objects_child_objects(extension_root))
    return warnings
