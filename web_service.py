import os
import re
import sqlite3
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, url_for

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "videos.db"

app = Flask(__name__)


def get_db():
    if "db" not in g:
        connection = sqlite3.connect(DB_PATH, timeout=10)
        connection.row_factory = sqlite3.Row
        # WAL включается один раз в init_db(): это свойство файла БД.
        # busy_timeout действует в рамках соединения, поэтому задаём здесь.
        connection.execute("PRAGMA busy_timeout = 5000")
        g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT    NOT NULL UNIQUE,
                file_path    TEXT    NOT NULL,
                video_url    TEXT    NOT NULL,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


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
    db.execute(
        """
        INSERT INTO videos (company_name, file_path, video_url)
        VALUES (?, ?, ?)
        ON CONFLICT(company_name) DO UPDATE SET
            file_path  = excluded.file_path,
            video_url  = excluded.video_url,
            updated_at = datetime('now')
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

    row = get_db().execute(
        "SELECT company_name, video_url FROM videos WHERE company_name = ?",
        (company_name,),
    ).fetchone()

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
    rows = get_db().execute(
        """
        SELECT id, company_name, file_path, video_url, created_at, updated_at
        FROM videos
        ORDER BY id
        """
    ).fetchall()
    return jsonify([dict(row) for row in rows])


def main():
    init_db()
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "8000"))
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
