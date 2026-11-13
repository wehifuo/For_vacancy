import os
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from psycopg2.extras import RealDictCursor
from apply_zoom import process_video as apply_zoom_video
from db import connect, init_db

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
POLL_SECONDS = 2

CLAIM_SQL = """
WITH next AS (
    SELECT id
    FROM videos
    WHERE processing_status = 'pending'
    ORDER BY updated_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE videos v
SET processing_status = 'processing',
    processing_error = NULL,
    updated_at = NOW()
FROM next
WHERE v.id = next.id
RETURNING v.id, v.company_name, v.file_path;
"""


def claim_job():
    with closing(connect()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(CLAIM_SQL)
            row = cur.fetchone()
        conn.commit()

    return dict(row) if row else None


def reset_stale_jobs():
    with closing(connect()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE videos
                SET processing_status = 'pending',
                    processing_error = 'stale job reset',
                    updated_at = NOW()
                WHERE processing_status = 'processing'
                  AND updated_at < NOW() - INTERVAL '10 minutes'
            """)
        conn.commit()


def mark_done(video_id, output):
    url = f"{PUBLIC_BASE_URL}/media/{quote(output.name)}"

    with closing(connect()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE videos
                SET processing_status = 'done',
                    processed_file_path = %s,
                    processed_video_url = %s,
                    processing_error = NULL,
                    processed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
            """, (str(output), url, video_id))
        conn.commit()


def mark_failed(video_id, error):
    with closing(connect()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE videos
                SET processing_status = 'failed',
                    processing_error = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (str(error)[:2000], video_id))
        conn.commit()


def main():
    init_db()
    reset_stale_jobs()
    print("worker started", flush=True)

    while True:
        job = claim_job()

        if job is None:
            time.sleep(POLL_SECONDS)
            continue

        video_id = job["id"]
        video_path = Path(job["file_path"])

        print(f"[{video_id}] start {video_path}", flush=True)

        try:
            output = apply_zoom_video(video_path, "ffmpeg", False)

            if output is None:
                raise RuntimeError("apply_zoom вернул None")

            mark_done(video_id, output)
            print(f"[{video_id}] done {output}", flush=True)

        except Exception as error:
            mark_failed(video_id, error)
            print(f"[{video_id}] failed: {error}", flush=True)


if __name__ == "__main__":
    main()
