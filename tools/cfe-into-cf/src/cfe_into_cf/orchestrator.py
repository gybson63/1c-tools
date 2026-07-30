"""Оркестратор переноса расширения в основную конфигурацию."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from cfe_into_cf.cancel import check as cancel_check
from cfe_into_cf.cancel import reset as cancel_reset
from cfe_into_cf.designer import (
    DesignerConfig,
    DesignerError,
    IbConnection,
    RepoConnection,
    dump_config_to_files,
    load_config_from_files,
    repository_commit,
    repository_lock,
    update_db_cfg,
)
from cfe_into_cf.inventory import (
    ExtensionInventory,
    format_new_objects_alert,
    inventory_extension,
)
from cfe_into_cf.merge_meta import merge_extension_into_main
from cfe_into_cf.report import RunReport
from cfe_into_cf.storage import objects_for_lock, write_load_list_file, write_objects_file

ProgressCallback = Callable[[str], None]


class NewObjectsNotAcceptedError(Exception):
    """Raised when Own objects would be added without --accept-new-objects."""

    def __init__(self, inventory: ExtensionInventory, alert_text: str) -> None:
        super().__init__(alert_text)
        self.inventory = inventory
        self.alert_text = alert_text


def _progress(cb: ProgressCallback | None, msg: str) -> None:
    if cb is not None:
        cb(msg)
    print(f"[…] {msg}")


def run_cfe_into_cf(
    *,
    extension: str,
    ib_path: str | None = None,
    ib_server: str | None = None,
    ib_ref: str | None = None,
    ib_user: str | None = None,
    ib_password: str | None = None,
    v8_path: str | None = None,
    repo_path: str | None = None,
    repo_user: str | None = None,
    repo_password: str | None = None,
    accept_new_objects: bool = False,
    dry_run: bool = False,
    skip_update_db: bool = False,
    repo_commit: bool = False,
    repo_comment: str = "",
    report_path: str | None = None,
    work_dir: str | None = None,
    # Offline / test mode: use pre-dumped trees instead of Designer dump
    extension_dump: str | None = None,
    main_dump: str | None = None,
    skip_designer: bool = False,
    on_progress: ProgressCallback | None = None,
) -> RunReport:
    """Run the extension → main configuration transfer pipeline."""
    cancel_reset()
    report = RunReport(extension=extension, dry_run=dry_run)

    repo: RepoConnection | None = None
    if repo_path:
        if not repo_user:
            raise DesignerError("При указании --repo-path нужен --repo-user")
        repo = RepoConnection(path=repo_path, user=repo_user, password=repo_password or "")

    cleanup_work = False
    if work_dir:
        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)
    else:
        work = Path(tempfile.mkdtemp(prefix="cfe-into-cf-"))
        cleanup_work = True
    report.work_dir = str(work)

    cfg = DesignerConfig(
        connection=IbConnection(
            ib_path=ib_path,
            ib_server=ib_server,
            ib_ref=ib_ref,
            user=ib_user,
            password=ib_password,
        ),
        v8_path=v8_path,
        work_dir=work,
        repo=repo,
    )

    try:
        ext_dir = Path(extension_dump) if extension_dump else work / "extension"
        main_dir = Path(main_dump) if main_dump else work / "main"

        if not skip_designer:
            if not ib_path and not (ib_server and ib_ref):
                raise DesignerError("Укажите --ib-path или --ib-server/--ib-ref")
            _progress(on_progress, f"Выгрузка расширения «{extension}»…")
            cancel_check()
            dump_config_to_files(cfg, ext_dir, extension=extension, on_progress=on_progress)
            _progress(on_progress, "Выгрузка основной конфигурации…")
            cancel_check()
            dump_config_to_files(cfg, main_dir, on_progress=on_progress)
        else:
            if not ext_dir.is_dir() or not (ext_dir / "Configuration.xml").is_file():
                raise FileNotFoundError(f"Выгрузка расширения не найдена: {ext_dir}")
            if not main_dir.is_dir() or not (main_dir / "Configuration.xml").is_file():
                raise FileNotFoundError(f"Выгрузка основной конфигурации не найдена: {main_dir}")

        _progress(on_progress, "Инвентаризация расширения…")
        cancel_check()
        inventory = inventory_extension(ext_dir)
        report.own_objects = [o.key for o in inventory.own_objects]
        report.adopted_objects = [o.key for o in inventory.adopted_objects]
        report.bsl_modules = [m.rel_path for m in inventory.bsl_modules]
        report.warnings.extend(inventory.warnings)

        lock_objs, need_root = objects_for_lock(inventory)
        report.lock_objects = [o.storage_name for o in lock_objs]
        if need_root:
            report.lock_objects = ["Configuration", *report.lock_objects]

        if inventory.own_objects:
            alert = format_new_objects_alert(inventory.own_objects)
            print(alert, flush=True)
            if on_progress:
                on_progress(alert)
            if not accept_new_objects:
                report.aborted_new_objects = True
                if report_path:
                    report.write_json(report_path)
                raise NewObjectsNotAcceptedError(inventory, alert)

        if dry_run:
            _progress(on_progress, "Dry-run: захват и загрузка пропущены")
            if report_path:
                report.write_json(report_path)
            return report

        # Storage lock
        objects_file = work / "objects-lock.xml"
        if repo is not None:
            write_objects_file(
                objects_file,
                lock_objs,
                include_configuration=need_root,
            )
            _progress(on_progress, "Захват объектов в хранилище…")
            cancel_check()
            repository_lock(cfg, objects_file, on_progress=on_progress)
            report.locked = True
        elif need_root or lock_objs:
            # Objects will change; warn if no repo credentials
            report.warnings.append(
                "Параметры хранилища не заданы — захват объектов пропущен. "
                "Если конфигурация подключена к хранилищу, укажите --repo-path/--repo-user."
            )

        # Merge into main dump copy (keep original dump for reference)
        merge_dir = work / "main-merged"
        if merge_dir.exists():
            shutil.rmtree(merge_dir)
        shutil.copytree(main_dir, merge_dir)

        _progress(on_progress, "Слияние метаданных и BSL…")
        cancel_check()
        touched, merge_warnings = merge_extension_into_main(ext_dir, merge_dir, inventory)
        report.warnings.extend(merge_warnings)
        report.touched_files = touched
        report.merged = True

        if skip_designer:
            # Offline mode: write merged tree only
            _progress(on_progress, f"Offline: результат в {merge_dir}")
            if report_path:
                report.write_json(report_path)
            return report

        list_file = work / "load-list.txt"
        # Always include Configuration.xml when own objects added
        load_paths = list(touched) if touched else ["Configuration.xml"]
        write_load_list_file(list_file, load_paths)

        _progress(on_progress, "Загрузка в основную конфигурацию…")
        cancel_check()
        load_config_from_files(cfg, merge_dir, list_file=list_file, on_progress=on_progress)
        report.loaded = True

        if not skip_update_db:
            cancel_check()
            update_db_cfg(cfg, on_progress=on_progress)
            report.db_updated = True
        else:
            report.warnings.append("UpdateDBCfg пропущен (--skip-update-db)")

        if repo_commit and repo is not None:
            cancel_check()
            comment = repo_comment or f"cfe-into-cf: перенос расширения {extension}"
            repository_commit(cfg, objects_file, comment=comment, on_progress=on_progress)
            report.repo_committed = True

        if report_path:
            report.write_json(report_path)
        return report
    finally:
        if cleanup_work and dry_run:
            # Keep work dir on full runs for diagnostics; clean on dry-run only if empty dumps
            pass
