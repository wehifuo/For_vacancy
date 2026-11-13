import argparse
import csv
import os
import sys
from pathlib import Path

import video_client
from playwright.sync_api import sync_playwright
import qscript

REQUIRED_COLUMNS = [
    "URL",
    "Company Name",
    "Language",
    "Country",
    "Postcode",
    "City",
    "Street",
    "HouseNo",
]

CSV_FILE = Path(__file__).with_name("input.csv")
DEFAULT_VIEW_SECONDS = 5


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server")
    parser.add_argument("--view-seconds", type=int, default=DEFAULT_VIEW_SECONDS)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--no-zoom-demo", action="store_true")
    parser.add_argument("--process", action="store_true")
    parser.add_argument("--wait-processed", type=int, default=0)

    args = parser.parse_args()

    if args.view_seconds < 0:
        parser.error("--view-seconds не может быть отрицательным")

    return args


def preview_video(url, seconds):

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="commit", timeout=30_000)
            page.wait_for_timeout(500)  # дать встроенному плееру отрисоваться

            if seconds > 0:
                page.wait_for_timeout(seconds * 1000)
            else:
                input("Нажмите Enter, чтобы закрыть окно...")
        finally:
            browser.close()


def upload_and_preview(server_url, video_path, company_name, view_seconds, process, wait_processed):
    sidecar = Path(str(video_path) + ".zoom.json")

    info = video_client.UploadVideoInfo(
        server_url,
        video_path,
        company_name,
        sidecar if sidecar.is_file() else None,
    )

    video_url = info["video_url"]
    print(f"    URL: {video_url}")
    print(f"    Статус: {info.get('processing_status')}")

    if process or wait_processed > 0:
        if info.get("processing_status") == "uploaded":
            result = video_client.ProcessVideo(server_url, info["id"])
            print(f"    Обработка: {result.get('processing_status')}")

        if wait_processed > 0:
            info = video_client.WaitForProcessed(
                server_url,
                company_name,
                timeout=wait_processed,
            )
            print(f"    Итог: {info.get('processing_status')}")

    preview_url = info.get("processed_video_url") or video_url
    preview_video(preview_url, view_seconds)
    return preview_url

def main():
    args = parse_args()

    qscript.PATH_TO_VIDEO_FOLDER = os.environ.get(
        "VIDEO_DIR", qscript.PATH_TO_VIDEO_FOLDER
    )

    qscript.HEADLESS = not args.headed
    qscript.DEMO_ZOOM = not args.no_zoom_demo

    if not CSV_FILE.is_file():
        print(f"Файл не найден: {CSV_FILE}")
        return 1

    with CSV_FILE.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter=";", quotechar='"')

        missing = [
            column
            for column in REQUIRED_COLUMNS
            if column not in (reader.fieldnames or [])
        ]
        if missing:
            print("В CSV не хватает колонок: " + ", ".join(missing))
            return 1

        rows = list(reader)

    if not rows:
        print("В csv нет ни одной строки с данными.")
        return 1

    recording_failures = 0
    upload_failures = 0

    for number, row in enumerate(rows, start=1):
        company = row["Company Name"].strip()
        print(f"[{number}/{len(rows)}] {company}")

        try:
            saved_path = qscript.CaptureVideo_Magento(
                url=row["URL"].strip(),
                company_name=company,
                language=row["Language"].strip(),
                country=row["Country"].strip(),
                postcode=row["Postcode"].strip(),
                city=row["City"].strip(),
                street=row["Street"].strip(),
                house_no=row["HouseNo"].strip(),
            )
        except Exception as error:
            recording_failures += 1
            print(f"    Ошибка записи: {error}")
            continue

        if not (saved_path and Path(saved_path).is_file()):
            recording_failures += 1
            print("    Видео не создано")
            continue

        print(f"    Готово: {saved_path}")

        if not args.server:
            continue

        try:
            upload_and_preview(
                args.server,
                saved_path,
                company,
                args.view_seconds,
                args.process,
                args.wait_processed,
            )
        except Exception as error:
            upload_failures += 1
            print(f"    Ошибка загрузки/просмотра: {error}")

    print(f"\nУспешно записано: {len(rows) - recording_failures}")
    if recording_failures:
        print(f"Ошибок записи: {recording_failures}")
    if args.server:
        print(f"Ошибок загрузки/просмотра: {upload_failures}")

    return 1 if (recording_failures or upload_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
