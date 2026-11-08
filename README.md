## Установка

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Запуск

Терминал 1 — сервер:

```bash
python web_service.py
```

Терминал 2 — запись, загрузка и превью:

```bash
python capture_video.py --server http://127.0.0.1:8000 --view-seconds 5
```

Без сервера:

```bash
python capture_video.py
```

`--view-seconds 0` — держать превью открытым до нажатия Enter.

## Результат

* `video/` — записанные видео
* `uploads/` — загруженные копии
* `videos.db` — база данных

## API

* `POST /upload`
* `GET /get_video_url?company_name=...`
* `GET /media/<filename>`
* `GET /videos`
