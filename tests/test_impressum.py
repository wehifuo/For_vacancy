import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import impressum as imp


def test_normalize_url():
    assert imp.normalize_url("nutrimmun.de") == "https://nutrimmun.de"
    assert imp.normalize_url("https://nutrimmun.de") == "https://nutrimmun.de"
    assert imp.normalize_url("") is None


def test_find_impressum_by_text():
    html = '<a href="/impressum/">Impressum</a>'
    assert imp.find_impressum_url(
        html, "https://example.com/"
    ) == "https://example.com/impressum/"


def test_find_impressum_by_href():
    html = '<a href="/imprint">Legal</a>'
    assert imp.find_impressum_url(
        html, "https://example.com/"
    ) == "https://example.com/imprint"


def test_extract_visible_text_removes_noise():
    html = """
    <html><body>
      <nav>Menu</nav>
      <h1>Impressum</h1>
      <script>alert(1)</script>
      <p>Anbieter: ACME GmbH</p>
      <footer>Footer</footer>
    </body></html>
    """
    text = imp.extract_visible_text(html)
    assert "Impressum" in text
    assert "Anbieter: ACME GmbH" in text
    assert "Menu" not in text
    assert "Footer" not in text
    assert "alert" not in text


def test_short_text_unchanged():
    text = "Impressum\nAnbieter\nACME GmbH"
    assert imp.optimize_text(text, max_chars=8000) == text


def test_long_text_is_cut():
    text = (
        "Cookie banner\n" * 500
        + "Impressum\nAnbieter\nACME GmbH\n"
        + ("x" * 4000)
        + "\n+49 123 456789\n"
        + "Footer\n" * 500
    )
    optimized = imp.optimize_text(text, max_chars=1000)

    assert len(optimized) <= 1000
    assert "Impressum" in optimized
    assert "+49 123 456789" in optimized


def test_no_anchor_returns_full_text():
    text = ("x" * 2000) + "\nCookie banner\n" * 500
    assert imp.optimize_text(text, max_chars=1000) == text


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"company_name": "ACME GmbH"}'
                    }
                }
            ]
        }


class FakeSession:
    def post(self, *args, **kwargs):
        return FakeResponse()


def test_deepseek_parses_json():
    payload = imp.call_deepseek(
        "Impressum ACME",
        api_key="test",
        session=FakeSession(),
    )
    assert payload["company_name"] == "ACME GmbH"


def test_deepseek_requires_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    try:
        imp.call_deepseek("text", api_key=None)
    except imp.DeepSeekError:
        pass
    else:
        raise AssertionError("ожидалась DeepSeekError")


class BlankResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": " "}}]}


class BlankSession:
    def post(self, *args, **kwargs):
        return BlankResponse()


def test_deepseek_blank_response_is_parse_error(monkeypatch):
    monkeypatch.setattr(imp.time, "sleep", lambda _: None)

    try:
        imp.call_deepseek(
            "text",
            api_key="test",
            session=BlankSession(),
        )
    except imp.DeepSeekParseError:
        pass
    else:
        raise AssertionError("ожидалась DeepSeekParseError")


def test_delay_between_pages(monkeypatch):
    def fake_fetch(url, session=None):
        if url.endswith("/impressum"):
            return "<html><body>Impressum Anbieter ACME</body></html>"
        return '<a href="/impressum">Impressum</a>'

    sleeps = []

    monkeypatch.setattr(imp, "fetch_html", fake_fetch)
    monkeypatch.setattr(imp, "REQUEST_DELAY_SEC", 0.5)
    monkeypatch.setattr(imp.time, "sleep", sleeps.append)

    imp.fetch_impressum_text("https://example.com")

    assert sleeps == [0.5]

