from __future__ import annotations

import argparse
import os
import re
import sys
import time

from psycopg2.extras import Json, RealDictCursor

from db import CompanyStatus, connect, init_db
from impressum import (
    DeepSeekParseError,
    call_deepseek,
    estimate_tokens,
    fetch_impressum_text,
    optimize_text,
)


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _email(value):
    value = _text(value)

    if not value or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return None

    return value


def has_any_value(value) -> bool:
    if isinstance(value, dict):
        return any(has_any_value(item) for item in value.values())
    if isinstance(value, list):
        return any(has_any_value(item) for item in value)
    if value is None:
        return False
    return bool(str(value).strip())


def decide_status(payload: dict) -> CompanyStatus:
    if not isinstance(payload, dict) or not has_any_value(payload):
        return CompanyStatus.PARSING_FAILED

    address = payload.get("postal_address")
    if not isinstance(address, dict):
        address = {}

    complete = all(
        _text(address.get(key))
        for key in ("postcode", "city", "street", "house_no")
    )

    if complete:
        return CompanyStatus.OK

    return CompanyStatus.ADDRESS_INCOMPLETE


def build_postal_address(address) -> str | None:
    if not isinstance(address, dict):
        return None

    street = " ".join(
        filter(
            None,
            [
                _text(address.get("street")),
                _text(address.get("house_no")),
            ],
        )
    )
    city = " ".join(
        filter(
            None,
            [
                _text(address.get("postcode")),
                _text(address.get("city")),
            ],
        )
    )

    parts = [
        part
        for part in (
            street,
            city,
            _text(address.get("country")),
        )
        if part
    ]

    return ", ".join(parts) or None


def select_companies(conn, company=None, status=None, limit=None):
    conditions = []
    params = []

    if company:
        conditions.append("company_name = %s")
        params.append(company)

    if status is None:
        conditions.append("(status IS NULL OR status <> %s)")
        params.append(int(CompanyStatus.OK))
    else:
        conditions.append("status = %s")
        params.append(status)

    sql = "SELECT id, company_name, web, status FROM companies"

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY id"

    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def set_status(conn, company_id, status, impressum_url=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE companies
            SET status = %s,
                impressum_url = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (int(status), impressum_url, company_id),
        )


def update_company(conn, company_id, status, impressum_url, payload, fallback_name):
    address = payload.get("postal_address") if isinstance(payload, dict) else {}
    legal_name = _text(payload.get("company_name")) if payload else None

    values = (
        int(status),
        impressum_url,
        legal_name or fallback_name,
        build_postal_address(address),
        _text(payload.get("handelsregister")),
        _text(payload.get("vat_number")),
        _text(payload.get("phone")),
        _email(payload.get("email")),
        _text(payload.get("responsible_person")),
        Json(payload) if payload is not None else None,
        company_id,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE companies
            SET status = %s,
                impressum_url = %s,
                legal_name = %s,
                postal_address = %s,
                handelsregister = %s,
                vat_number = %s,
                phone = %s,
                email = %s,
                responsible_person = %s,
                raw_json = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            values,
        )


def process_company(conn, row) -> CompanyStatus:
    company_id = row["id"]
    company_name = row["company_name"]
    web = row["web"]

    if not web or not str(web).strip():
        print(f"[{company_id}] {company_name}: NO_WEBSITE", flush=True)
        set_status(conn, company_id, CompanyStatus.NO_WEBSITE)
        return CompanyStatus.NO_WEBSITE

    try:
        impressum_url, text = fetch_impressum_text(web)
    except Exception as error:
        print(
            f"[{company_id}] {company_name}: ERROR fetch: {error}",
            flush=True,
        )
        set_status(conn, company_id, CompanyStatus.ERROR)
        return CompanyStatus.ERROR

    if text is None:
        print(
            f"[{company_id}] {company_name}: "
            f"NO_IMPRESSUM_LINK_FOUND ({web})",
            flush=True,
        )
        set_status(
            conn,
            company_id,
            CompanyStatus.NO_IMPRESSUM_LINK_FOUND,
        )
        return CompanyStatus.NO_IMPRESSUM_LINK_FOUND

    optimized = optimize_text(text)

    print(
        f"[{company_id}] {company_name}: "
        f"chars {len(text)} -> {len(optimized)}; "
        f"tokens ~{estimate_tokens(text)} -> "
        f"{estimate_tokens(optimized)}",
        flush=True,
    )

    try:
        payload = call_deepseek(optimized)
    except DeepSeekParseError as error:
        print(
            f"[{company_id}] {company_name}: "
            f"PARSING_FAILED: {error}",
            flush=True,
        )
        update_company(
            conn,
            company_id,
            CompanyStatus.PARSING_FAILED,
            impressum_url,
            {},
            company_name,
        )
        return CompanyStatus.PARSING_FAILED
    except Exception as error:
        print(
            f"[{company_id}] {company_name}: "
            f"ERROR deepseek: {error}",
            flush=True,
        )
        set_status(
            conn,
            company_id,
            CompanyStatus.ERROR,
            impressum_url,
        )
        return CompanyStatus.ERROR

    status = decide_status(payload)
    update_company(
        conn,
        company_id,
        status,
        impressum_url,
        payload,
        company_name,
    )

    print(f"[{company_id}] {company_name}: {status.name}", flush=True)
    return status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Обогащение компаний через DeepSeek",
    )
    parser.add_argument("--company")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--status", type=int)
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Пауза между компаниями в секундах",
    )
    args = parser.parse_args(argv)

    valid_statuses = {int(status) for status in CompanyStatus}

    if args.status is not None and args.status not in valid_statuses:
        parser.error("--status должен быть от 0 до 5")

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit должен быть больше 0")

    delay = (
        args.delay
        if args.delay is not None
        else float(os.environ.get("REQUEST_DELAY_SEC", "1.0"))
    )

    if delay < 0:
        parser.error("--delay не может быть отрицательным")

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(
            "DEEPSEEK_API_KEY не задан. Добавь его в .env",
            file=sys.stderr,
        )
        return 2

    init_db()
    conn = connect()
    conn.autocommit = True
    failures = 0

    try:
        rows = select_companies(
            conn,
            company=args.company,
            status=args.status,
            limit=args.limit,
        )

        print(f"К обработке: {len(rows)}", flush=True)

        for row in rows:
            try:
                status = process_company(conn, row)
                if status == CompanyStatus.ERROR:
                    failures += 1
            except Exception as error:
                failures += 1
                print(
                    f"[{row['id']}] fatal: {error}",
                    file=sys.stderr,
                )

                try:
                    set_status(
                        conn,
                        row["id"],
                        CompanyStatus.ERROR,
                    )
                except Exception:
                    pass

            if delay > 0:
                time.sleep(delay)

    finally:
        conn.close()

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
