import os
import re
from pathlib import Path
from flask import Flask, g, jsonify, request, send_from_directory, url_for
import time
import psycopg2
from psycopg2.extras import RealDictCursor


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"


app = Flask(__name__)


def _db_config():
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ.get("DB_PORT", "5432")),
        "dbname": os.environ["DB_NAME"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "connect_timeout": 5,
    }


def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(**_db_config())
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(max_attempts=30, delay=1):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    last_error = None

    for _ in range(max_attempts):
        try:
            conn = psycopg2.connect(**_db_config())
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS videos (
                            id           SERIAL PRIMARY KEY,
                            company_name TEXT NOT NULL UNIQUE,
                            file_path    TEXT NOT NULL,
                            video_url    TEXT NOT NULL,
                            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        );
                    """)
                conn.commit()
            finally:
                conn.close()
            return

        except psycopg2.OperationalError as error:
            last_error = error
            time.sleep(delay)

    raise RuntimeError("Не удалось подключиться к Postgre") from last_error


def safe_filename(company_name, original_filename=""):
    name = re.sub(r"[^\w.-]+", "_", company_name.strip(), flags=re.UNICODE)
    name = name.strip("._") or "video"

    suffix = Path(original_filename).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".webm"

    if not name.lower().endswith(suffix):
        name += suffix

    return name


def make_video_url(filename):
    return request.host_url.rstrip("/") + url_for("serve_media", filename=filename)


@app.post("/upload")
def upload_video():
    if "file" not in request.files:
        return jsonify({"error": "поле 'file' обязательно"}), 400

    uploaded_file = request.files["file"]
    company_name = (request.form.get("company_name") or "").strip()

    if not company_name:
        return jsonify({"error": "поле 'company_name' обязательно"}), 400
    if not uploaded_file.filename:
        return jsonify({"error": "имя загружаемого файла пустое"}), 400

    filename = safe_filename(company_name, uploaded_file.filename)
    file_path = (UPLOAD_DIR / filename).resolve()

    if file_path.parent != UPLOAD_DIR.resolve():
        return jsonify({"error": "некорректное имя файла"}), 400

    uploaded_file.save(str(file_path))
    video_url = make_video_url(filename)

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO videos (company_name, file_path, video_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (company_name) DO UPDATE SET
                file_path  = EXCLUDED.file_path,
                video_url  = EXCLUDED.video_url,
                updated_at = NOW()
            """,
            (company_name, str(file_path), video_url),
        )
    db.commit()
    return jsonify({"company_name": company_name, "video_url": video_url}), 200


@app.get("/get_video_url")
def get_video_url():
    company_name = (request.args.get("company_name") or "").strip()
    if not company_name:
        return jsonify({"error": "параметр 'company_name' обязателен"}), 400

    with get_db().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT company_name, video_url FROM videos WHERE company_name = %s",
            (company_name,),
        )
        row = cur.fetchone()

    if row is None:
        return jsonify({"error": "видео не найдено", "company_name": company_name}), 404

    return jsonify(
        {"company_name": row["company_name"], "video_url": row["video_url"]}
    ), 200


@app.get("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory(str(UPLOAD_DIR), filename, conditional=True)


@app.get("/videos")
def list_videos():

    with get_db().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT id, company_name, file_path, video_url, created_at::text AS created_at, updated_at::text AS updated_at
                    FROM videos
                    ORDER BY id;
                    """)
        rows = cur.fetchall()

    return jsonify([dict(row) for row in rows])


def main():
    init_db()
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "8000"))
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
