"""CLI entrypoint: cfe-into-cf."""

from __future__ import annotations

import argparse
import sys

from cfe_into_cf.cancel import CancelledError
from cfe_into_cf.designer import DesignerError
from cfe_into_cf.orchestrator import NewObjectsNotAcceptedError, run_cfe_into_cf


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cfe-into-cf",
        description=(
            "Перенос содержимого расширения конфигурации 1С в основную конфигурацию "
            "через пакетный режим Конфигуратора, с захватом объектов в хранилище."
        ),
    )
    p.add_argument("--extension", required=True, help="Имя расширения в ИБ")
    p.add_argument("--ib-path", default=None, help="Путь к файловой информационной базе")
    p.add_argument("--ib-server", default=None, help="Сервер 1С (для клиент-серверной ИБ)")
    p.add_argument("--ib-ref", default=None, help="Имя ИБ на сервере")
    p.add_argument("--ib-user", default=None, help="Пользователь ИБ")
    p.add_argument("--ib-password", default=None, help="Пароль пользователя ИБ")
    p.add_argument("--1cv8", dest="v8_path", default=None, help="Путь к 1cv8.exe")
    p.add_argument("--repo-path", default=None, help="Путь к хранилищу конфигурации")
    p.add_argument("--repo-user", default=None, help="Пользователь хранилища")
    p.add_argument("--repo-password", default=None, help="Пароль хранилища")
    p.add_argument(
        "--accept-new-objects",
        action="store_true",
        help="Подтвердить добавление новых (Own) объектов в основную конфигурацию",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Только выгрузка и инвентаризация; без захвата и загрузки",
    )
    p.add_argument(
        "--skip-update-db",
        action="store_true",
        help="Не вызывать /UpdateDBCfg после загрузки",
    )
    p.add_argument(
        "--repo-commit",
        action="store_true",
        help="После успешного переноса поместить объекты в хранилище",
    )
    p.add_argument("--repo-comment", default="", help="Комментарий к помещению в хранилище")
    p.add_argument("--report", default=None, help="Путь к JSON-отчёту")
    p.add_argument("--work-dir", default=None, help="Рабочий каталог (выгрузки, логи)")
    # Offline / test helpers
    p.add_argument(
        "--extension-dump",
        default=None,
        help="Готовая выгрузка расширения (пропускает DumpConfigToFiles для CFE)",
    )
    p.add_argument(
        "--main-dump",
        default=None,
        help="Готовая выгрузка основной CF (пропускает DumpConfigToFiles для CF)",
    )
    p.add_argument(
        "--skip-designer",
        action="store_true",
        help="Только merge по --extension-dump/--main-dump без вызовов Конфигуратора",
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
        report = run_cfe_into_cf(
            extension=args.extension,
            ib_path=args.ib_path,
            ib_server=args.ib_server,
            ib_ref=args.ib_ref,
            ib_user=args.ib_user,
            ib_password=args.ib_password,
            v8_path=args.v8_path,
            repo_path=args.repo_path,
            repo_user=args.repo_user,
            repo_password=args.repo_password,
            accept_new_objects=args.accept_new_objects,
            dry_run=args.dry_run,
            skip_update_db=args.skip_update_db,
            repo_commit=args.repo_commit,
            repo_comment=args.repo_comment,
            report_path=args.report,
            work_dir=args.work_dir,
            extension_dump=args.extension_dump,
            main_dump=args.main_dump,
            skip_designer=args.skip_designer,
            on_progress=lambda msg: print(f"[…] {msg}"),
        )
    except NewObjectsNotAcceptedError as exc:
        print(exc.alert_text, file=sys.stderr)
        print(
            "[ERROR] Добавление новых объектов не подтверждено. "
            "Повторите с --accept-new-objects после проверки списка.",
            file=sys.stderr,
        )
        return 2
    except CancelledError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 130
    except (DesignerError, FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print("=== cfe-into-cf summary ===")
    print(f"  Extension: {report.extension}")
    print(f"  Own:       {len(report.own_objects)}")
    print(f"  Adopted:   {len(report.adopted_objects)}")
    print(f"  BSL:       {len(report.bsl_modules)}")
    print(f"  Locked:    {report.locked}")
    print(f"  Merged:    {report.merged}")
    print(f"  Loaded:    {report.loaded}")
    print(f"  DB update: {report.db_updated}")
    print(f"  Work dir:  {report.work_dir}")
    for w in report.warnings:
        print(f"  [WARN] {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
