from __future__ import annotations

import re

import pytest
import requests

from newsattention import __version__
from newsattention.client import (
    Budget,
    CallCapReached,
    SourceBlocked,
    UsageLog,
    family_of,
    now_utc,
    user_agent,
)
from tests.conftest import FakeResponse

API = "https://en.wikipedia.org/w/api.php"
REST = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/x"


def ok(body=None, **kw):
    return lambda m, u, p, h: FakeResponse(200, body if body is not None else {"ok": 1}, **kw)


def test_user_agent_has_project_version_contact_and_library():
    ua = user_agent()
    assert ua.startswith(f"newsattention/{__version__} (https://github.com/obadaKraishan) ")
    assert re.search(r"python-requests/\d", ua)
    assert "@" not in ua


def test_now_utc_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", now_utc())


@pytest.mark.parametrize(
    ("host", "path", "family"),
    [
        ("wikimedia.org", "/api/rest_v1/metrics/pageviews/top/x", "analytics"),
        ("www.wikidata.org", "/w/api.php", "wikidata"),
        ("de.wikipedia.org", "/w/api.php", "action"),
        ("analytics.wikimedia.org", "/published/x.tsv", "files"),
        ("dumps.wikimedia.org", "/other/x", "files"),
        ("doc.wikimedia.org", "/x.html", "web"),
    ],
)
def test_family_of(host, path, family):
    assert family_of(host, path) == family


def test_every_request_is_logged_with_metadata_only(make_client, tmp_path):
    client, session = make_client(ok({"a": "b"}))
    client.get(API, {"titles": "X"})
    rows = UsageLog(tmp_path / "usage_log.csv").rows()
    assert rows == [
        {
            "time": "2026-11-13T15:00:00Z",
            "method": "GET",
            "host": "en.wikipedia.org",
            "path": "/w/api.php",
            "status": "200",
            "bytes": str(len(b'{"a": "b"}')),
        }
    ]
    headers = session.calls[0][3]
    assert headers["User-Agent"] == user_agent()


def test_usage_log_rows_of_missing_file_is_empty(tmp_path):
    assert UsageLog(tmp_path / "none.csv").rows() == []


def test_retries_429_and_5xx_with_retry_after_then_succeeds(make_client):
    answers = [
        FakeResponse(429, {}, headers={"Retry-After": "7"}),
        FakeResponse(503, {}),
        FakeResponse(200, {"ok": 1}),
    ]
    client, session = make_client(lambda m, u, p, h: answers.pop(0))
    assert client.get_json(REST) == {"ok": 1}
    assert client.sleeps == [7.0, 4.0]
    assert len(session.calls) == 3


def test_retry_after_that_is_not_a_number_falls_back_to_backoff(make_client):
    answers = [FakeResponse(429, {}, headers={"Retry-After": "soon"}), FakeResponse(200, {})]
    client, _ = make_client(lambda m, u, p, h: answers.pop(0))
    client.get(REST)
    assert client.sleeps == [2.0]


def test_gives_up_after_retries(make_client):
    client, session = make_client(lambda m, u, p, h: FakeResponse(500, {}), max_retries=2)
    with pytest.raises(SourceBlocked, match="kept failing"):
        client.get(REST)
    assert len(session.calls) == 3


def test_403_stops_the_source_and_never_retries(make_client):
    client, session = make_client(lambda m, u, p, h: FakeResponse(403, {}))
    with pytest.raises(SourceBlocked, match="blocked"):
        client.get(REST)
    with pytest.raises(SourceBlocked, match="earlier in this run"):
        client.get(REST)
    assert len(session.calls) == 1


def test_action_api_sends_maxlag_and_waits_when_lagged(make_client):
    answers = [
        FakeResponse(200, {"error": {"code": "maxlag"}}, headers={"Retry-After": "5"}),
        FakeResponse(200, {"query": {"pages": []}}),
    ]
    client, session = make_client(lambda m, u, p, h: answers.pop(0))
    data = client.action_api(API, {"action": "query"})
    assert data == {"query": {"pages": []}}
    params = session.calls[0][2]
    assert params["maxlag"] == 5
    assert params["format"] == "json"
    assert params["formatversion"] == "2"
    assert client.sleeps == [5.0]


def test_maxlag_also_applies_to_wikidata(make_client):
    client, session = make_client(
        lambda m, u, p, h: FakeResponse(200, {"error": {"code": "maxlag"}}), max_retries=1
    )
    with pytest.raises(SourceBlocked):
        client.action_api("https://www.wikidata.org/w/api.php", {"action": "wbgetentities"})
    assert len(session.calls) == 2


def test_action_api_error_and_404(make_client):
    client, _ = make_client(ok({"error": {"code": "badvalue"}}))
    with pytest.raises(RuntimeError, match="badvalue"):
        client.action_api(API, {})
    client, _ = make_client(lambda m, u, p, h: FakeResponse(404, {}))
    with pytest.raises(RuntimeError, match="404"):
        client.action_api(API, {})


def test_non_json_action_answer_is_not_maxlag(make_client):
    client, _ = make_client(lambda m, u, p, h: FakeResponse(200, content=b"<html>"))
    resp = client.get(API)
    assert resp.status_code == 200


def test_get_json_404_is_none_and_other_errors_raise(make_client):
    client, _ = make_client(lambda m, u, p, h: FakeResponse(404, {}))
    assert client.get_json(REST) is None
    client, _ = make_client(lambda m, u, p, h: FakeResponse(400, {}))
    with pytest.raises(requests.HTTPError):
        client.get_json(REST)


def test_call_cap_stops_before_the_request(make_client):
    budget = Budget(caps={"analytics": 2})
    client, session = make_client(ok(), budget=budget)
    client.get(REST)
    client.get(REST)
    with pytest.raises(CallCapReached, match="analytics call cap"):
        client.get(REST)
    assert len(session.calls) == 2


def test_budget_from_log_counts_calls_since(tmp_path):
    log = UsageLog(tmp_path / "log.csv")
    log.append(
        "GET", "https://wikimedia.org/api/rest_v1/metrics/a", 200, 10, "2026-11-12T00:00:00Z"
    )
    log.append(
        "GET", "https://wikimedia.org/api/rest_v1/metrics/a", 200, 20, "2026-11-13T00:00:00Z"
    )
    log.append("GET", "https://www.wikidata.org/w/api.php", 200, 5, "2026-11-13T01:00:00Z")
    budget = Budget.from_log(log.rows(), "2026-11-13T00:00:00Z")
    assert budget.used == {"analytics": 1, "wikidata": 1}
    assert budget.bytes_used == 25


def test_byte_cap(make_client):
    budget = Budget(max_bytes=100)
    budget.check_bytes(100)
    with pytest.raises(CallCapReached, match="over the cap"):
        budget.check_bytes(101)


def test_head_size_asks_for_the_uncompressed_size(make_client):
    client, session = make_client(ok(headers={"Content-Length": "1234"}))
    assert client.head_size("https://analytics.wikimedia.org/x.tsv") == 1234
    method, _, _, headers = session.calls[0]
    assert method == "HEAD"
    assert headers["Accept-Encoding"] == "identity"


def test_head_size_unknown_and_missing(make_client):
    client, _ = make_client(ok())
    assert client.head_size("https://analytics.wikimedia.org/x.tsv") is None
    client, _ = make_client(lambda m, u, p, h: FakeResponse(404, {}))
    assert client.head_size("https://analytics.wikimedia.org/x.tsv") is None


def test_download_writes_once_read_only_and_logs_bytes(make_client, tmp_path):
    client, _ = make_client(lambda m, u, p, h: FakeResponse(200, content=b"a\tb\n" * 10))
    dest = tmp_path / "raw" / "f.tsv"
    assert client.download("https://analytics.wikimedia.org/f.tsv", dest, expected_size=40) == 40
    assert dest.read_bytes() == b"a\tb\n" * 10
    assert not (dest.stat().st_mode & 0o222)
    assert client.log.rows()[-1]["bytes"] == "40"
    with pytest.raises(FileExistsError, match="written once"):
        client.download("https://analytics.wikimedia.org/f.tsv", dest)


def test_download_refuses_a_file_over_the_byte_cap(make_client, tmp_path):
    client, session = make_client(ok(), budget=Budget(max_bytes=10))
    with pytest.raises(CallCapReached):
        client.download("https://analytics.wikimedia.org/f.tsv", tmp_path / "f", expected_size=11)
    assert session.calls == []


def test_download_stops_mid_stream_at_the_byte_cap_and_leaves_no_file(make_client, tmp_path):
    client, _ = make_client(
        lambda m, u, p, h: FakeResponse(200, content=b"x" * (3 << 20)),
        budget=Budget(max_bytes=1 << 20),
    )
    dest = tmp_path / "f.tsv"
    with pytest.raises(CallCapReached, match="during a download"):
        client.download("https://analytics.wikimedia.org/f.tsv", dest)
    assert not dest.exists()
    assert not (tmp_path / "f.tsv.part").exists()


def test_download_of_a_missing_file(make_client, tmp_path):
    client, _ = make_client(lambda m, u, p, h: FakeResponse(404, {}))
    with pytest.raises(requests.HTTPError):
        client.download("https://analytics.wikimedia.org/f.tsv", tmp_path / "f")
    assert client.log.rows()[-1]["status"] == "404"


def test_download_blocked(make_client, tmp_path):
    client, _ = make_client(lambda m, u, p, h: FakeResponse(403, {}))
    with pytest.raises(SourceBlocked):
        client.download("https://analytics.wikimedia.org/f.tsv", tmp_path / "f")
    assert client.log.rows()[-1]["status"] == "403"


def test_stream_retry_is_logged(make_client, tmp_path):
    answers = [FakeResponse(503, {}), FakeResponse(200, content=b"abc")]
    client, _ = make_client(lambda m, u, p, h: answers.pop(0))
    client.download("https://analytics.wikimedia.org/f.tsv", tmp_path / "f")
    assert [r["status"] for r in client.log.rows()] == ["503", "200"]


def test_min_interval_spaces_requests(make_client):
    ticks = iter([0.0, 0.1, 5.0])
    client, _ = make_client(ok(), min_interval=0.35, monotonic=lambda: next(ticks))
    client.get(REST)
    client.get(REST)
    client.get(REST)
    assert client.sleeps == [pytest.approx(0.25)]
