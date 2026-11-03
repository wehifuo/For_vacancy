import csv
import os
import sys
from pathlib import Path

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


def main():
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

    failed = 0

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
            failed += 1
            print(f"    Ошибка: {error}")
            continue

        if saved_path and Path(saved_path).is_file():
            print(f"    Готово: {saved_path}")
        else:
            failed += 1
            print("    Видео не создано")

    print(f"\nУспешно {len(rows) - failed}, с ошибками {failed}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
