"""Инвентаризация содержимого расширения конфигурации."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

# Designer hierarchical dump folder name -> singular type
DIR_TO_TYPE = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "Enums": "Enum",
    "CommonModules": "CommonModule",
    "Reports": "Report",
    "DataProcessors": "DataProcessor",
    "ExchangePlans": "ExchangePlan",
    "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "BusinessProcesses": "BusinessProcess",
    "Tasks": "Task",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "CalculationRegisters": "CalculationRegister",
    "Constants": "Constant",
    "CommonForms": "CommonForm",
    "CommonCommands": "CommonCommand",
    "CommonTemplates": "CommonTemplate",
    "CommonPictures": "CommonPicture",
    "Roles": "Role",
    "Subsystems": "Subsystem",
    "SessionParameters": "SessionParameter",
    "FilterCriteria": "FilterCriterion",
    "EventSubscriptions": "EventSubscription",
    "ScheduledJobs": "ScheduledJob",
    "FunctionalOptions": "FunctionalOption",
    "FunctionalOptionsParameters": "FunctionalOptionsParameter",
    "DefinedTypes": "DefinedType",
    "SettingsStorages": "SettingsStorage",
    "CommandGroups": "CommandGroup",
    "WebServices": "WebService",
    "HTTPServices": "HTTPService",
    "WSReferences": "WSReference",
    "XDTOPackages": "XDTOPackage",
    "StyleItems": "StyleItem",
    "Styles": "Style",
    "Languages": "Language",
    "Interfaces": "Interface",
    "DocumentJournals": "DocumentJournal",
    "Sequences": "Sequence",
    "DocumentNumerators": "DocumentNumerator",
    "ExternalDataSources": "ExternalDataSource",
}

TYPE_TO_DIR = {v: k for k, v in DIR_TO_TYPE.items()}

SKIP_NAMES = {
    "ConfigDumpInfo.xml",
    "Configuration.xml",
    "VERSION",
    ".git",
    ".DS_Store",
}

_OBJECT_BELONGING_RE = re.compile(
    r"<ObjectBelonging>\s*(Adopted|Own)\s*</ObjectBelonging>",
    re.IGNORECASE,
)


@dataclass
class ObjectRef:
    """Metadata object reference."""

    type_name: str
    object_name: str
    form_name: str | None = None
    template_name: str | None = None
    belonging: str = "Own"  # Own | Adopted
    rel_xml: str | None = None

    @property
    def key(self) -> str:
        if self.form_name:
            return f"{self.type_name}.{self.object_name}.Form.{self.form_name}"
        if self.template_name and self.type_name != "CommonTemplate":
            return f"{self.type_name}.{self.object_name}.Template.{self.template_name}"
        return f"{self.type_name}.{self.object_name}"

    @property
    def storage_name(self) -> str:
        """Name for Object list file: Type.ObjectName."""
        return f"{self.type_name}.{self.object_name}"


@dataclass
class BslModuleRef:
    """BSL module file inside extension dump."""

    rel_path: str
    object: ObjectRef
    has_change_and_control: bool = False
    has_new_methods: bool = False


@dataclass
class ExtensionInventory:
    """Parsed extension dump contents."""

    own_objects: list[ObjectRef] = field(default_factory=list)
    adopted_objects: list[ObjectRef] = field(default_factory=list)
    bsl_modules: list[BslModuleRef] = field(default_factory=list)
    form_files: list[str] = field(default_factory=list)
    template_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    name_prefix: str = ""
    extension_name: str = ""

    @property
    def new_objects(self) -> list[ObjectRef]:
        """Own objects that will be added to the main configuration."""
        return list(self.own_objects)

    @property
    def lock_targets(self) -> list[ObjectRef]:
        """Main-configuration objects that must be locked in storage."""
        seen: dict[str, ObjectRef] = {}
        for obj in self.adopted_objects:
            seen[obj.storage_name] = ObjectRef(
                type_name=obj.type_name,
                object_name=obj.object_name,
                belonging="Adopted",
            )
        for mod in self.bsl_modules:
            parent = mod.object
            seen[parent.storage_name] = ObjectRef(
                type_name=parent.type_name,
                object_name=parent.object_name,
                belonging=parent.belonging,
            )
        return list(seen.values())


def _localname(tag: str | bytes | object) -> str:
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _read_belonging(xml_path: Path) -> str:
    try:
        text = xml_path.read_text(encoding="utf-8-sig")
    except OSError:
        return "Own"
    m = _OBJECT_BELONGING_RE.search(text)
    if m:
        return m.group(1).capitalize() if m.group(1).lower() != "own" else "Own"
    # Adopted is explicit; missing tag usually means Own in extension dumps
    if "Adopted" in text or "adopted" in text.lower():
        return "Adopted"
    return "Own"


def _parse_name_prefix(config_xml: Path) -> tuple[str, str]:
    """Return (extension_name, name_prefix) from Configuration.xml."""
    if not config_xml.is_file():
        return "", ""
    try:
        tree = etree.parse(str(config_xml))
    except etree.XMLSyntaxError:
        return "", ""
    root = tree.getroot()
    name = ""
    prefix = ""
    for el in root.iter():
        ln = _localname(el.tag)
        if ln == "Name" and el.text and not name:
            # First Name under Properties is configuration name
            parent = el.getparent()
            if parent is not None and _localname(parent.tag) == "Properties":
                name = el.text.strip()
        if ln == "NamePrefix" and el.text:
            prefix = el.text.strip()
    return name, prefix


def map_path_to_object(rel_path: str, belonging: str = "Own") -> ObjectRef | None:
    parts = Path(rel_path).parts
    if not parts:
        return None
    top = parts[0]
    type_name = DIR_TO_TYPE.get(top)
    if not type_name:
        return None
    if len(parts) < 2:
        return None
    object_name = Path(parts[1]).stem if parts[1].endswith(".xml") and len(parts) == 2 else parts[1]

    if len(parts) >= 4 and parts[2] == "Forms":
        form_name = Path(parts[3]).stem
        return ObjectRef(
            type_name=type_name,
            object_name=object_name,
            form_name=form_name,
            belonging=belonging,
        )

    if len(parts) >= 4 and parts[2] == "Templates":
        template_name = Path(parts[3]).stem
        return ObjectRef(
            type_name=type_name,
            object_name=object_name,
            template_name=template_name,
            belonging=belonging,
        )

    if top == "CommonTemplates":
        return ObjectRef(
            type_name=type_name,
            object_name=object_name,
            template_name=object_name,
            belonging=belonging,
        )

    return ObjectRef(type_name=type_name, object_name=object_name, belonging=belonging)


def object_xml_rel(type_name: str, object_name: str) -> str:
    folder = TYPE_TO_DIR.get(type_name)
    if not folder:
        raise ValueError(f"Unknown type: {type_name}")
    return f"{folder}/{object_name}.xml"


def _iter_dump_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES and not d.startswith(".")]
        for name in files:
            if name in SKIP_NAMES or name.startswith("."):
                continue
            result.append(Path(dirpath) / name)
    return result


def _bsl_has_change_and_control(text: str) -> bool:
    low = text.casefold()
    return "&изменениеиконтроль" in low or "&changeandvalidate" in low


_METHOD_START = re.compile(
    r"^\s*(Процедура|Функция|Procedure|Function)\s+",
    re.MULTILINE | re.IGNORECASE,
)


def inventory_extension(extension_root: Path | str) -> ExtensionInventory:
    """Scan hierarchical extension dump and classify Own / Adopted content."""
    root = Path(extension_root)
    if not (root / "Configuration.xml").is_file():
        raise FileNotFoundError(f"Configuration.xml не найден в выгрузке расширения: {root}")

    inv = ExtensionInventory()
    inv.extension_name, inv.name_prefix = _parse_name_prefix(root / "Configuration.xml")

    seen_own: dict[str, ObjectRef] = {}
    seen_adopted: dict[str, ObjectRef] = {}

    # Top-level object XML files
    for type_dir, type_name in DIR_TO_TYPE.items():
        folder = root / type_dir
        if not folder.is_dir():
            continue
        for xml_file in folder.glob("*.xml"):
            belonging = _read_belonging(xml_file)
            ref = ObjectRef(
                type_name=type_name,
                object_name=xml_file.stem,
                belonging=belonging,
                rel_xml=f"{type_dir}/{xml_file.name}",
            )
            if belonging.lower() == "adopted":
                seen_adopted[ref.key] = ref
            else:
                seen_own[ref.key] = ref

        # Nested forms / templates under object folders
        for obj_dir in folder.iterdir():
            if not obj_dir.is_dir():
                continue
            obj_xml = folder / f"{obj_dir.name}.xml"
            belonging = _read_belonging(obj_xml) if obj_xml.is_file() else "Own"
            parent = ObjectRef(
                type_name=type_name,
                object_name=obj_dir.name,
                belonging=belonging,
                rel_xml=f"{type_dir}/{obj_dir.name}.xml" if obj_xml.is_file() else None,
            )
            if belonging.lower() == "adopted":
                seen_adopted.setdefault(parent.key, parent)
            elif parent.key not in seen_own and parent.key not in seen_adopted:
                seen_own.setdefault(parent.key, parent)

            forms_dir = obj_dir / "Forms"
            if forms_dir.is_dir():
                for form_entry in forms_dir.iterdir():
                    form_name = form_entry.stem if form_entry.is_file() else form_entry.name
                    rel = f"{type_dir}/{obj_dir.name}/Forms/{form_name}"
                    inv.form_files.append(rel)
                    if belonging.lower() == "adopted":
                        seen_adopted.setdefault(parent.key, parent)

            templates_dir = obj_dir / "Templates"
            if templates_dir.is_dir():
                for tmpl in templates_dir.iterdir():
                    tmpl_name = tmpl.stem if tmpl.is_file() else tmpl.name
                    inv.template_files.append(f"{type_dir}/{obj_dir.name}/Templates/{tmpl_name}")
                    if belonging.lower() == "adopted":
                        seen_adopted.setdefault(parent.key, parent)

    inv.own_objects = sorted(seen_own.values(), key=lambda o: o.key)
    inv.adopted_objects = sorted(seen_adopted.values(), key=lambda o: o.key)

    # BSL modules
    for path in _iter_dump_files(root):
        if path.suffix.lower() != ".bsl":
            continue
        rel = path.relative_to(root).as_posix()
        # Resolve parent object belonging from object xml if possible
        parts = Path(rel).parts
        belonging = "Own"
        obj_ref = map_path_to_object(rel, belonging)
        if obj_ref is None:
            inv.warnings.append(f"Не удалось сопоставить BSL с объектом: {rel}")
            continue
        type_dir = parts[0]
        obj_xml = root / type_dir / f"{obj_ref.object_name}.xml"
        if obj_xml.is_file():
            belonging = _read_belonging(obj_xml)
            obj_ref.belonging = belonging
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            inv.warnings.append(f"Не удалось прочитать {rel}: {exc}")
            continue
        has_cc = _bsl_has_change_and_control(text)
        # Heuristic: methods without interceptor may be new own methods in adopted module
        has_methods = bool(_METHOD_START.search(text))
        inv.bsl_modules.append(
            BslModuleRef(
                rel_path=rel,
                object=obj_ref,
                has_change_and_control=has_cc,
                has_new_methods=has_methods and not has_cc,
            )
        )

    return inv


def format_new_objects_alert(objects: list[ObjectRef]) -> str:
    """Loud CLI alert text for new (Own) objects being added to main CF."""
    lines = [
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
        "  ВНИМАНИЕ: в основную конфигурацию будут ДОБАВЛЕНЫ",
        "  новые объекты метаданных (рискованная операция):",
    ]
    for obj in objects:
        lines.append(f"    - {obj.key}")
    lines.append(f"  Всего: {len(objects)}")
    lines.append("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    return "\n".join(lines)
