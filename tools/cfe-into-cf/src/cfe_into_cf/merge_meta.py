"""Перенос метаданных расширения в выгрузку основной конфигурации."""

from __future__ import annotations

import contextlib
import copy
import re
import shutil
from pathlib import Path

from lxml import etree

from cfe_into_cf.inventory import (
    TYPE_TO_DIR,
    ExtensionInventory,
    ObjectRef,
    object_xml_rel,
)
from cfe_into_cf.merge_bsl import merge_extension_bsl_into_main, read_text, write_text_bom

MD_NS = "http://v8.1c.ru/8.3/MDClasses"
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

_OBJECT_BELONGING_RE = re.compile(
    r"\s*<ObjectBelonging>\s*(Adopted|Own)\s*</ObjectBelonging>\s*\n?",
    re.IGNORECASE,
)
_EXTENDED_CONFIG_RE = re.compile(
    r"\s*<ExtendedConfigurationObject>[^<]*</ExtendedConfigurationObject>\s*\n?",
    re.IGNORECASE,
)


def _localname(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _parse_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False)
    return etree.parse(str(path), parser)


def _object_element(root: etree._Element) -> etree._Element | None:
    ln = _localname(root.tag)
    if ln == "MetaDataObject":
        for child in root:
            if isinstance(child.tag, str):
                return child
        return None
    return root


def _child_objects(obj_el: etree._Element) -> etree._Element | None:
    for child in obj_el:
        if _localname(child.tag) == "ChildObjects":
            return child
    return None


def _ensure_child_objects(obj_el: etree._Element) -> etree._Element:
    co = _child_objects(obj_el)
    if co is not None:
        return co
    co = etree.SubElement(obj_el, f"{{{MD_NS}}}ChildObjects")
    return co


def _child_names(co: etree._Element) -> set[str]:
    names: set[str] = set()
    for child in co:
        ln = _localname(child.tag)
        if ln in CHILD_PROPERTY_TAGS:
            # Prefer Name child, else text
            name_el = None
            for sub in child.iter():
                if _localname(sub.tag) == "Name" and sub.text:
                    name_el = sub
                    break
            if name_el is not None and name_el.text:
                names.add(f"{ln}:{name_el.text.strip()}")
            elif child.text and child.text.strip():
                names.add(f"{ln}:{child.text.strip()}")
    return names


def _save_xml(path: Path, tree: etree._ElementTree) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = etree.tostring(
        tree.getroot(),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )
    # Designer dumps use UTF-8 BOM
    path.write_bytes(b"\xef\xbb\xbf" + xml_bytes)


def strip_extension_markers(xml_text: str) -> str:
    """Remove ObjectBelonging / ExtendedConfigurationObject from own-object XML."""
    text = _OBJECT_BELONGING_RE.sub("\n", xml_text)
    text = _EXTENDED_CONFIG_RE.sub("\n", text)
    return text


def copy_own_object(
    extension_root: Path,
    main_root: Path,
    obj: ObjectRef,
) -> list[str]:
    """Copy an Own object tree from extension dump into main dump."""
    warnings: list[str] = []
    folder = TYPE_TO_DIR.get(obj.type_name)
    if not folder:
        warnings.append(f"Неизвестный тип объекта: {obj.type_name}")
        return warnings

    src_xml = extension_root / folder / f"{obj.object_name}.xml"
    dst_xml = main_root / folder / f"{obj.object_name}.xml"
    if dst_xml.is_file():
        warnings.append(f"Объект уже есть в основной конфигурации: {obj.key}")
        return warnings

    if src_xml.is_file():
        text = strip_extension_markers(src_xml.read_text(encoding="utf-8-sig"))
        dst_xml.parent.mkdir(parents=True, exist_ok=True)
        dst_xml.write_text(text, encoding="utf-8-sig", newline="\r\n")

    src_dir = extension_root / folder / obj.object_name
    dst_dir = main_root / folder / obj.object_name
    if src_dir.is_dir():
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)

    # Register in Configuration.xml ChildObjects if possible
    _ensure_configuration_child(main_root, obj, warnings)
    return warnings


def _ensure_configuration_child(main_root: Path, obj: ObjectRef, warnings: list[str]) -> None:
    cfg = main_root / "Configuration.xml"
    if not cfg.is_file():
        warnings.append("Configuration.xml основной конфигурации не найден — ChildObjects не обновлён")
        return
    try:
        tree = _parse_xml(cfg)
    except etree.XMLSyntaxError as exc:
        warnings.append(f"Не удалось разобрать Configuration.xml: {exc}")
        return
    root = tree.getroot()
    conf_el = _object_element(root)
    if conf_el is None:
        warnings.append("Не найден элемент Configuration в Configuration.xml")
        return
    co = _ensure_child_objects(conf_el)
    tag = obj.type_name
    # Check existing
    for child in co:
        if _localname(child.tag) == tag and (child.text or "").strip() == obj.object_name:
            return
    el = etree.SubElement(co, f"{{{MD_NS}}}{tag}")
    el.text = obj.object_name
    _save_xml(cfg, tree)


def merge_adopted_child_objects(
    extension_root: Path,
    main_root: Path,
    obj: ObjectRef,
) -> list[str]:
    """Merge ChildObjects (attributes, forms, …) from adopted extension object into main."""
    warnings: list[str] = []
    try:
        rel = object_xml_rel(obj.type_name, obj.object_name)
    except ValueError as exc:
        warnings.append(str(exc))
        return warnings

    ext_xml = extension_root / rel
    main_xml = main_root / rel
    if not ext_xml.is_file():
        return warnings
    if not main_xml.is_file():
        warnings.append(f"В основной конфигурации нет объекта для слияния: {obj.key}")
        return warnings

    try:
        ext_tree = _parse_xml(ext_xml)
        main_tree = _parse_xml(main_xml)
    except etree.XMLSyntaxError as exc:
        warnings.append(f"XML parse error for {obj.key}: {exc}")
        return warnings

    ext_obj = _object_element(ext_tree.getroot())
    main_obj = _object_element(main_tree.getroot())
    if ext_obj is None or main_obj is None:
        warnings.append(f"Не найден корневой элемент объекта: {obj.key}")
        return warnings

    ext_co = _child_objects(ext_obj)
    if ext_co is None:
        return warnings

    main_co = _ensure_child_objects(main_obj)
    existing = _child_names(main_co)
    added = 0
    for child in list(ext_co):
        ln = _localname(child.tag)
        if ln not in CHILD_PROPERTY_TAGS:
            continue
        name_el = None
        for sub in child.iter():
            if _localname(sub.tag) == "Name" and sub.text:
                name_el = sub
                break
        name = name_el.text.strip() if name_el is not None and name_el.text else (child.text or "").strip()
        key = f"{ln}:{name}"
        if key in existing:
            continue
        main_co.append(copy.deepcopy(child))
        existing.add(key)
        added += 1

    if added:
        _save_xml(main_xml, main_tree)

    # Copy form / template files that exist only in extension
    folder = TYPE_TO_DIR[obj.type_name]
    for sub in ("Forms", "Templates"):
        src = extension_root / folder / obj.object_name / sub
        dst = main_root / folder / obj.object_name / sub
        if not src.is_dir():
            continue
        for entry in src.iterdir():
            name = entry.name
            target = dst / name
            if target.exists():
                continue
            dst.mkdir(parents=True, exist_ok=True)
            if entry.is_dir():
                shutil.copytree(entry, target)
            else:
                shutil.copy2(entry, target)
            added += 1

    return warnings


def merge_extension_into_main(
    extension_root: Path | str,
    main_root: Path | str,
    inventory: ExtensionInventory,
) -> tuple[list[str], list[str]]:
    """Apply full metadata + BSL merge. Returns (touched_relative_paths, warnings)."""
    ext = Path(extension_root)
    main = Path(main_root)
    warnings: list[str] = []
    touched: set[str] = set()

    for obj in inventory.own_objects:
        w = copy_own_object(ext, main, obj)
        warnings.extend(w)
        folder = TYPE_TO_DIR.get(obj.type_name)
        if folder:
            touched.add(f"{folder}/{obj.object_name}.xml")
            obj_dir = main / folder / obj.object_name
            if obj_dir.is_dir():
                for p in obj_dir.rglob("*"):
                    if p.is_file():
                        touched.add(p.relative_to(main).as_posix())
        touched.add("Configuration.xml")

    for obj in inventory.adopted_objects:
        w = merge_adopted_child_objects(ext, main, obj)
        warnings.extend(w)
        with contextlib.suppress(ValueError):
            touched.add(object_xml_rel(obj.type_name, obj.object_name))

    for mod in inventory.bsl_modules:
        ext_path = ext / mod.rel_path
        main_path = main / mod.rel_path
        if not ext_path.is_file():
            continue
        main_src = read_text(str(main_path)) if main_path.is_file() else None
        ext_src = read_text(str(ext_path))
        merged, w = merge_extension_bsl_into_main(main_src, ext_src)
        warnings.extend(w)
        if merged != (main_src or ""):
            write_text_bom(str(main_path), merged)
            touched.add(mod.rel_path.replace("\\", "/"))

    return sorted(touched), warnings
