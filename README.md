# Video Web Service — Internship Task 1

Flask + Apache (mod_wsgi) + PostgreSQL, запуск через Docker Compose.

## Запуск

Нужны Docker и Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Сервис: http://127.0.0.1:8000

Остановка (данные сохраняются в томах db_data и uploads):

```bash
docker compose down
```

Полная очистка вместе с данными:

```bash
docker compose down -v
```
