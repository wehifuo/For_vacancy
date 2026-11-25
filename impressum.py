from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 20
REQUEST_DELAY_SEC = float(os.environ.get("REQUEST_DELAY_SEC", "1.0"))
MAX_TEXT_CHARS = 8000
TAIL_MARGIN = 400

DEEPSEEK_BASE_URL = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
).rstrip("/")
DEEPSEEK_MODEL_DEFAULT = "deepseek-chat"
DEEPSEEK_RETRIES = 3
DEEPSEEK_TIMEOUT = 60

HEAD_STRONG_RE = re.compile(
    r"(?i)(?:"
    r"Angaben\s+gem(?:äß|aess|äss)\s*§?\s*5\s*(?:TMG|DDG)"
    r"|Anbieter"
    r"|Diensteanbieter"
    r")"
)

HEAD_FALLBACK_RE = re.compile(r"(?i)(?:Impressum|Imprint)")

TAIL_PATTERNS = [
    # +49 123 456789, 0049 123...
    re.compile(r"(?:\+49|0049)[\d\s()/.-]{6,}"),

    # DE 217 733 235, DE316472128
    re.compile(r"\bDE\s?\d{3}\s?\d{3}\s?\d{3}\b", re.I),

    # e-mail
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),

    # HRB 6160, HRA 12345
    re.compile(r"\b(?:HRB|HRA)\s?\d+\b", re.I),

    # ответственные лица / регистрация
    re.compile(
        r"(?i)(?:"
        r"Registergericht"
        r"|Amtsgericht"
        r"|Verantwortlich"
        r"|Vertreten durch"
        r"|Geschäftsführer(?:in)?"
        r"|Inhaltlich verantwortlich"
        r")"
    ),
]

BOILERPLATE_RE = re.compile(
    r"(?i)^(?:"
    r"cookie|datenschutz|agb|©|menü|menu|deutsch|english|"
    r"startseite|zurück|alle cookies|newsletter|warenkorb|"
    r"anmelden|registrieren|zum\s+|zur\s+|zeige alle"
    r")"
)

class DeepSeekError(Exception):
    pass


class DeepSeekParseError(DeepSeekError):
    """DeepSeek ответил, но JSON пустой или невалидный."""


SYSTEM_PROMPT = """\
You extract legally required company information ("Impressum" / "Imprint") from
German-language website text.

Return ONLY a valid JSON object (no markdown fences, no commentary) that parses
with json.loads. The JSON must have exactly these keys:

{
    "company_name": "<string or null>",
    "postal_address": {
        "street": "<string or null>",
        "house_no": "<string or null>",
        "postcode": "<string or null>",
        "city": "<string or null>",
        "country": "<string or null>"
    },
    "handelsregister": "<string or null>",
    "vat_number": "<string or null>",
    "phone": "<string or null>",
    "email": "<string or null>",
    "responsible_person": "<string or null>"
}

Rules:
- Extract ONLY information actually present in the text; use null when absent.
- Do not invent or guess values.
- phone: keep the international format when possible.
- vat_number: German VAT ids look like DE followed by 9 digits.
- email: lowercase.
- responsible_person: the named person or role legally responsible.
- Output valid JSON only.
"""

def call_deepseek(text: str, api_key: str | None = None, model: str | None = None, session: requests.Session | None = None) -> dict:
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekError("DEEPSEEK_API_KEY не задан")

    model = model or os.environ.get(
        "DEEPSEEK_MODEL", DEEPSEEK_MODEL_DEFAULT
    )
    session = session or requests.Session()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract the Impressum data from the text below "
                    "and return JSON:\n\n" + text
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 1024,
        "temperature": 0,
    }

    last_error = None
    parse_error = False

    for attempt in range(1, DEEPSEEK_RETRIES + 1):
        try:
            response = session.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=DEEPSEEK_TIMEOUT,
            )

            if response.status_code in (401, 403):
                raise DeepSeekError("Неверный DEEPSEEK_API_KEY")

            response.raise_for_status()

            content = response.json()["choices"][0]["message"]["content"]

            if not content or not content.strip():
                raise ValueError("пустой ответ")

            content = content.strip()

            if content.startswith("```"):
                content = content.strip("`")
                content = re.sub(r"^json\s*", "", content, flags=re.I)
                content = content.strip()

            parsed = json.loads(content)

            if not isinstance(parsed, dict):
                raise ValueError("ответ не JSON-объект")

            return parsed

        except DeepSeekError:
            raise

        except requests.RequestException as error:
            last_error = error
            parse_error = False

            if attempt < DEEPSEEK_RETRIES:
                time.sleep(attempt)

        except (ValueError, KeyError, IndexError) as error:
            last_error = error
            parse_error = True

            if attempt < DEEPSEEK_RETRIES:
                time.sleep(attempt)

    if parse_error:
        raise DeepSeekParseError(
            f"DeepSeek вернул пустой или невалидный JSON: {last_error}"
        ) from last_error

    raise DeepSeekError(
        f"DeepSeek API error: {last_error}"
    ) from last_error
def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def normalize_url(web: str) -> str | None:
    web = (web or "").strip()

    if not web:
        return None

    if not web.startswith(("http://", "https://")):
        web = "https://" + web

    return web


def fetch_html(url: str, session: requests.Session | None = None) -> str:
    session = session or requests.Session()

    response = session.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"

    return response.text


def find_impressum_url(html: str, base_url: str) -> str | None:
    soup = _soup(html)
    anchors = soup.find_all("a", href=True)

    for anchor in anchors:
        text = anchor.get_text(" ", strip=True).lower()
        if text in {"impressum", "imprint"}:
            return urljoin(base_url, anchor["href"].strip())

    for anchor in anchors:
        href = anchor["href"].strip()

        if href.lower().startswith(("javascript:", "mailto:", "#")):
            continue

        if "impressum" in href.lower() or "imprint" in href.lower():
            return urljoin(base_url, href)

    return None


def extract_visible_text(html: str) -> str:
    soup = _soup(html)

    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "header",
        "footer",
        "form",
    ]):
        tag.decompose()

    raw = soup.get_text("\n")
    lines = []

    for line in raw.splitlines():
        # Служебный символ зарегистрированной торговой марки в Impressum не нужен.
        line = " ".join(line.replace("®", " ").split())
        if line:
            lines.append(line)

    return "\n".join(lines)


def strip_boilerplate(text: str) -> str:
    lines = []

    for line in text.splitlines():
        line = " ".join(line.split())

        if not line:
            continue

        if len(line) <= 120 and BOILERPLATE_RE.search(line):
            continue

        lines.append(line)

    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def optimize_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    if not text:
        return text

    if len(text) <= max_chars:
        return text

    cleaned = strip_boilerplate(text)

    if not cleaned:
        return text

    if len(cleaned) <= max_chars:
        return cleaned

    head = HEAD_STRONG_RE.search(cleaned) or HEAD_FALLBACK_RE.search(cleaned)

    if head is None:
        return text

    last_tail_end = 0

    for pattern in TAIL_PATTERNS:
        for match in pattern.finditer(cleaned):
            last_tail_end = max(last_tail_end, match.end())

    if last_tail_end <= head.start():
        return text

    head_line_start = cleaned.rfind("\n", 0, head.start()) + 1
    previous_line_start = cleaned.rfind("\n", 0, head_line_start - 1) + 1
    previous_line = cleaned[previous_line_start:head_line_start]

    if HEAD_FALLBACK_RE.search(previous_line):
        start = previous_line_start
    else:
        start = head_line_start

    end = min(len(cleaned), last_tail_end + TAIL_MARGIN)

    if end - start > max_chars:
        separator = "\n...\n"
        budget = max_chars - len(separator)
        head_budget = budget // 2
        tail_budget = budget - head_budget

        head_part = cleaned[start:start + head_budget]
        tail_start = max(start + head_budget, end - tail_budget)
        tail_part = cleaned[tail_start:end]
        cut = head_part + separator + tail_part
    else:
        cut = cleaned[start:end]

    has_head = bool(HEAD_STRONG_RE.search(cut) or HEAD_FALLBACK_RE.search(cut))
    has_signal = any(pattern.search(cut) for pattern in TAIL_PATTERNS)

    if not has_head or not has_signal:
        return text

    return cut


def fetch_impressum_text(
    web: str,
    session: requests.Session | None = None,
) -> tuple[str | None, str | None]:
    home_url = normalize_url(web)

    if not home_url:
        return None, None

    session = session or requests.Session()
    home_html = fetch_html(home_url, session)
    impressum_url = find_impressum_url(home_html, home_url)

    if not impressum_url:
        return None, None

    if REQUEST_DELAY_SEC > 0:
        time.sleep(REQUEST_DELAY_SEC)

    impressum_html = fetch_html(impressum_url, session)
    return impressum_url, extract_visible_text(impressum_html)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Найти Impressum и сократить его текст",
    )
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--max-chars",
        type=int,
        default=MAX_TEXT_CHARS,
    )
    args = parser.parse_args(argv)

    try:
        impressum_url, text = fetch_impressum_text(args.url)
    except requests.RequestException as error:
        print(f"HTTP ошибка: {error}", file=sys.stderr)
        return 1

    if text is None:
        print("Impressum/Imprint не найден", file=sys.stderr)
        return 1

    optimized = optimize_text(text, args.max_chars)

    print(f"Impressum URL: {impressum_url}")
    print(f"chars: {len(text)} -> {len(optimized)}")
    print(
        f"tokens ~: {estimate_tokens(text)} -> "
        f"{estimate_tokens(optimized)}"
    )
    print("--- optimized text ---")
    print(optimized)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
