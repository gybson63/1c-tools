# Пошаговая инструкция: сборка расширения из git-диффа

Инструкция описывает полный цикл: от установки инструментов до получения XML расширения (и при необходимости файла `.cfe`) через скрипт `scripts/run-cfe-from-diff.ps1`.

Скрипт делает три вещи:

1. Строит список изменённых файлов через `git diff`.
2. Выгружает эти файлы (состояние на стороне «после») во временный каталог `--changes`.
3. Запускает `cfe-from-diff`, который сравнивает изменения с базовой выгрузкой CF и собирает расширение.

```text
[git repo с выгрузкой CF]
        │
        │  git diff From..To
        ▼
[staging: каталог changes]  ──┐
                               ├──►  cfe-from-diff  ──►  XML расширения  ──►  (.cfe через ibcmd)
[базовая выгрузка --config] ──┘
```

---

## 0. Что должно быть готово заранее

| Что | Зачем |
|-----|--------|
| Python ≥ 3.10 | Запуск `cfe-from-diff` |
| Git | Список и выгрузка изменённых файлов |
| Репозиторий с hierarchical XML-выгрузкой конфигурации | Источник diff |
| Базовая выгрузка той же CF (каталог dump) | `--config` — «эталон», с которым сравнивают изменения |
| (Опционально) Платформа 1С с `ibcmd` и файловая ИБ | Только если нужна сборка `.cfe` |

**Важно про `--config` и git:**

- `--config` — это снимок **базовой** конфигурации (без ваших доработок из выбранного диапазона коммитов).
- Файлы из git на стороне `DiffTo` — это **уже изменённые** версии тех же относительных путей.
- Относительные пути в репозитории (после снятия `$DumpPrefix`) должны совпадать со структурой dump: `Catalogs\...`, `CommonModules\...`, `Documents\...` и т.д.

Типичные схемы:

1. **Репозиторий = сама выгрузка.** Тогда `$GitRepo` и `$ConfigDir` могут указывать на один каталог, а `$ConfigDir` лучше зафиксировать на коммит «до изменений» (checkout / worktree / отдельная копия).
2. **Выгрузка в подкаталоге репо** (`src/cf/...`). Тогда `$GitRepo` — корень репо, `$DumpPrefix = "src/cf/"`, `$ConfigDir` — путь к базовой копии dump.

---

## GUI

Десктопный интерфейс удобен для повседневной работы. После установки пакета:

```powershell
cfe-from-diff-gui
# или: python -m cfe_tools.gui_app
```

GUI повторяет сценарий этого гайда, но без правки `.ps1`:

| Действие в GUI | Что происходит |
|----------------|----------------|
| Обновить список | Коммиты текущей ветки автора с `git user.name` / `user.email` (hash + сообщение + дата) |
| Выбрать как To | `DiffTo = commit`, `DiffFrom = commit^` |
| Показать изменения | `git diff --name-only --diff-filter=ACMR` + маппинг в объекты метаданных |
| Клик по файлу | Unified diff `From..To` для файла |
| Запустить пайплайн | Staging blobs @ To → `cfe-from-diff` (XML и опционально `.cfe`) |
| Только dry-run | То же с `--dry-run` (только инвентаризация) |

Поля **Config**, **DumpPrefix**, **Skip build**, **Force**, **IB path** соответствуют параметрам скрипта из разделов ниже. «Свои коммиты» не появятся, если в git не настроены `user.name` / `user.email`.

---

## 1. Установка cfe-tools

В каталоге репозитория `1c-tools`:

```powershell
cd C:\Git\1c-tools
python -m pip install -e ".[dev]"
```

Проверка:

```powershell
cfe-from-diff --help
```

Если команда не находится в PATH, в скрипте укажите:

```powershell
$CfeFromDiff = @("python", "-m", "cfe_tools.cli")
```

(запускайте из каталога, где установлен пакет, либо с настроенным `PYTHONPATH=src`).

---

## 2. Скопируйте и откройте шаблон скрипта

Не обязательно, но удобно: скопируйте шаблон под свою задачу, чтобы не затирать общий файл при обновлении репозитория.

```powershell
copy C:\Git\1c-tools\scripts\run-cfe-from-diff.ps1 C:\work\run-K7-20486.ps1
notepad C:\work\run-K7-20486.ps1
```

Дальше правьте только блок **«ПАРАМЕТРЫ»** в начале файла (выше комментария «Логика»).

---

## 3. Определите диапазон git diff

Скрипт вызывает по сути:

```text
git diff --name-only --diff-filter=ACMR DiffFrom DiffTo
```

То есть в список попадают добавленные, скопированные, изменённые и переименованные файлы. Удалённые не выгружаются (для `--changes` они не нужны).

### Вариант A — один конкретный коммит

```powershell
$DiffFrom = "a1b2c3d~1"
$DiffTo   = "a1b2c3d"
```

`~1` — родитель коммита. Эквивалентно изменениям, внесённым именно этим коммитом.

Узнать hash:

```powershell
git -C C:\path\to\cf-repo log --oneline -20
```

### Вариант B — все изменения ветки относительно main

```powershell
$DiffFrom = "origin/main"
$DiffTo   = "HEAD"
```

### Вариант C — от тега / релиза до текущего состояния

```powershell
$DiffFrom = "v1.0.0"
$DiffTo   = "HEAD"
```

### Проверка списка до запуска скрипта

```powershell
git -C C:\path\to\cf-repo diff --name-only --diff-filter=ACMR a1b2c3d~1 a1b2c3d
```

Убедитесь, что в списке именно файлы выгрузки конфигурации, а не посторонние (readme, CI и т.п.). При необходимости сузьте область:

```powershell
$Pathspec = @("Catalogs", "CommonModules", "Documents")
# или при DumpPrefix:
$DumpPrefix = "src/cf/"
$Pathspec   = @()   # тогда фильтр уже по DumpPrefix
```

---

## 4. Подготовьте базовую выгрузку (`$ConfigDir`)

`$ConfigDir` должен содержать **базовую** hierarchical XML-выгрузку — ту версию CF, относительно которой сделаны изменения в `$DiffTo`.

Рекомендуемый способ, если база и изменения живут в одном git-репо:

```powershell
# отдельный worktree на коммит «до» (например родитель вашего DiffTo)
git -C C:\path\to\cf-repo worktree add C:\work\cf-base a1b2c3d~1
```

Тогда:

```powershell
$ConfigDir = "C:\work\cf-base"          # или "C:\work\cf-base\src\cf" при подкаталоге
$GitRepo   = "C:\path\to\cf-repo"
$DumpPrefix = ""                        # или "src/cf/"
$DiffFrom  = "a1b2c3d~1"
$DiffTo    = "a1b2c3d"
```

Если у вас уже есть отдельный каталог с выгрузкой «чистой» CF (не из этого коммита) — укажите его в `$ConfigDir`. Главное: структура папок и имена объектов должны соответствовать файлам из diff.

---

## 5. Заполните параметры расширения и путей

Минимальный набор для генерации XML **без** сборки `.cfe`:

```powershell
$ExtensionName = "K7_20486"
$Purpose       = "Customization"   # или Patch / AddOn
$Prefix        = $null             # будет K7_20486_

$ConfigDir     = "C:\work\cf-base"
$GitRepo       = "C:\path\to\cf-repo"
$DumpPrefix    = ""

$OutputDir     = "C:\work\ext-K7_20486"
$CfePath       = ""                # не используется при SkipBuild

$ChangesDir    = ""                # пусто = временный каталог
$DiffFrom      = "a1b2c3d~1"
$DiffTo        = "a1b2c3d"

$SkipBuild     = $true
$DryRun        = $false
$ForceOutput   = $true
$KeepChanges   = $true             # на первый прогон удобно оставить staging
$ListPath      = "C:\work\changed-files.txt"
$ReportPath    = "C:\work\report.json"

$CfeFromDiff   = "cfe-from-diff"
```

Смысл ключевых полей:

| Параметр | Смысл |
|----------|--------|
| `$ExtensionName` | Имя расширения в 1С |
| `$Purpose` | Назначение расширения |
| `$ConfigDir` | Базовая выгрузка CF |
| `$GitRepo` | Откуда читать `git diff` / blob'ы |
| `$DumpPrefix` | Префикс пути выгрузки внутри репо |
| `$OutputDir` | Куда записать XML расширения |
| `$ChangesDir` | Куда сложить файлы из diff; пусто — temp |
| `$SkipBuild` | `$true` — только XML; `$false` — ещё ibcmd → `.cfe` |
| `$DryRun` | Только инвентаризация, без записи расширения |
| `$KeepChanges` / `$ListPath` | Отладка: сохранить staging и список файлов |

---

## 6. Первый прогон: dry-run (рекомендуется)

Перед записью расширения проверьте, что инструмент «видит» нужные объекты:

```powershell
$DryRun    = $true
$SkipBuild = $true
$ListPath  = "C:\work\changed-files.txt"
$KeepChanges = $true
```

Запуск:

```powershell
powershell -ExecutionPolicy Bypass -File C:\work\run-K7-20486.ps1
```

Ожидаемый вывод (примерно):

```text
git diff a1b2c3d~1..a1b2c3d : N файл(ов)
Список записан: C:\work\changed-files.txt
Staging --changes: ...
Выгружено в staging: N
Запуск: cfe-from-diff ...
=== cfe-from-diff dry-run ===
Changed files: ...
Borrow: ...
New objects: ...
BSL: ...
```

Проверьте:

1. `changed-files.txt` — нужные пути выгрузки.
2. В dry-run: `Borrow` / `New objects` / `BSL` соответствуют ожидаемым объектам.
3. Нет массовых `[WARN] Cannot map path to metadata object` (часто значит неверный `$DumpPrefix` или в diff попали не-dump файлы).

---

## 7. Генерация XML расширения

Если dry-run выглядит корректно:

```powershell
$DryRun      = $false
$SkipBuild   = $true
$ForceOutput = $true
$ReportPath  = "C:\work\report.json"
```

Снова запустите скрипт. В `$OutputDir` появится дерево расширения (`Configuration.xml`, заимствованные объекты, модули и т.д.).

Краткий контроль:

- есть `Configuration.xml`;
- нужные объекты присутствуют;
- в BSL для изменённых методов — декораторы `&ИзменениеИКонтроль` и области `#Вставка` / `#Удаление` (если так задумано инструментом для ваших diff).

---

## 8. (Опционально) Сборка `.cfe` через ibcmd

Нужны:

1. Установленная платформа 1С с `ibcmd` в PATH **или** явный путь в `$Ibcmd`.
2. Файловая информационная база, в которую **уже загружена та же базовая CF**, что и `$ConfigDir`.

Параметры:

```powershell
$SkipBuild  = $false
$CfePath    = "C:\work\K7_20486.cfe"
$IbPath     = "C:\work\infobase"
$Ibcmd      = $null          # или "C:\Program Files\1cv8\8.3.xx.xxxx\bin\ibcmd.exe"
$IbUser     = $null          # при необходимости
$IbPassword = $null
```

Скрипт передаст в CLI `--cfe` и `--ib-path`. Внутри `cfe-from-diff` выполнит цепочку ibcmd: create extension → import → check → apply → save `.cfe`.

Если сборка не нужна (XML загрузите в Конфигураторе вручную) — оставьте `$SkipBuild = $true`.

---

## 9. Типовой чеклист одного прогона

1. `pip install -e ".[dev]"` и `cfe-from-diff --help` работают.
2. Известны hash/ветки для `$DiffFrom` / `$DiffTo`.
3. Вручную просмотрен `git diff --name-only ...` — список адекватный.
4. `$ConfigDir` указывает на **базовую** выгрузку (состояние «до»).
5. `$GitRepo` / `$DumpPrefix` настроены так, что пути в staging совпадают со структурой `$ConfigDir`.
6. Dry-run: инвентарь Borrow / New / BSL верный.
7. Боевой прогон с `$SkipBuild = $true` → XML в `$OutputDir`.
8. При необходимости — `$SkipBuild = $false` и сборка `.cfe`.

---

## 10. Частые проблемы

| Симптом | Что проверить |
|---------|----------------|
| `Нет изменённых файлов в диапазоне` | Неверный From/To; уже нет diff; слишком узкий `$Pathspec` |
| `Пропуск (нет в To)` | Файл есть в diff как rename/unusual path; проверьте `git show To:path` |
| `Cannot map path to metadata object` | В staging попали файлы вне dump, или не снят `$DumpPrefix` |
| Пустой / странный inventory | `$ConfigDir` не «база», а уже с теми же правками, что и To — тогда diff с базой нулевой |
| `cfe-from-diff` не найден | Доустановите пакет или задайте `$CfeFromDiff = @("python", "-m", "cfe_tools.cli")` |
| Ошибка ibcmd / apply | В ИБ должна быть загружена та же CF, что `$ConfigDir`; проверьте права и путь `$IbPath` |
| ExecutionPolicy | Запуск с `-ExecutionPolicy Bypass` (как в примере выше) |

---

## 11. Ручной запуск без скрипта

Если staging вы собрали сами (или оставили через `$KeepChanges = $true`):

```powershell
cfe-from-diff `
  --name K7_20486 `
  --config C:\work\cf-base `
  --changes C:\work\cfe-changes `
  --output C:\work\ext-K7_20486 `
  --skip-build `
  --force `
  --report C:\work\report.json
```

Со сборкой:

```powershell
cfe-from-diff `
  --name K7_20486 `
  --config C:\work\cf-base `
  --changes C:\work\cfe-changes `
  --output C:\work\ext-K7_20486 `
  --cfe C:\work\K7_20486.cfe `
  --ib-path C:\work\infobase `
  --purpose Customization `
  --force
```

---

## Краткая шпаргалка параметров скрипта

```powershell
# Расширение
$ExtensionName = "K7_XXXXX"
$Purpose       = "Customization"     # Patch | Customization | AddOn
$Prefix        = $null

# Пути
$ConfigDir     = "C:\path\to\cf-base-dump"
$GitRepo       = "C:\path\to\cf-repo"
$DumpPrefix    = ""                  # напр. "src/cf/"
$OutputDir     = "C:\path\to\extension-src"
$CfePath       = "C:\path\to\out.cfe"
$ChangesDir    = ""                  # "" = temp

# Git
$DiffFrom      = "COMMIT~1"
$DiffTo        = "COMMIT"
$Pathspec      = @()

# ibcmd (если $SkipBuild = $false)
$IbPath        = "C:\path\to\infobase"
$Ibcmd         = $null
$IbUser        = $null
$IbPassword    = $null

# Режим
$SkipBuild     = $true
$DryRun        = $false
$ForceOutput   = $true
$KeepChanges   = $false
$ReportPath    = ""
$ListPath      = ""
$CfeFromDiff   = "cfe-from-diff"
```
