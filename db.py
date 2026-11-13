import os
import time
from contextlib import closing
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"


def db_config():
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ.get("DB_PORT", "5432")),
        "dbname": os.environ["DB_NAME"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "connect_timeout": 5,
    }


def connect():
    return psycopg2.connect(**db_config())


CREATE_VIDEOS = """
CREATE TABLE IF NOT EXISTS videos (
    id           SERIAL PRIMARY KEY,
    company_name TEXT NOT NULL UNIQUE,
    file_path    TEXT NOT NULL,
    video_url    TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

MIGRATIONS = [
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_file_path TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_video_url TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS processing_status TEXT NOT NULL DEFAULT 'skipped'",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS processing_error TEXT",
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_videos_processing_status ON videos (processing_status)",
    "UPDATE videos SET processed_video_url = video_url WHERE processing_status = 'skipped' AND processed_video_url IS NULL",
]


def init_db(max_attempts=30, delay=1):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    last_error = None

    for _ in range(max_attempts):
        try:
            with closing(connect()) as conn:
                with conn.cursor() as cur:
                    cur.execute(CREATE_VIDEOS)

                    for statement in MIGRATIONS:
                        cur.execute(statement)

                conn.commit()
            return

        except psycopg2.OperationalError as error:
            last_error = error
            time.sleep(delay)

    raise RuntimeError("Не удалось подключиться к PostgreSQL") from last_error
