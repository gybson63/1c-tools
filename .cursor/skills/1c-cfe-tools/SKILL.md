---
name: 1c-cfe-tools
description: >-
  Routes work with 1C configuration extensions (CFE) to the right tool in the
  1c-tools monorepo. Use when the user mentions 1C, расширения, CFE, .cfe,
  заимствование объектов, перенос расширения в конфигурацию, сборку расширения
  из git-diff / выгрузки CF, или инструменты cfe-from-diff / cfe-into-cf.
---

# 1C CFE tools — выбор инструмента

Монорепозиторий `1c-tools`. Каждый инструмент самодостаточен в `tools/<имя>/`.

## Когда какой инструмент

| Задача | Skill | Каталог |
|--------|-------|---------|
| Собрать **расширение** из git-diff / разницы выгрузок CF | [cfe-from-diff](../cfe-from-diff/SKILL.md) | `tools/cfe-from-diff` |
| Перенести содержимое **расширения в основную CF** (ИБ + хранилище) | [cfe-into-cf](../cfe-into-cf/SKILL.md) | `tools/cfe-into-cf` |

### Решите по направлению

```text
Изменения в CF (git / dump)  ──►  расширение (.cfe / XML)     →  cfe-from-diff
Расширение уже в ИБ           ──►  основная конфигурация       →  cfe-into-cf
```

Не путать:

- **cfe-from-diff** — CF → CFE (через ibcmd, без Конфигуратора).
- **cfe-into-cf** — CFE → CF (пакетный Конфигуратор, опционально захват в хранилище).

## Обязательный порядок

1. Прочитать skill выбранного инструмента целиком.
2. Следовать его workflow (сначала dry-run).
3. Не изобретать ручной merge XML/BSL, если задачу закрывает CLI.

## Требования окружения

- Python ≥ 3.10
- Windows (типичный сценарий с платформой 1С)
- Для сборки `.cfe`: платформа с `ibcmd`
- Для переноса в CF: платформа с `1cv8` (Конфигуратор)

Установка — из каталога инструмента:

```powershell
cd tools/cfe-from-diff   # или tools/cfe-into-cf
python -m pip install -e .
```

## Документация в репо

- Корневой обзор: `README.md`
- Гайды: `tools/cfe-from-diff/docs/cfe-from-diff-guide.md`, `tools/cfe-into-cf/docs/cfe-into-cf-guide.md`
