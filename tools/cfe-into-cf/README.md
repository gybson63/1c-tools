# cfe-into-cf

Перенос содержимого расширения конфигурации 1С в **основную конфигурацию** через пакетный режим Конфигуратора.

- Источник истины — живая ИБ (расширение уже подключено).
- При подключении к хранилищу — предварительный захват нужных объектов.
- При добавлении **новых (Own) объектов** — блокирующий алерт и обязательное подтверждение.

## Установка

```powershell
cd tools\cfe-into-cf
python -m pip install -e ".[dev]"
```

## CLI

```powershell
# Сначала dry-run: выгрузка + инвентаризация + алерт
cfe-into-cf `
  --extension MyExt `
  --ib-path "D:\Bases\Dev" `
  --ib-user Admin `
  --repo-path "D:\Repo\cf" `
  --repo-user dev `
  --dry-run

# Полный перенос (с подтверждением новых объектов)
cfe-into-cf `
  --extension MyExt `
  --ib-path "D:\Bases\Dev" `
  --ib-user Admin `
  --repo-path "D:\Repo\cf" `
  --repo-user dev `
  --accept-new-objects `
  --report report.json
```

Коды выхода:

| Код | Значение |
|-----|----------|
| 0 | Успех |
| 1 | Ошибка Designer / параметры |
| 2 | Есть новые объекты, нет `--accept-new-objects` |
| 130 | Отмена |

## GUI

```powershell
cfe-into-cf-gui
# или
python -m cfe_into_cf.gui_app
```

При наличии новых объектов откроется модальное окно с красным предупреждением; продолжение только после чекбокса «Я понимаю риск».

## Offline / тесты без Конфигуратора

```powershell
cfe-into-cf `
  --extension TestExt `
  --extension-dump path\to\ext `
  --main-dump path\to\cf `
  --skip-designer `
  --accept-new-objects `
  --work-dir .\work
```

Результат merge: `work\main-merged\`.

## Документация

Подробный пайплайн: [docs/cfe-into-cf-guide.md](docs/cfe-into-cf-guide.md).
