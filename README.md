# 1c-tools

Монорепозиторий утилит для работы с конфигурациями и расширениями 1С.

Каждый инструмент лежит в `tools/<имя>/` и может копироваться/устанавливаться отдельно.

## Инструменты

| Каталог | Описание |
|---------|----------|
| [tools/cfe-from-diff](tools/cfe-from-diff) | Сборка расширения (CFE) из git-diff / выгрузки CF; CLI + GUI |

## Как перенести один инструмент на другой ПК

Скопируйте только нужную папку, например:

```powershell
# из корня репозитория
Copy-Item -Recurse tools\cfe-from-diff C:\work\cfe-from-diff
```

Или соберите ZIP:

```powershell
powershell -File scripts\pack-cfe-from-diff.ps1
# результат: dist\cfe-from-diff-*.zip
```

Дальше установка и запуск — в README внутри этой папки. Корневые lint/pre-commit на целевой ПК не нужны.

## Разработка в монорепо

Линтеры и pre-commit настроены на инструмент `cfe-from-diff`:

```powershell
cd tools\cfe-from-diff
pip install -e ".[dev]"
pre-commit install   # из корня репозитория, см. .pre-commit-config.yaml
```
