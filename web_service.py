import json
import os
import re
from pathlib import Path
from flask import Flask, g, jsonify, request, send_from_directory, url_for
from psycopg2.extras import RealDictCursor
from db import UPLOAD_DIR, connect, init_db

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)

def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

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

    sidecar_file = request.files.get("sidecar")
    sidecar_path = Path(str(file_path) + ".zoom.json")
    has_zoom = False
    raw_sidecar = None

    if sidecar_file and sidecar_file.filename:
        raw_sidecar = sidecar_file.read()

        try:
            payload = json.loads(raw_sidecar.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return jsonify({"error": "sidecar должен быть корректным JSON"}), 400

        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            return jsonify({"error": "в sidecar нет списка events"}), 400

        has_zoom = bool(events)

    uploaded_file.save(str(file_path))

    if raw_sidecar is not None:
        sidecar_path.write_bytes(raw_sidecar)
    else:
        sidecar_path.unlink(missing_ok=True)

    processed_path = file_path.with_name(file_path.stem + ".zoomed.webm")
    processed_path.unlink(missing_ok=True)

    status = "uploaded" if has_zoom else "skipped"
    video_url = make_video_url(filename)
    processed_url = None if has_zoom else video_url

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO videos (
                company_name, file_path, video_url,
                processed_file_path, processed_video_url,
                processing_status, processing_error, processed_at
            )
            VALUES (%s, %s, %s, NULL, %s, %s, NULL, NULL)
            ON CONFLICT (company_name) DO UPDATE SET
                file_path = EXCLUDED.file_path,
                video_url = EXCLUDED.video_url,
                processed_file_path = NULL,
                processed_video_url = EXCLUDED.processed_video_url,
                processing_status = EXCLUDED.processing_status,
                processing_error = NULL,
                processed_at = NULL,
                updated_at = NOW()
            RETURNING id
            """,
            (company_name, str(file_path), video_url, processed_url, status),
        )
        video_id = cur.fetchone()[0]

    db.commit()

    return jsonify({
        "id": video_id,
        "company_name": company_name,
        "video_url": video_url,
        "processed_video_url": processed_url,
        "processing_status": status,
    }), 200


@app.get("/get_video_url")
def get_video_url():
    company_name = (request.args.get("company_name") or "").strip()
    if not company_name:
        return jsonify({"error": "параметр 'company_name' обязателен"}), 400

    with get_db().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, company_name, video_url, processed_video_url,
                   processing_status, processing_error
            FROM videos
            WHERE company_name = %s
            """,
            (company_name,),
        )
        row = cur.fetchone()

    if row is None:
        return jsonify({"error": "видео не найдено", "company_name": company_name}), 404

    return jsonify(dict(row)), 200

@app.get("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory(str(UPLOAD_DIR), filename, conditional=True)


@app.get("/videos")
def list_videos():
    with get_db().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, company_name, file_path, video_url,
                   processed_file_path, processed_video_url,
                   processing_status, processing_error,
                   created_at::text AS created_at,
                   updated_at::text AS updated_at,
                   processed_at::text AS processed_at
            FROM videos
            ORDER BY id
        """)
        rows = cur.fetchall()

    return jsonify([dict(row) for row in rows])

@app.post("/videos/<int:video_id>/process")
def process_video(video_id):
    db = get_db()

    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, processing_status FROM videos WHERE id = %s FOR UPDATE",
            (video_id,),
        )
        row = cur.fetchone()

        if row is None:
            return jsonify({"error": "видео не найдено"}), 404

        status = row["processing_status"]

        if status == "skipped":
            return jsonify({"error": "у видео нет событий зума"}), 409

        if status in ("pending", "processing"):
            return jsonify({"error": "видео уже в очереди", "processing_status": status}), 409

        cur.execute(
            """
            UPDATE videos
            SET processing_status = 'pending',
                processing_error = NULL,
                updated_at = NOW()
            WHERE id = %s
            """,
            (video_id,),
        )

    db.commit()
    return jsonify({"id": video_id, "processing_status": "pending"}), 202


def main():
    init_db()
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "8000"))
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
