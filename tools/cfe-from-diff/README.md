# cfe-from-diff

Создаёт расширение конфигурации (CFE) по разнице между выгрузкой основной конфигурации
и набором изменённых файлов: заимствует объекты, переносит метаданные и BSL-патчи,
собирает `.cfe` через **ibcmd** (без Конфигуратора).

Этот каталог — **самодостаточный пакет**. Его можно скопировать на другой ПК без остального
репозитория `1c-tools` и без lint/pre-commit-окружения.

## Что копировать

Скопируйте целиком папку `cfe-from-diff` (этот каталог):

```text
cfe-from-diff/
  README.md
  LICENSE
  NOTICE
  pyproject.toml
  src/
  docs/
  scripts/
  tests/          # необязательно на рабочем ПК
```

Не нужны: `.git`, `.pre-commit-config.yaml`, ruff/mypy/pylint — они живут в корне монорепо.

## Требования на целевом ПК

| Что | Зачем |
|-----|--------|
| Python ≥ 3.10 (с Tkinter) | CLI и GUI |
| Git в PATH | список коммитов / staging из diff |
| `lxml` (ставится через pip) | разбор XML |
| Платформа 1С с `ibcmd` | только если нужна сборка `.cfe` |

## Установка

```powershell
cd C:\path\to\cfe-from-diff
python -m pip install .
```

Только runtime-зависимости (`lxml`). Для разработки/тестов: `pip install -e ".[dev]"`.

## Запуск

GUI:

```powershell
cfe-from-diff-gui
# или без entrypoint:
python -m cfe_tools.gui_app
```

CLI:

```powershell
cfe-from-diff --help
```

Шаблон PowerShell: [scripts/run-cfe-from-diff.ps1](scripts/run-cfe-from-diff.ps1).  
Подробный сценарий: [docs/cfe-from-diff-guide.md](docs/cfe-from-diff-guide.md).

### GUI — краткий сценарий

1. Укажите **Git repo**, **Output** и при необходимости DumpPrefix.
2. **Обновить список** — свои коммиты текущей ветки (`git user.name` / `user.email`).
3. Выберите коммит → **Выбрать как To** → **Показать изменения**.
4. Клик по файлу — unified diff.
5. **Запустить пайплайн** или **Только dry-run**.

База (Config) и staging изменений берутся из git автоматически:
- Config = дерево выгрузки на **DiffFrom**
- Changes = изменённые файлы на **DiffTo**

Отдельный каталог Config не нужен. IB path нужен только если собираете `.cfe` (Skip build выключен).

Основные поля формы (пути, ibcmd, флаги и т.п.) сохраняются автоматически в
`%LOCALAPPDATA%\cfe-tools\gui-settings.json` и подставляются при следующем запуске.
Пароль ИБ не сохраняется.

## Параметры CLI

| Параметр | Описание |
|----------|----------|
| `--config` | Каталог hierarchical XML-выгрузки базовой CF |
| `--changes` | Каталог изменённых файлов (те же относительные пути) |
| `--output` | Куда писать XML расширения |
| `--cfe` | Путь выходного `.cfe` |
| `--ib-path` | Файловая ИБ с уже загруженной базовой CF |
| `--ibcmd` | Путь к `ibcmd` (иначе PATH / `Program Files\1cv8`) |
| `--skip-build` | Не вызывать ibcmd |
| `--force` | Перезаписать `--output`, если там уже есть `Configuration.xml` |

## Тесты (опционально)

```powershell
pip install -e ".[dev]"
pytest
```

Часть логики заимствования/валидации адаптирована из [cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills) (см. `NOTICE`).
