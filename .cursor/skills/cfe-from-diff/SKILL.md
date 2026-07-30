---
name: cfe-from-diff
description: >-
  Builds a 1C configuration extension (CFE/XML) from git-diff or Designer dump
  differences via ibcmd. Use when creating an extension from CF changes, packing
  .cfe, borrowing metadata objects, applying BSL patches with
  &ИзменениеИКонтроль, or when the user mentions cfe-from-diff, сборку расширения
  из diff, DiffFrom/DiffTo, или выгрузку CF → CFE.
---

# cfe-from-diff

Создаёт расширение из разницы между базовой hierarchical XML-выгрузкой CF и изменёнными файлами. Сборка `.cfe` — через **ibcmd** (без Конфигуратора).

Каталог: `tools/cfe-from-diff`  
Гайд: `tools/cfe-from-diff/docs/cfe-from-diff-guide.md`  
Шаблон: `tools/cfe-from-diff/scripts/run-cfe-from-diff.ps1`

## Когда применять

- Нужно расширение по коммиту / диапазону git в репозитории выгрузки CF
- Есть `--config` (база) + `--changes` (изменённые файлы с теми же относительными путями)
- Нужен только XML расширения (`--skip-build`) или ещё `.cfe`

Не применять для переноса расширения обратно в основную CF — это [cfe-into-cf](../cfe-into-cf/SKILL.md).

## Установка и проверка

```powershell
cd tools/cfe-from-diff
python -m pip install -e .
cfe-from-diff --help
```

Без установки в PATH:

```powershell
$env:PYTHONPATH = "tools/cfe-from-diff/src"
python -m cfe_tools.cli --help
```

## Workflow (агент)

Скопируйте и отмечайте прогресс:

```text
- [ ] 1. Определены DiffFrom / DiffTo (или готовые --config / --changes)
- [ ] 2. Проверен git diff --name-only --diff-filter=ACMR
- [ ] 3. Базовая выгрузка (--config) = состояние «до», не «после»
- [ ] 4. DumpPrefix / pathspec отсекают не-dump файлы
- [ ] 5. Dry-run: inventory Borrow / New / BSL адекватен
- [ ] 6. Генерация XML (--skip-build, при необходимости --force)
- [ ] 7. (Опционально) Сборка .cfe: ИБ с той же базовой CF + ibcmd
```

### Предпочтительный путь: шаблон PowerShell

1. Скопировать `scripts/run-cfe-from-diff.ps1` в рабочий файл.
2. Заполнить блок **ПАРАМЕТРЫ** (`$ExtensionName`, `$ConfigDir`, `$GitRepo`, `$DumpPrefix`, `$DiffFrom`, `$DiffTo`, `$OutputDir`, …).
3. Сначала `$DryRun = $true`, `$SkipBuild = $true`.
4. Затем боевой прогон с `$DryRun = $false`.
5. Для `.cfe`: `$SkipBuild = $false`, задать `$CfePath` и `$IbPath`.

```powershell
powershell -ExecutionPolicy Bypass -File path/to/run-….ps1
```

### Прямой CLI (без git-staging)

Если каталоги `--config` и `--changes` уже готовы:

```powershell
cfe-from-diff `
  --name K7_20486 `
  --config path/to/cf-base `
  --changes path/to/changes `
  --output path/to/ext-src `
  --skip-build `
  --force `
  --dry-run `
  --report report.json
```

Боевая генерация XML — убрать `--dry-run`. Сборка `.cfe` — убрать `--skip-build`, добавить `--cfe` и `--ib-path`.

## Ключевые параметры

| Параметр | Смысл |
|----------|--------|
| `--name` | Имя расширения |
| `--config` | Базовая hierarchical XML-выгрузка CF |
| `--changes` | Дерево изменённых файлов (те же relative paths) |
| `--output` | Куда писать XML расширения |
| `--cfe` / `--ib-path` | Выход `.cfe` и файловая ИБ (нужны без `--skip-build`) |
| `--purpose` | `Patch` \| `Customization` \| `AddOn` (default Customization) |
| `--prefix` | NamePrefix (default `<name>_`) |
| `--dry-run` | Только инвентаризация |
| `--skip-build` | Только XML, без ibcmd |
| `--force` | Перезаписать `--output`, если там уже есть `Configuration.xml` |
| `--report` | JSON-отчёт |

## Инварианты

- `--config` = снимок **без** правок из выбранного диапазона; `--changes` = версии **после**.
- Относительные пути после снятия DumpPrefix: `Catalogs/…`, `CommonModules/…`, `Documents/…` и т.д.
- Для ibcmd в ИБ уже должна быть загружена **та же** базовая CF, что `--config`.
- Удалённые файлы в diff в staging не выгружаются (`--diff-filter=ACMR`).

## Типичные сбои

| Симптом | Действие |
|---------|----------|
| Нет изменённых файлов | Проверить From/To и pathspec |
| `Cannot map path to metadata object` | DumpPrefix / в diff попали не-dump файлы |
| Пустой inventory | `--config` уже содержит те же правки, что To |
| `cfe-from-diff` не найден | `pip install -e .` или `python -m cfe_tools.cli` |
| Ошибка ibcmd | Проверить ИБ, путь ibcmd, совпадение базовой CF |

## GUI (человек, не агент)

```powershell
powershell -ExecutionPolicy Bypass -File tools/cfe-from-diff/run-gui.ps1
```

Агенту предпочтителен CLI / шаблон `.ps1`.

## Дополнительно

Полный пошаговый сценарий и чеклист — в `tools/cfe-from-diff/docs/cfe-from-diff-guide.md`.
