# Video Web Service — Internship Task 2

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

Сервис: <http://127.0.0.1:8000>

Сервисы: `web`, `worker`, `db`. Тома: `db_data`, `uploads`.

```bash
docker compose down      # остановить, данные сохраняются
docker compose down -v   # остановить и удалить данные
```

## Что происходит

1. `capture_video.py` записывает видео в `video/`.
2. При зуме создаётся `video/<name>.webm.zoom.json`.
3. С `--server` видео и sidecar загружаются в `/upload`.
4. С `--process` вызывается `POST /videos/<id>/process`.
5. `worker` запускает `apply_zoom.py` и ffmpeg.
6. Результат: `uploads/<name>.zoomed.webm`, URL сохраняется в PostgreSQL.
7. С `--wait-processed` открывается уже обработанное видео.

## `capture_video.py`

```bash
python capture_video.py [аргументы]
```

| Аргумент | Что делает |
|---|---|
| `--server URL` | загрузить видео и sidecar на сервер |
| `--view-seconds N` | сколько секунд держать превью (по умолчанию 5; `0` — ждать Enter) |
| `--headed` | видимый браузер, нужен для ручного F5 |
| `--no-zoom-demo` | отключить автоматический демо-зум |
| `--process` | после загрузки вызвать `POST /videos/<id>/process` |
| `--wait-processed N` | ждать обработки до N секунд и открыть результат |

Примеры:

```bash
python capture_video.py
# только запись

python capture_video.py --server http://127.0.0.1:8000
# запись + загрузка + превью оригинала

python capture_video.py --server http://127.0.0.1:8000 --process --wait-processed 60
# полный цикл: запись → загрузка → обработка → превью

python capture_video.py --headed --no-zoom-demo
# ручной зум: первое нажатие F5 — in, второе — out
```

## `apply_zoom.py`

```bash
python apply_zoom.py --video video/Company.webm [аргументы]
```

| Аргумент | Что делает |
|---|---|
| `--video PATH` | исходное видео (обязательно) |
| `--dry-run` | показать команду ffmpeg без кодирования |
| `--ffmpeg PATH` | путь к ffmpeg, если его нет в `PATH` |

Результат: `video/Company.zoomed.webm`.

Если sidecar нет или в нём нет событий, видео копируется без изменений.

```bash
python apply_zoom.py --video video/Company.webm
python apply_zoom.py --video video/Company.webm --dry-run
```

## API

| Метод | Путь | Что делает |
|---|---|---|
| POST | `/upload` | загрузить видео и sidecar |
| GET | `/get_video_url?company_name=...` | вернуть URL и статус |
| GET | `/media/<filename>` | отдать видео |
| GET | `/videos` | список записей |
| POST | `/videos/<id>/process` | поставить видео в очередь |
