"""End-to-end sample run on invented pages and counts, through the command line."""

from __future__ import annotations

import json
from datetime import date

import pytest

from newsattention import cli
from newsattention.pipeline import EN, Sample, read_jsonl, read_views_csv
from newsattention.schema import Views
from newsattention.validate import validate_file
from tests.conftest import FakeResponse

DAY1 = """'''Sports'''
*[[Made-up Cup]]
**[[Fakeland]] wins the final. [https://www.example.com/a (Example)]
"""
DAY2 = """'''Politics and elections'''
*[[Otherland]] holds a vote. [https://news.example.org/b (Example News)]
"""

DP_FILE = (
    "Fakeland\tFL\ten.wikipedia\t1\tFakeland\tQ1\t500\n"
    "Fakeland\tFL\tde.wikipedia\t11\tFakeland_(Staat)\tQ1\t300\n"
    "Fakeland\tFL\tfr.wikipedia\t21\tFakeland_(pays)\tQ1\t200\n"
    "Otherland\tOL\ten.wikipedia\t2\tOtherland\tQ2\t150\n"
    "Otherland\tOL\twikidata\t3\tQ2\tQ2\t150\n"
    "Otherland\tOL\ten.wikipedia\t4\tUnrelated\tQ9\t900\n"
)


def handler(method, url, params, headers):
    if url == "https://en.wikipedia.org/w/api.php" and params.get("prop") == "revisions":
        pages = []
        for title in params["titles"].split("|"):
            text = {
                "Portal:Current events/2025 March 2": DAY1,
                "Portal:Current events/2025 March 3": DAY2,
            }.get(title)
            if text is None:
                pages.append({"title": title, "missing": True})
            else:
                pages.append(
                    {
                        "title": title,
                        "pageid": 5,
                        "revisions": [
                            {
                                "revid": 1000,
                                "timestamp": "2025-03-04T00:00:00Z",
                                "slots": {"main": {"content": text}},
                            }
                        ],
                    }
                )
        return FakeResponse(200, {"query": {"pages": pages}})
    if url == "https://en.wikipedia.org/w/api.php":
        props = {"Fakeland": ("Q1", 1), "Made-up Cup": ("Q3", 3), "Otherland": ("Q2", 2)}
        pages = [
            {"title": t, "pageid": props[t][1], "pageprops": {"wikibase_item": props[t][0]}}
            for t in params["titles"].split("|")
        ]
        return FakeResponse(200, {"query": {"pages": pages}})
    if url.startswith("https://analytics.wikimedia.org/"):
        empty = url.endswith("2025-03-01.tsv")
        if method == "HEAD":
            return FakeResponse(
                200, headers={"Content-Length": "0" if empty else str(len(DP_FILE))}
            )
        return FakeResponse(200, content=DP_FILE.encode())
    if url in {"https://de.wikipedia.org/w/api.php", "https://fr.wikipedia.org/w/api.php"}:
        names = {11: ("Fakeland (Staat)", "Q1"), 21: ("Fakeland (pays)", "Q99")}
        pages = [
            {
                "pageid": int(p),
                "title": names[int(p)][0],
                "pageprops": {"wikibase_item": names[int(p)][1]},
            }
            for p in params["pageids"].split("|")
        ]
        return FakeResponse(200, {"query": {"pages": pages}})
    if url.startswith("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"):
        if "/Otherland/" in url:
            return FakeResponse(400, {})
        items = [{"timestamp": f"202503{d:02d}00", "views": 100} for d in range(1, 5)]
        items += [{"timestamp": "2025020300", "views": 50}]
        return FakeResponse(200, {"items": items})
    raise AssertionError(f"unexpected request {method} {url}")


@pytest.fixture
def run(make_client, monkeypatch, tmp_path):
    client, session = make_client(handler)
    monkeypatch.setattr(cli, "_client", lambda log, since, max_bytes, command: client)

    def go(*extra):
        return cli.main(
            [
                "sample",
                "--start",
                "2025-03-01",
                "--end",
                "2025-03-04",
                "--complete-until",
                "2025-03-04",
                "--dp-until",
                "2025-03-03",
                "--out",
                str(tmp_path / "out"),
                "--raw",
                str(tmp_path / "raw"),
                "--seed",
                "1",
                "--api-budget",
                "10",
                *extra,
            ]
        )

    return go, session, tmp_path


def test_sample_end_to_end(run):
    go, _session, tmp = run
    assert go() == 0
    out = tmp / "out"
    events = read_jsonl(out / "events.jsonl")
    assert [e["category"] for e in events] == ["Sports", "Politics and elections"]
    for name in (
        "events.jsonl",
        "event_pages.jsonl",
        "attention.jsonl",
        "views_dp.csv",
        "views_api.csv",
    ):
        report = validate_file(out / name)
        assert report.ok, (name, report.errors)
    dp = read_views_csv(out / "views_dp.csv")
    assert {(v.qid, v.project) for v in dp} == {
        ("Q1", "en.wikipedia"),
        ("Q1", "de.wikipedia"),
        ("Q1", "fr.wikipedia"),
        ("Q2", "en.wikipedia"),
    }
    plan = read_jsonl(out / "api_plan.jsonl")
    # fr.wikipedia's page id belongs to another item, so it is dropped.
    assert [(p["qid"], p["project"]) for p in plan if p["project"] != EN] == [
        ("Q1", "de.wikipedia")
    ]
    status = read_jsonl(out / "api_status.jsonl")
    assert sorted(s["status"] for s in status) == ["error 400", "ok", "ok", "ok"]
    attention = read_jsonl(out / "attention.jsonl")
    assert {a["project"] for a in attention} == {"en.wikipedia", "de.wikipedia"}
    # The invented series is zero on most baseline days, so the median is 0 and there is no lift.
    assert {a["baseline"] for a in attention} == {0.0}
    assert all(a["lift"] is None for a in attention)
    assert json.loads((out / "api_plan.json").read_text())["seed"] == 1
    raw = sorted(p.name for p in (tmp / "raw" / "portal").iterdir())
    assert raw == ["2025-03-02_1000.json", "2025-03-03_1000.json"]
    assert sorted(p.name for p in (tmp / "raw" / "country_project_page").iterdir()) == [
        "2025-03-02.tsv",
        "2025-03-03.tsv",
    ]


def test_a_rerun_spends_no_requests(run):
    go, session, _ = run
    assert go() == 0
    calls = len(session.calls)
    assert go() == 0
    # Every table is read back from disk.
    assert len(session.calls) == calls


def test_stop_after_steps(run, capsys):
    go, _session, tmp = run
    assert go("--stop-after", "resolve") == 0
    assert not (tmp / "out" / "views_dp.csv").exists()
    assert go("--stop-after", "dp") == 0
    assert (tmp / "out" / "views_dp.csv").exists()
    assert go("--stop-after", "plan") == 0
    assert "plan: 4 calls" in capsys.readouterr().out
    assert not (tmp / "out" / "views_api.csv").exists()


def test_plan_api_round_robin_and_budget():
    rows = [
        Views(
            date=date(2025, 3, 2), qid=q, project=p, country="FL", views=v, source="dp", noisy=True
        )
        for q, p, v in [
            ("Q1", "de.wikipedia", 300),
            ("Q1", "fr.wikipedia", 200),
            ("Q2", "fr.wikipedia", 900),
            ("Q1", EN, 999),
        ]
    ]
    plan = Sample.plan_api({"Q1": "Fakeland", "Q2": "Otherland"}, rows, budget=10)
    assert [(p["qid"], p["project"], p["rank"]) for p in plan] == [
        ("Q1", EN, 0),
        ("Q2", EN, 0),
        ("Q1", "de.wikipedia", 1),
        ("Q2", "fr.wikipedia", 1),
        ("Q1", "fr.wikipedia", 2),
    ]
    assert len(Sample.plan_api({"Q1": "Fakeland", "Q2": "Otherland"}, rows, budget=3)) == 3
    ordered = Sample.plan_api({"Q1": "F", "Q2": "O"}, rows, budget=10, other_order=["Q2", "Q1"])
    assert [p["qid"] for p in ordered[2:]] == ["Q2", "Q1", "Q1"]


def test_sizes_command(make_client, monkeypatch, tmp_path, capsys):
    from tests.test_readers import LISTING

    client, _ = make_client(lambda m, u, p, h: FakeResponse(200, content=LISTING.encode()))
    monkeypatch.setattr(cli, "_client", lambda log, since, max_bytes, command: client)
    assert cli.main(["sizes", "--out", str(tmp_path / "sizes.json")]) == 0
    data = json.loads((tmp_path / "sizes.json").read_text())
    assert data["country_project_page"]["files"] == 3
    assert data["country_project_page"]["empty_files"] == ["2031-01-02"]
    assert data["country_project_page"]["days_without_file"] == 0


def test_real_client_factory_reads_the_log(tmp_path):
    log = tmp_path / "log.csv"
    log.write_text(
        "time,method,host,path,status,bytes\n"
        "2031-01-01T00:00:00Z,GET,wikimedia.org,/api/rest_v1/metrics/x,200,5\n"
    )
    client = cli._client(log, "2030-12-31T00:00:00Z", 1000, "sample")
    assert client.budget.used == {"analytics": 1}
    assert client.budget.max_bytes == 1000


def test_dedupe_links_keeps_the_first_link_to_an_article():
    from newsattention.pipeline import dedupe_links
    from newsattention.schema import EventPage

    def page(order, page_id, title, in_text):
        return EventPage(
            event_id="2025-03-02-0a1b2c3d",
            qid=f"Q{page_id}",
            project=EN,
            page_id=page_id,
            page_title=title,
            link_order=order,
            in_text=in_text,
        )

    pages = [
        page(1, 7, "Fakeland", True),
        page(2, 9, "Storm season", True),
        page(3, 9, "Storm season", False),
        page(4, 8, "Otherland", False),
    ]
    out = dedupe_links(pages)
    assert [(p.page_id, p.link_order, p.in_text) for p in out] == [
        (7, 1, True),
        (9, 2, True),
        (8, 3, False),
    ]
