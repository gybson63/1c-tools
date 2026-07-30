"""Inventory differences between base configuration dump and changed files."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# Designer hierarchical dump folder name -> singular type used by cfe-borrow
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

SKIP_NAMES = {
    "ConfigDumpInfo.xml",
    "Configuration.xml",
    "VERSION",
    ".git",
    ".DS_Store",
}


@dataclass
class FileChange:
    """One differing file relative to config root."""

    rel_path: str
    kind: str  # added | modified | deleted | unchanged
    change_abs: str | None = None
    base_abs: str | None = None


@dataclass
class ObjectRef:
    """Metadata object reference for borrowing."""

    type_name: str  # Catalog
    object_name: str
    form_name: str | None = None
    template_name: str | None = None

    @property
    def borrow_spec(self) -> str:
        if self.form_name:
            return f"{self.type_name}.{self.object_name}.Form.{self.form_name}"
        return f"{self.type_name}.{self.object_name}"

    @property
    def key(self) -> str:
        return self.borrow_spec


@dataclass
class TemplateRef:
    """Object template (СКД / макет) under Templates/ or a CommonTemplate body."""

    type_dir: str
    object_name: str
    template_name: str
    is_common: bool = False

    @property
    def key(self) -> str:
        if self.is_common:
            return f"CommonTemplate.{self.template_name}"
        return f"{self.type_dir}/{self.object_name}/Templates/{self.template_name}"


@dataclass
class Inventory:
    files: list[FileChange] = field(default_factory=list)
    borrow_objects: list[ObjectRef] = field(default_factory=list)
    new_objects: list[ObjectRef] = field(default_factory=list)
    bsl_files: list[FileChange] = field(default_factory=list)
    form_xml_files: list[FileChange] = field(default_factory=list)
    object_xml_files: list[FileChange] = field(default_factory=list)
    template_files: list[FileChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def changed_files(self) -> list[FileChange]:
        return [f for f in self.files if f.kind in ("added", "modified")]


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_change_files(changes_root: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(changes_root):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES and not d.startswith(".")]
        for name in files:
            if name in SKIP_NAMES or name.startswith("."):
                continue
            yield Path(root) / name


def map_path_to_object(rel_path: str) -> ObjectRef | None:
    """Map relative dump path to metadata object / form / template."""
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

    # Catalogs/Name/Forms/FormName/...
    if len(parts) >= 4 and parts[2] == "Forms":
        form_token = parts[3]
        form_name = Path(form_token).stem
        return ObjectRef(type_name=type_name, object_name=object_name, form_name=form_name)

    # Catalogs/Name/Templates/TemplateName/...
    if len(parts) >= 4 and parts[2] == "Templates":
        template_name = Path(parts[3]).stem
        return ObjectRef(
            type_name=type_name,
            object_name=object_name,
            template_name=template_name,
        )

    # CommonForms/Name/...
    if top == "CommonForms":
        return ObjectRef(type_name=type_name, object_name=object_name)

    # CommonTemplates/Name/... — object itself is the template
    if top == "CommonTemplates":
        return ObjectRef(type_name=type_name, object_name=object_name, template_name=object_name)

    return ObjectRef(type_name=type_name, object_name=object_name)


def map_path_to_template(rel_path: str) -> TemplateRef | None:
    """Map dump path to a template (nested object template or CommonTemplate body)."""
    parts = Path(rel_path).parts
    if not parts:
        return None

    # CommonTemplates/Name.xml or CommonTemplates/Name/Ext/Template.*
    if parts[0] == "CommonTemplates" and len(parts) >= 2:
        name = Path(parts[1]).stem
        lower = rel_path.lower().replace("\\", "/")
        if lower.endswith(".xml") and len(parts) == 2:
            return TemplateRef("CommonTemplates", name, name, is_common=True)
        if "/ext/" in lower:
            return TemplateRef("CommonTemplates", name, name, is_common=True)
        return None

    # TypeDir/Object/Templates/Name.xml or .../Templates/Name/Ext/...
    if len(parts) >= 4 and parts[2] == "Templates":
        type_dir = parts[0]
        if type_dir not in DIR_TO_TYPE:
            return None
        object_name = parts[1]
        template_name = Path(parts[3]).stem
        return TemplateRef(type_dir, object_name, template_name, is_common=False)

    return None


def object_exists_in_config(config_root: Path, ref: ObjectRef) -> bool:
    dir_name = None
    for folder, tname in DIR_TO_TYPE.items():
        if tname == ref.type_name:
            dir_name = folder
            break
    if not dir_name:
        return False
    meta = config_root / dir_name / f"{ref.object_name}.xml"
    return meta.is_file()


def build_inventory(config_root: str | Path, changes_root: str | Path) -> Inventory:
    """Compare changes tree against base configuration dump."""
    config_root = Path(config_root).resolve()
    changes_root = Path(changes_root).resolve()
    inv = Inventory()

    if not config_root.is_dir():
        raise FileNotFoundError(f"Config path not found: {config_root}")
    if not changes_root.is_dir():
        raise FileNotFoundError(f"Changes path not found: {changes_root}")

    seen_borrow: dict[str, ObjectRef] = {}
    seen_new: dict[str, ObjectRef] = {}

    for change_path in _iter_change_files(changes_root):
        rel = change_path.relative_to(changes_root).as_posix()
        base_path = config_root / rel
        if not base_path.exists():
            kind = "added"
            base_abs = None
        elif _file_digest(change_path) != _file_digest(base_path):
            kind = "modified"
            base_abs = str(base_path)
        else:
            kind = "unchanged"
            base_abs = str(base_path)

        fc = FileChange(
            rel_path=rel,
            kind=kind,
            change_abs=str(change_path),
            base_abs=base_abs,
        )
        inv.files.append(fc)
        if kind == "unchanged":
            continue

        ref = map_path_to_object(rel)
        if ref is None:
            inv.warnings.append(f"Не включён в расширение (не объект метаданных): {rel}")
            continue

        lower = rel.lower()
        if lower.endswith(".bsl"):
            inv.bsl_files.append(fc)
        elif "/forms/" in lower and lower.endswith("form.xml"):
            inv.form_xml_files.append(fc)
        elif map_path_to_template(rel) is not None:
            inv.template_files.append(fc)
        elif (
            lower.endswith(".xml")
            and "/ext/" not in lower
            and "/forms/" not in lower
            and "/templates/" not in lower
            and Path(rel).name == f"{ref.object_name}.xml"
        ):
            # object metadata xml e.g. Catalogs/X.xml
            inv.object_xml_files.append(fc)

        exists = object_exists_in_config(config_root, ref)
        if exists:
            # Prefer form-level borrow when form is involved
            parent = ObjectRef(type_name=ref.type_name, object_name=ref.object_name)
            if parent.key not in seen_borrow:
                seen_borrow[parent.key] = parent
            if ref.form_name:
                seen_borrow[ref.key] = ref
        else:
            parent = ObjectRef(type_name=ref.type_name, object_name=ref.object_name)
            seen_new[parent.key] = parent

    inv.borrow_objects = list(seen_borrow.values())
    inv.new_objects = list(seen_new.values())
    return inv
