# Video Web Service

Flask + Apache/mod_wsgi + PostgreSQL + worker + DeepSeek.

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

Сервис: <http://127.0.0.1:8000>  
Сервисы: `web`, `worker`, `db`.

```bash
docker compose down      # остановить
docker compose down -v   # остановить и удалить данные
```

## Видео

```bash
python capture_video.py --server http://127.0.0.1:8000 \
  --process --wait-processed 60
```

## Компании

Импорт CSV:

```bash
curl -X POST http://127.0.0.1:8000/upload_companies \
  -F "file=@companies.csv"
```

Форма: <http://127.0.0.1:8000/upload_companies>

```bash
curl http://127.0.0.1:8000/companies
curl "http://127.0.0.1:8000/companies/nutrimmun%20GmbH"
curl "http://127.0.0.1:8000/companies?status=0"
```

Обогащение:

```bash
docker compose exec web python enrich_companies.py
docker compose exec web python enrich_companies.py --company "nutrimmun GmbH"
docker compose exec web python enrich_companies.py --limit 1
docker compose exec web python enrich_companies.py --status 4
docker compose exec web python enrich_companies.py --delay 2
```

Статусы:

```text
NULL  не обработана
0     OK
1     нет Impressum
2     PARSING_FAILED
3     адрес неполный
4     ERROR
5     нет website
```

## Token optimization

Перед отправкой текста Impressum в DeepSeek `impressum.py` применяет бюджет `MAX_TEXT_CHARS = 8000`:

- текст короче лимита отправляется как есть;
- из длинных страниц удаляются boilerplate-строки (cookie, «Datenschutz», «AGB», «©», меню, языковые переключатели);
- head-якоря (`Impressum`, `Angaben gemäß § 5 TMG/DDG`, `Anbieter`, `Diensteanbieter`) отсекают навигацию до юридического блока;
- tail-якоря (`+49`/`0049`, VAT `DE...`, e-mail, `HRB`/`HRA`, `Amtsgericht`/`Registergericht`, `Geschäftsführer`/`Verantwortlich`) задают конец значимой части, после последнего совпадения остаётся запас `TAIL_MARGIN = 400` символов;
- если текст всё ещё длиннее лимита, остаётся окно «начало + конец»; если якоря не найдены — отправляется исходный текст.

Служебный символ `®` из текста удаляется. До и после оптимизации в лог пишутся `chars` и оценка токенов (`len(text) // 4`).

## Тесты

```bash
./venv/bin/python -m pytest -q
```
