"""Apply BSL patches into extension module files."""

from __future__ import annotations

from pathlib import Path

from cfe_tools.bsl_methods import build_extension_module, read_text, write_text_bom
from cfe_tools.inventory import Inventory


def extension_bsl_path(extension_root: Path, rel_path: str) -> Path:
    """Map dump-relative BSL path to extension path (same relative layout)."""
    return extension_root / rel_path


def apply_bsl_patches(
    config_root: Path,
    changes_root: Path,
    extension_root: Path,
    inventory: Inventory,
    name_prefix: str,
) -> list[str]:
    warnings: list[str] = []
    for fc in inventory.bsl_files:
        if fc.kind not in ("added", "modified"):
            continue
        changed_path = Path(fc.change_abs) if fc.change_abs else changes_root / fc.rel_path
        base_path = Path(fc.base_abs) if fc.base_abs else config_root / fc.rel_path
        base_src = read_text(str(base_path)) if base_path.is_file() else None
        changed_src = read_text(str(changed_path))
        module_text, w = build_extension_module(base_src, changed_src, name_prefix)
        warnings.extend(w)
        if not module_text.strip():
            warnings.append(f"No transferable methods in {fc.rel_path}")
            continue
        out = extension_bsl_path(extension_root, fc.rel_path)
        write_text_bom(str(out), module_text)
    return warnings
