"""Transfer metadata changes (attributes, forms, new objects) into extension XML."""

from __future__ import annotations

import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

from cfe_tools.inventory import DIR_TO_TYPE, Inventory, object_exists_in_config

MD_NS = "http://v8.1c.ru/8.3/MDClasses"
NSMAP = {
    "md": MD_NS,
    "xr": "http://v8.1c.ru/8.3/xcf/readable",
    "v8": "http://v8.1c.ru/8.1/data/core",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xs": "http://www.w3.org/2001/XMLSchema",
}

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


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_child_objects(root: ET.Element) -> ET.Element | None:
    for el in root.iter():
        if _local(el.tag) == "ChildObjects":
            return el
    return None


def _child_names(child_objects: ET.Element) -> set[str]:
    names: set[str] = set()
    for ch in list(child_objects):
        text = (ch.text or "").strip()
        if text:
            names.add(f"{_local(ch.tag)}:{text}")
        else:
            # nested property objects with Name
            name_el = None
            for sub in ch.iter():
                if _local(sub.tag) == "Name" and sub.text:
                    name_el = sub
                    break
            if name_el is not None and name_el.text:
                names.add(f"{_local(ch.tag)}:{name_el.text.strip()}")
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
        ref = None
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
            base_tree = ET.parse(base_xml)
            ch_tree = ET.parse(ch_xml)
            ext_tree = ET.parse(ext_xml)
        except ET.ParseError as exc:
            warnings.append(f"XML parse error for {fc.rel_path}: {exc}")
            continue

        base_co = _find_child_objects(base_tree.getroot())
        ch_co = _find_child_objects(ch_tree.getroot())
        ext_co = _find_child_objects(ext_tree.getroot())
        if ch_co is None:
            continue
        if ext_co is None:
            # create ChildObjects under object element
            obj_el = None
            for el in ext_tree.getroot():
                if _local(el.tag) not in ("MetaDataObject",):
                    obj_el = el
                    break
            if obj_el is None:
                warnings.append(f"No object element in {ext_xml}")
                continue
            ext_co = ET.SubElement(obj_el, f"{{{MD_NS}}}ChildObjects")

        base_names = _child_names(base_co) if base_co is not None else set()
        added = 0
        for ch in list(ch_co):
            tag = _local(ch.tag)
            if tag not in CHILD_PROPERTY_TAGS:
                continue
            # identify
            key = None
            text = (ch.text or "").strip()
            if text:
                key = f"{tag}:{text}"
            else:
                name_el = None
                for sub in ch.iter():
                    if _local(sub.tag) == "Name" and sub.text:
                        name_el = sub
                        break
                if name_el is not None and name_el.text:
                    key = f"{tag}:{name_el.text.strip()}"
            if not key or key in base_names:
                continue
            # skip Form refs — forms handled separately via borrow
            if tag == "Form" and text:
                continue
            ext_co.append(ch)
            added += 1
        if added:
            ext_tree.write(ext_xml, encoding="utf-8", xml_declaration=True)
            # ensure BOM
            _ensure_bom(ext_xml)
            inventory.warnings.append(f"Transferred {added} new child object(s) into {ext_xml.name}")
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
            ch_tree = ET.parse(ch_form)
            ch_root = ch_tree.getroot()
        except ET.ParseError as exc:
            warnings.append(f"Form parse error {fc.rel_path}: {exc}")
            continue

        # Remove existing BaseForm from changed, then attach base content as BaseForm
        for el in list(ch_root):
            if _local(el.tag) == "BaseForm":
                ch_root.remove(el)

        if base_form.is_file():
            try:
                base_tree = ET.parse(base_form)
                base_root = base_tree.getroot()
                # Copy base form children into BaseForm wrapper
                ns = base_root.tag.split("}")[0][1:] if base_root.tag.startswith("{") else ""
                tag = f"{{{ns}}}BaseForm" if ns else "BaseForm"
                base_form_el = ET.Element(tag)
                for child in list(base_root):
                    if _local(child.tag) == "BaseForm":
                        continue
                    base_form_el.append(child)
                ch_root.append(base_form_el)
            except ET.ParseError as exc:
                warnings.append(f"Base form parse error {fc.rel_path}: {exc}")

        ext_form.parent.mkdir(parents=True, exist_ok=True)
        ch_tree.write(ext_form, encoding="utf-8", xml_declaration=True)
        _ensure_bom(ext_form)
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

        # Prefer keeping original name if already prefixed; else warn — renaming XML is complex
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

        _register_child_object(extension_root, ref.type_name, ref.object_name)
    return warnings


def _register_child_object(extension_root: Path, type_name: str, object_name: str) -> None:
    cfg = extension_root / "Configuration.xml"
    tree = ET.parse(cfg)
    root = tree.getroot()
    child_objects = None
    for el in root.iter():
        if _local(el.tag) == "ChildObjects":
            child_objects = el
            break
    if child_objects is None:
        return
    # avoid duplicates
    for ch in child_objects:
        if _local(ch.tag) == type_name and (ch.text or "").strip() == object_name:
            return
    tag = f"{{{MD_NS}}}{type_name}"
    # detect namespace from existing children
    if len(child_objects):
        sample = child_objects[0].tag
        if sample.startswith("{"):
            ns = sample.split("}")[0][1:]
            tag = f"{{{ns}}}{type_name}"
        else:
            tag = type_name
    else:
        tag = type_name
    el = ET.Element(tag)
    el.text = object_name
    child_objects.append(el)
    tree.write(cfg, encoding="utf-8", xml_declaration=True)
    _ensure_bom(cfg)


def _ensure_bom(path: Path) -> None:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return
    # ElementTree write may produce utf-8 without BOM
    text = data.decode("utf-8")
    if text.startswith("<?xml"):
        path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))


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
    warnings.extend(create_own_objects(changes_root, extension_root, inventory, name_prefix))
    return warnings
