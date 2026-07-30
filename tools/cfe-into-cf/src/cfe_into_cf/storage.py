"""Формирование Object list XML и операции с хранилищем."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from cfe_into_cf.inventory import ExtensionInventory, ObjectRef

OBJECTS_NS = "http://v8.1c.ru/8.3/config/objects"


def build_objects_xml(
    objects: list[ObjectRef],
    *,
    include_configuration: bool = False,
    configuration_name: str = "Configuration",
) -> str:
    """Build Designer Object list file content."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<Objects xmlns="{OBJECTS_NS}" version="1.0">',
    ]
    if include_configuration:
        lines.append(f'  <Configuration includeChildObjects="false" name="{escape(configuration_name)}"/>')
    for obj in objects:
        lines.append(
            f'  <Object fullName="{escape(obj.storage_name)}" includeChildObjects="true"/>'
        )
    lines.append("</Objects>")
    lines.append("")
    return "\n".join(lines)


def write_objects_file(
    path: Path | str,
    objects: list[ObjectRef],
    *,
    include_configuration: bool = False,
    configuration_name: str = "Configuration",
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = build_objects_xml(
        objects,
        include_configuration=include_configuration,
        configuration_name=configuration_name,
    )
    out.write_text(text, encoding="utf-8-sig")
    return out


def objects_for_lock(inventory: ExtensionInventory) -> tuple[list[ObjectRef], bool]:
    """Return (objects to lock, need_configuration_root).

    Configuration root is required when new Own objects are added
    (ChildObjects of the configuration tree change).
    """
    need_root = bool(inventory.own_objects)
    targets = list(inventory.lock_targets)
    # Also lock parents of forms that are own additions under adopted objects —
    # already covered by lock_targets via adopted_objects.
    return targets, need_root


def write_load_list_file(path: Path | str, relative_paths: list[str]) -> Path:
    """Write -listFile for LoadConfigFromFiles (one relative path per line)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [p.replace("\\", "/") for p in relative_paths]
    out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out
