"""CLI entrypoint: cfe-from-diff."""

from __future__ import annotations

import argparse
import sys

from cfe_tools.ibcmd_build import IbcmdError
from cfe_tools.orchestrator import run_cfe_from_diff
from cfe_tools.vendor.cfe_borrow import CfeBorrowError
from cfe_tools.vendor.cfe_init import CfeInitError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cfe-from-diff",
        description=(
            "Create a 1C configuration extension from Designer dump diffs and optionally build .cfe via ibcmd."
        ),
    )
    p.add_argument("--name", required=True, help="Extension name (e.g. K7_20486)")
    p.add_argument("--config", required=True, help="Base configuration XML dump directory")
    p.add_argument(
        "--changes",
        required=True,
        help="Changed files tree (same relative paths as config dump)",
    )
    p.add_argument("--output", required=True, help="Output directory for extension XML sources")
    p.add_argument("--cfe", default=None, help="Output .cfe path (required unless --skip-build)")
    p.add_argument(
        "--ib-path",
        default=None,
        help="File infobase path with base CF already loaded (required unless --skip-build)",
    )
    p.add_argument("--ibcmd", default=None, help="Path to ibcmd executable")
    p.add_argument("--user", default=None, help="Infobase user")
    p.add_argument("--password", default=None, help="Infobase password")
    p.add_argument(
        "--purpose",
        default="Customization",
        choices=["Patch", "Customization", "AddOn"],
        help="ConfigurationExtensionPurpose",
    )
    p.add_argument("--prefix", default=None, help="NamePrefix (default: <name>_)")
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="Only generate XML sources, do not call ibcmd",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventory only; do not write extension or build",
    )
    p.add_argument("--report", default=None, help="Write JSON report to this path")
    p.add_argument(
        "--force",
        action="store_true",
        help="Remove existing --output if it already contains Configuration.xml",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    stdout = getattr(sys.stdout, "reconfigure", None)
    stderr = getattr(sys.stderr, "reconfigure", None)
    if callable(stdout):
        stdout(encoding="utf-8")
    if callable(stderr):
        stderr(encoding="utf-8")

    args = build_parser().parse_args(argv)
    try:
        report = run_cfe_from_diff(
            name=args.name,
            config=args.config,
            changes=args.changes,
            output=args.output,
            cfe=args.cfe,
            ib_path=args.ib_path,
            ibcmd=args.ibcmd,
            user=args.user,
            password=args.password,
            purpose=args.purpose,
            prefix=args.prefix,
            skip_build=args.skip_build,
            dry_run=args.dry_run,
            report_path=args.report,
            force_output=args.force,
            on_progress=lambda msg: print(f"[…] {msg}"),
        )
    except (CfeInitError, CfeBorrowError, IbcmdError, FileNotFoundError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print("=== cfe-from-diff summary ===")
    print(f"  Output:   {report.output}")
    print(f"  Borrowed: {len(report.borrowed)}")
    print(f"  New:      {len(report.new_objects)}")
    print(f"  BSL:      {len(report.bsl_files)}")
    print(f"  Templates:{len(report.template_files)}")
    print(f"  Built:    {report.built}")
    if report.cfe:
        print(f"  CFE:      {report.cfe}")
    for w in report.warnings:
        print(f"  [WARN] {w}")
    # Validate remarks are warnings; fail only when build was required and did not run
    if args.dry_run or args.skip_build:
        return 0
    return 0 if report.built else 1


if __name__ == "__main__":
    raise SystemExit(main())
