"""Orchestrate diff → extension XML → optional ibcmd .cfe build."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from cfe_tools.apply_patches import apply_bsl_patches
from cfe_tools.ibcmd_build import IbcmdConfig, IbcmdError, build_cfe
from cfe_tools.inventory import build_inventory
from cfe_tools.meta_transfer import apply_metadata_transfers
from cfe_tools.vendor.cfe_borrow import CfeBorrowError, borrow_objects
from cfe_tools.vendor.cfe_init import CfeInitError, create_extension
from cfe_tools.vendor.cfe_validate import validate_extension


@dataclass
class RunReport:
    name: str
    config: str
    changes: str
    output: str
    cfe: str | None = None
    borrowed: list[str] = field(default_factory=list)
    new_objects: list[str] = field(default_factory=list)
    bsl_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validate_errors: int = 0
    built: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _read_name_prefix(extension_root: Path) -> str:
    cfg = extension_root / "Configuration.xml"
    tree = ET.parse(cfg)
    root = tree.getroot()
    ns = {"md": "http://v8.1c.ru/8.3/MDClasses"}
    node = root.find(".//md:Configuration/md:Properties/md:NamePrefix", ns)
    if node is not None and node.text:
        return node.text
    # fallback without ns
    for el in root.iter():
        if el.tag.endswith("NamePrefix") and el.text:
            return el.text
    return "Ext_"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _assert_safe_output_wipe(output_root: Path, *protected: Path) -> None:
    """Refuse rmtree when output equals or contains a protected path (config/changes)."""
    out = output_root.resolve()
    if out.anchor and out == Path(out.anchor):
        raise CfeInitError(f"Refusing to delete filesystem root as output: {out}")
    for raw in protected:
        prot = raw.resolve()
        if out == prot:
            raise CfeInitError(f"Refusing to delete output that equals a protected path: {out}")
        if _is_relative_to(prot, out):
            raise CfeInitError(f"Refusing to delete output that contains protected path {prot}: {out}")


def run_cfe_from_diff(
    name: str,
    config: str | Path,
    changes: str | Path,
    output: str | Path,
    cfe: str | Path | None = None,
    ib_path: str | Path | None = None,
    ibcmd: str | None = None,
    user: str | None = None,
    password: str | None = None,
    purpose: str = "Customization",
    prefix: str | None = None,
    skip_build: bool = False,
    dry_run: bool = False,
    report_path: str | Path | None = None,
    force_output: bool = False,
) -> RunReport:
    config_root = Path(config).resolve()
    changes_root = Path(changes).resolve()
    output_root = Path(output).resolve()

    inventory = build_inventory(config_root, changes_root)
    report = RunReport(
        name=name,
        config=str(config_root),
        changes=str(changes_root),
        output=str(output_root),
        cfe=str(Path(cfe).resolve()) if cfe else None,
        borrowed=[o.borrow_spec for o in inventory.borrow_objects],
        new_objects=[o.borrow_spec for o in inventory.new_objects],
        bsl_files=[f.rel_path for f in inventory.bsl_files],
        warnings=list(inventory.warnings),
    )

    if dry_run:
        print("=== cfe-from-diff dry-run ===")
        print(f"Changed files: {len(inventory.changed_files)}")
        print(f"Borrow: {report.borrowed}")
        print(f"New objects: {report.new_objects}")
        print(f"BSL: {report.bsl_files}")
        for w in report.warnings:
            print(f"[WARN] {w}")
        _write_report(report, report_path)
        return report

    if not inventory.changed_files and not inventory.new_objects:
        report.warnings.append("No differences found between config and changes")
        _write_report(report, report_path)
        return report

    if output_root.exists() and (output_root / "Configuration.xml").exists():
        if force_output:
            _assert_safe_output_wipe(output_root, config_root, changes_root)
            shutil.rmtree(output_root)
        else:
            raise CfeInitError(
                f"Output already contains Configuration.xml: {output_root}. Use a clean directory or force_output=True."
            )

    name_prefix = prefix or f"{name}_"
    create_extension(
        name=name,
        output_dir=str(output_root),
        name_prefix=name_prefix,
        purpose=purpose,
        config_path=str(config_root),
        no_role=True,
    )
    name_prefix = _read_name_prefix(output_root)

    # Borrow existing objects (forms with BorrowMainAttribute when form changes exist)
    form_specs = [o.borrow_spec for o in inventory.borrow_objects if o.form_name]
    object_specs = [o.borrow_spec for o in inventory.borrow_objects if not o.form_name]

    try:
        if object_specs:
            borrow_objects(str(output_root), str(config_root), object_specs)
        if form_specs:
            borrow_objects(
                str(output_root),
                str(config_root),
                form_specs,
                borrow_main_attribute="Form",
            )
    except CfeBorrowError as exc:
        report.warnings.append(str(exc))
        raise

    meta_warnings = apply_metadata_transfers(config_root, changes_root, output_root, inventory, name_prefix)
    report.warnings.extend(meta_warnings)

    bsl_warnings = apply_bsl_patches(config_root, changes_root, output_root, inventory, name_prefix)
    report.warnings.extend(bsl_warnings)

    report.validate_errors = validate_extension(str(output_root))
    if report.validate_errors:
        report.warnings.append(f"cfe-validate reported errors (exit={report.validate_errors})")

    if not skip_build:
        if report.validate_errors:
            report.warnings.append(f"Skipping ibcmd build due to {report.validate_errors} validate error(s)")
        else:
            if not cfe or not ib_path:
                raise IbcmdError("Building .cfe requires --cfe and --ib-path (or pass --skip-build)")
            build_cfe(
                IbcmdConfig(
                    ib_path=str(Path(ib_path).resolve()),
                    extension_name=name,
                    extension_src=str(output_root),
                    cfe_path=str(Path(cfe).resolve()),
                    name_prefix=name_prefix,
                    purpose=purpose,
                    ibcmd=ibcmd,
                    user=user,
                    password=password,
                )
            )
            report.built = True
            report.cfe = str(Path(cfe).resolve())

    _write_report(report, report_path)
    return report


def _write_report(report: RunReport, report_path: str | Path | None) -> None:
    if not report_path:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] Report: {path}")
