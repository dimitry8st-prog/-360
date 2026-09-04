# ДИС Аналитик 360

Универсальный AI-аналитик данных: загрузка CSV/Excel/JSON/PDF/изображений, проверка качества, интерактивные графики, история чатов и проверяемые выводы.

## Возможности MVP

- регистрация по email и паролю, личные данные пользователей изолированы;
- PostgreSQL в Docker и SQLite для локальной демонстрации;
- CSV, XLSX, JSON, PDF и изображения;
- `bar`, `line`, `histogram`, `pie`, `scatter`, `box`, `heatmap`;
- интерактивные Plotly-графики и экспорт PNG при доступном Kaleido;
- WebSocket-канал статуса обработки;
- аудит действий и структурированное логирование без содержимого файлов;
- админ-панель со статистикой;
- срок хранения файлов 30 дней;
- заглушки OpenAI, SMTP и 2FA позволяют безопасно запустить демо без ключей.

## Быстрый локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте `http://127.0.0.1:8000`. Демо-администратор создаётся из переменных `ADMIN_EMAIL` и `ADMIN_PASSWORD`.

## Docker

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

Контейнеры: `web`, `worker`, `db`, `redis`, `nginx`. Для production замените все значения с `change-me`, настройте SMTP и TLS.

## Проверка

```bash
pytest -q
```

Учебный прототип основан на идее проекта [MrGAN12009/data_assistant](https://github.com/MrGAN12009/data_assistant) и существенно расширен для самостоятельной эксплуатации.

