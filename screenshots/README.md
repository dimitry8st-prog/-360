# Скриншоты для сдачи

Папка локальная: PNG не уходят в git.

Сделано скриптом `scripts/capture_screenshots.py` с живого `http://127.0.0.1:8000`:

| Файл | Что на экране |
|---|---|
| `01-landing.png` | Главная, маскот, вход и регистрация |
| `02-dashboard.png` | Кабинет с чатом и лисом |
| `03-chat.png` | Чат по данным и файлам |
| `04-analysis.png` | Страница результата анализа CSV |

Переснять: сервер должен быть запущен, затем

```bash
.venv/Scripts/python scripts/capture_screenshots.py
```
