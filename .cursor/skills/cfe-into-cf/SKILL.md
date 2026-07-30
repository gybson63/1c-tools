---
name: cfe-into-cf
description: >-
  Transfers a 1C configuration extension into the main configuration via Designer
  batch mode, with optional configuration repository lock. Use when merging
  extension content into CF, applying &ИзменениеИКонтроль / #Вставка / #Удаление
  to main modules, accepting Own objects into the base config, or when the user
  mentions cfe-into-cf, перенос расширения в конфигурацию, захват в хранилище,
  DumpConfigToFiles / LoadConfigFromFiles для CFE→CF.
---

# cfe-into-cf

Переносит **всё** содержимое указанного расширения в основную конфигурацию ИБ через пакетный Конфигуратор. Расширение после переноса **не** удаляется и не отключается.

Каталог: `tools/cfe-into-cf`  
Гайд: `tools/cfe-into-cf/docs/cfe-into-cf-guide.md`

## Когда применять

- Расширение уже подключено в ИБ (источник истины — живая база)
- Нужно внести Own-объекты, правки Adopted и BSL-директивы в основную CF
- Нужен захват объектов в хранилище перед загрузкой

Не применять для сборки расширения из diff — это [cfe-from-diff](../cfe-from-diff/SKILL.md).

Почему не `/MergeCfg`: пакетный merge `.cfe` плохо учитывает `ObjectBelonging` и директивы изменения/контроля; этот инструмент делает контролируемый merge выгрузок.

## Установка и проверка

```powershell
cd tools/cfe-into-cf
python -m pip install -e .
cfe-into-cf --help
```

## Workflow (агент)

```text
- [ ] 1. Известны имя расширения и параметры ИБ (file или server/ref)
- [ ] 2. При хранилище заданы --repo-path / --repo-user (и пароль при необходимости)
- [ ] 3. Dry-run: выгрузка + инвентаризация Own / Adopted / BSL
- [ ] 4. Если есть Own — получить явное подтверждение пользователя
- [ ] 5. Полный прогон с --accept-new-objects (только после п.4)
- [ ] 6. Проверить summary и --report; UpdateDBCfg / repo-commit по договорённости
```

### 1. Dry-run (обязательно первым)

```powershell
cfe-into-cf `
  --extension MyExt `
  --ib-path "D:/Bases/Dev" `
  --ib-user Admin `
  --repo-path "D:/Repo/cf" `
  --repo-user dev `
  --dry-run `
  --report report.json
```

Клиент-серверная ИБ: вместо `--ib-path` указать `--ib-server` и `--ib-ref`.

### 2. Алерт новых объектов

Если есть Own-объекты и нет `--accept-new-objects` → exit code **2** и список в stderr.

**Агент не должен сам ставить `--accept-new-objects`.** Показать пользователю список Own и дождаться явного согласия (риски: дерево метаданных, структура БД, права, РИБ, префиксы).

### 3. Полный перенос

```powershell
cfe-into-cf `
  --extension MyExt `
  --ib-path "D:/Bases/Dev" `
  --ib-user Admin `
  --repo-path "D:/Repo/cf" `
  --repo-user dev `
  --accept-new-objects `
  --report report.json
```

Опции после успеха:

| Флаг | Смысл |
|------|--------|
| `--skip-update-db` | Не вызывать `/UpdateDBCfg` |
| `--repo-commit` | Поместить объекты в хранилище (по умолчанию выкл.) |
| `--repo-comment` | Комментарий помещения |

## Пайплайн (что делает CLI)

1. `DumpConfigToFiles` — расширение и основная CF (hierarchical)
2. Инвентаризация Own / Adopted / BSL
3. Алерт Own без подтверждения → stop (code 2)
4. При параметрах хранилища — `ConfigurationRepositoryLock` (+ корень `Configuration`, если есть Own)
5. Merge XML/BSL во временную копию основной выгрузки
6. `LoadConfigFromFiles` (частичная загрузка)
7. `UpdateDBCfg` (если не `--skip-update-db`)
8. Опционально `--repo-commit`

## Offline / без Конфигуратора

Для отладки merge на готовых выгрузках:

```powershell
cfe-into-cf `
  --extension TestExt `
  --extension-dump path/to/ext `
  --main-dump path/to/cf `
  --skip-designer `
  --accept-new-objects `
  --work-dir ./work
```

Результат: `work/main-merged/`.

## Коды выхода

| Код | Значение |
|-----|----------|
| 0 | Успех |
| 1 | Ошибка Designer / параметры |
| 2 | Есть Own, нет `--accept-new-objects` |
| 130 | Отмена |

## Правила безопасности для агента

- Всегда начинать с `--dry-run`.
- Не передавать `--accept-new-objects` без явного OK пользователя по списку Own.
- Не включать `--repo-commit`, пока пользователь не попросил.
- Пароли ИБ/хранилища не писать в git, отчёты и skills; брать из окружения / запроса пользователя.
- Если конфигурация на хранилище — передавать `--repo-*`, иначе захват пропускается и загрузка может упасть в Конфигураторе.

## GUI (человек)

```powershell
cfe-into-cf-gui
# или: python -m cfe_into_cf.gui_app
```

При Own — модальное предупреждение и чекбокс подтверждения. Агенту — только CLI.

## Дополнительно

Риски Own-объектов и детали хранилища — в `tools/cfe-into-cf/docs/cfe-into-cf-guide.md`.
