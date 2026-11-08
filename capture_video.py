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


def upload_and_preview(server_url, video_path, company_name, view_seconds):

    video_url = video_client.UploadVideo(server_url, video_path, company_name)
    print(f"    URL: {video_url}")
    preview_video(video_url, view_seconds)
    return video_url


def main():
    args = parse_args()

    qscript.PATH_TO_VIDEO_FOLDER = os.environ.get(
        "VIDEO_DIR", qscript.PATH_TO_VIDEO_FOLDER
    )

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
