# 1c-tools

Утилиты для работы с конфигурациями и расширениями 1С.

## cfe-from-diff

Создаёт расширение конфигурации (CFE) по разнице между выгрузкой основной конфигурации
и набором изменённых файлов: заимствует объекты, переносит метаданные и BSL-патчи,
собирает `.cfe` через **ibcmd** (без Конфигуратора).

### Установка

```bash
pip install -e ".[dev]"
```

Требуется Python ≥ 3.10 и `lxml`. Для сборки `.cfe` — установленная платформа 1С с `ibcmd`.

### Пошаговая инструкция

Подробный сценарий с git diff и шаблоном скрипта: [docs/cfe-from-diff-guide.md](docs/cfe-from-diff-guide.md).

Быстрый старт через шаблон:

```powershell
copy scripts\run-cfe-from-diff.ps1 C:\work\run-my-ext.ps1
# заполнить блок ПАРАМЕТРЫ, затем:
powershell -ExecutionPolicy Bypass -File C:\work\run-my-ext.ps1
```

### GUI

Десктопный интерфейс (Tkinter): выбор своих коммитов, просмотр изменённых объектов и diff, запуск полного пайплайна.

```bash
pip install -e ".[dev]"
cfe-from-diff-gui
```

Альтернатива без entrypoint:

```bash
python -m cfe_tools.gui_app
```

В окне:

1. Укажите **Git repo**, **Config (база)**, **Output** и при необходимости DumpPrefix / ibcmd.
2. **Обновить список** — свои коммиты текущей ветки (фильтр по `git user.name` / `user.email`).
3. Выберите коммит → **Выбрать как To** (From = родитель) → **Показать изменения**.
4. В правой панели — объекты/файлы; клик по файлу показывает unified diff.
5. **Запустить пайплайн** или **Только dry-run**.

Подробнее: [docs/cfe-from-diff-guide.md](docs/cfe-from-diff-guide.md#gui).

### Использование (CLI напрямую)

```bash
cfe-from-diff \
  --name K7_20486 \
  --config C:\path\to\cf-dump \
  --changes C:\path\to\changed-files \
  --output C:\path\to\extension-src \
  --cfe C:\path\to\K7_20486.cfe \
  --ib-path C:\path\to\infobase \
  --purpose Patch \
  --report report.json
```

Только XML-исходники (без ibcmd):

```bash
cfe-from-diff \
  --name K7_20486 \
  --config C:\path\to\cf-dump \
  --changes C:\path\to\changed-files \
  --output C:\path\to\extension-src \
  --skip-build
```

Инвентаризация без записи:

```bash
cfe-from-diff ... --dry-run --skip-build
```

### Параметры

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

### Пайплайн ibcmd

В ИБ должна быть загружена та же базовая конфигурация, что и `--config`:

```text
ibcmd infobase --db-path=<IB> config extension create --name=... --name-prefix=... --purpose=...
ibcmd infobase --db-path=<IB> config import --extension=... <output>
ibcmd infobase --db-path=<IB> config check --extension=...
ibcmd infobase --db-path=<IB> config apply --extension=... --force
ibcmd infobase --db-path=<IB> config save --extension=... <out.cfe>
```

### Перенос изменений

| Diff | В расширение |
|------|----------------|
| Новый метод | копия без декоратора |
| Изменённый метод | `&ИзменениеИКонтроль` + `#Вставка`/`#Удаление` |
| Новый реквизит/ТЧ | Own в XML заимствованного объекта |
| Изменённая форма | borrow формы + Form.xml из changes |
| Новый объект | Own (копия из changes) |

### Тесты

```bash
pytest
```

### Линтеры

```bash
pip install -e ".[dev]"
ruff check src tests
ruff format --check src tests
mypy
pylint src tests
```

Хуки pre-commit (ruff, mypy, pylint):

```bash
pre-commit install
pre-commit run --all-files
```

Часть логики заимствования/валидации адаптирована из [cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills) (см. `NOTICE`).
