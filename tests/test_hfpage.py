"""Signed-out checks of the Hugging Face page: no credentials, headings, raw tags."""

from __future__ import annotations

import json

import pytest
import requests

from newsattention import hfpage


class FakeSession(requests.Session):
    def __init__(self, status: int = 200, body: object = None, text: str = "") -> None:
        super().__init__()
        self.trust_env = False
        self.status, self.body, self.page = status, body, text
        self.sent: list[requests.PreparedRequest] = []

    def send(self, request, **kwargs):  # type: ignore[override]
        self.sent.append(request)
        r = requests.Response()
        r.status_code = self.status
        r._content = json.dumps(self.body).encode() if self.body is not None else self.page.encode()
        return r


def test_visibility_is_asked_signed_out():
    s = FakeSession(200, {"private": False})
    assert hfpage.visibility("o/d", s) == ("public", 200)
    assert not any(h.lower() in hfpage.CREDENTIAL_HEADERS for h in s.sent[0].headers)
    assert hfpage.visibility("o/d", FakeSession(401)) == ("not public", 401)
    assert hfpage.visibility("o/d", FakeSession(404)) == ("not public", 404)
    for bad in (FakeSession(500), FakeSession(200, {"private": True}), FakeSession(200, None, "x")):
        with pytest.raises(hfpage.PageCheckError):
            hfpage.visibility("o/d", bad)


def test_a_signed_out_request_refuses_credentials():
    s = FakeSession(200, {"private": False})
    s.headers["Authorization"] = "Bearer secret"
    with pytest.raises(hfpage.PageCheckError, match="carry"):
        hfpage.signed_out_get("https://huggingface.co/x", s)
    session = hfpage.signed_out_session()
    assert session.trust_env is False and "User-Agent" in session.headers


def test_an_unreachable_page_is_an_error():
    class Down(FakeSession):
        def send(self, request, **kwargs):  # type: ignore[override]
            raise requests.ConnectionError("down")

    with pytest.raises(hfpage.PageCheckError, match="could not reach"):
        hfpage.signed_out_get("https://huggingface.co/x", Down())


def test_headings_and_raw_tags():
    card = "---\nlicense: x\n---\n# Title\n\n```\n# not a heading\n```\n## Two `code`\n"
    assert hfpage.card_headings(card) == ["Title", "Two code"]
    html = "<h1>Site</h1><h1>Title</h1><p>x</p><h2>Two code</h2>"
    assert hfpage.heading_problems(card, html) == []
    assert hfpage.heading_problems(card, "<h2>Two code</h2><h1>Title</h1>") == [
        "out of order on the page: 'Two code'"
    ]
    assert hfpage.heading_problems(card, "<h1>Title</h1>") == ["not on the page: 'Two code'"]
    assert hfpage.heading_problems("no headings", "") == ["the card has no headings"]
    text = "a `<code>` and <https://example.org> fine\n\n<b>bold</b>\n"
    assert hfpage.raw_tags(text) == [(3, "<b>"), (3, "</b>")]
    assert hfpage.tag_problems("X", "<i>")[0].startswith("X line 1: '<i>'")
