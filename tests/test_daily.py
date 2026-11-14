"""The daily command against one fake server for every endpoint. All data are invented."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from newsattention import backfill, daily, tables
from newsattention.backfill import Store
from newsattention.portal import PortalPage
from tests.conftest import FakeResponse

TODAY = date(2025, 3, 20)
DAY = date(2025, 3, 19)
OLD_DAY = date(2025, 3, 12)  # 7 days before DAY: its items get a follow-up call
TEXT = "'''Sports'''\n*[[Fakeland]] wins. [https://example.com/a (X)]\n"
TEXT_NEW = "'''Sports'''\n*[[Newland]] votes. [https://example.com/b (X)]\n"
IDS = {"Fakeland": (100, "Q1"), "Newland": (200, "Q2")}


def handler(method, url, params, headers):
    if url == "https://en.wikipedia.org/w/api.php":
        if params.get("prop") == "revisions":
            pages = [
                {
                    "title": t,
                    "pageid": 5,
                    "revisions": [
                        {
                            "revid": 9,
                            "timestamp": "2025-03-20T00:00:00Z",
                            "slots": {"main": {"content": TEXT_NEW if "March 19" in t else TEXT}},
                        }
                    ],
                }
                for t in params["titles"].split("|")
            ]
            return FakeResponse(200, {"query": {"pages": pages}})
        if params.get("list") == "logevents":
            return FakeResponse(200, {"query": {"logevents": []}})
        pages = [
            {"title": t, "pageid": IDS[t][0], "pageprops": {"wikibase_item": IDS[t][1]}}
            for t in params["titles"].split("|")
        ]
        return FakeResponse(200, {"query": {"pages": pages}})
    if url == "https://de.wikipedia.org/w/api.php":
        return FakeResponse(
            200,
            {
                "query": {
                    "pages": [
                        {"pageid": 21, "title": "Neuland", "pageprops": {"wikibase_item": "Q2"}}
                    ]
                }
            },
        )
    if url.startswith("https://analytics.wikimedia.org/"):
        if method == "HEAD":
            return FakeResponse(200, headers={"Content-Length": "60"})
        return FakeResponse(
            200,
            content=(
                b"Fakeland\tFL\ten.wikipedia\t200\tNewland\tQ2\t300\n"
                b"Fakeland\tFL\tde.wikipedia\t21\tNeuland\tQ2\t150\n"
            ),
        )
    if url.startswith("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"):
        return FakeResponse(200, {"items": [{"timestamp": "2025031900", "views": 42}]})
    raise AssertionError(f"unexpected {method} {url}")


def _store_with_q1(tmp_path, days, covered_until):
    """A store whose portal days ``days`` link Fakeland (Q1), fetched up to ``covered_until``."""
    store = Store(tmp_path / "store", tmp_path / "raw")
    for d in days:
        title = f"Portal:Current events/{d.year} {d.strftime('%B')} {d.day}"
        read_at = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
        backfill.record_read(store, PortalPage(title, d, 5, 8, None, TEXT), "first", read_at)
    backfill.append_jsonl(
        store.resolved,
        [
            {
                "linked_title": "Fakeland",
                "title": "Fakeland",
                "page_id": 100,
                "qid": "Q1",
                "redirected": False,
                "resolved_at": "x",
            }
        ],
    )
    entry = {"qid": "Q1", "project": "en.wikipedia", "title": "Fakeland", "page_id": 100}
    entry |= {"rank": 0, "kind": "current"}
    backfill.append_jsonl(store.root / "api" / "plan.jsonl", [entry])
    status = {"plan_index": 0, "status": "ok", "days": 1, "first": "2025-01-01"}
    backfill.append_jsonl(
        store.root / "api" / "status.jsonl", [status | {"last": covered_until.isoformat()}]
    )
    backfill.write_json(store.root / "api" / "progress.json", {"next": 1})
    return store


def test_daily_runs_every_step(make_client, tmp_path):
    store = _store_with_q1(tmp_path, [OLD_DAY], OLD_DAY)
    client, _session = make_client(handler)
    lines: list[str] = []
    out = daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lines.append)
    assert [line.split(":")[0] for line in lines] == [
        "portal",
        "reread",
        "links",
        "moves",
        "dp",
        "api",
    ]
    assert out["portal"]["read"] == 7  # March 13 to 19: every day after the last one read
    assert out["reread"]["due"] == 1  # the 7-day re-read of March 12
    assert out["links"]["new_items"] == 1
    assert out["dp"]["download"]["downloaded"] == 8  # the week of retries plus the new day
    assert out["dp"]["filter"]["days"] == 8  # filtered again for the new item
    # New item Q2: English and German over the whole span; Q1's 7-day follow-up for its
    # March 12 event, from the day before its last fetched day.
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")[1:]
    assert [(p["qid"], p["project"], p.get("span_start"), p.get("span_end")) for p in plan] == [
        ("Q2", "en.wikipedia", "2025-01-01", "2025-03-19"),
        ("Q2", "de.wikipedia", "2025-01-01", "2025-03-19"),
        ("Q1", "en.wikipedia", "2025-03-11", "2025-03-19"),
    ]
    assert out["api"]["calls"] == 3
    again = daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lambda m: None)
    assert again["links"]["new_items"] == 0 and again["api"]["planned"] == 0


def test_daily_catches_up_after_missed_days(make_client, tmp_path):
    # Read up to March 5 and fetched up to March 5; the next run comes on March 20.
    read = [date(2025, 3, 1) + timedelta(days=k) for k in range(5)]
    store = _store_with_q1(tmp_path, read, date(2025, 3, 5))
    client, _ = make_client(handler)
    out = daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lambda m: None)
    assert out["portal"]["read"] == 14 and out["portal"]["from"] == "2025-03-06"
    assert out["dp"]["from"] == "2025-03-12"  # no file known yet: the last week
    follow = [
        p for p in backfill.read_jsonl(store.root / "api" / "plan.jsonl") if p.get("follow_up")
    ]
    # One call for Q1 closes the gap from its earliest due event (March 1) to March 19.
    assert [(p["qid"], p["span_start"], p["span_end"]) for p in follow] == [
        ("Q1", "2025-03-01", "2025-03-19")
    ]


def test_follow_ups_due_close_the_gap_and_skip_covered_items():
    by_day = {date(2025, 3, 1): {"Q1", "Q2", "Q3"}, date(2025, 3, 15): {"Q2"}}
    covered = {
        ("Q1", "en.wikipedia"): (date(2025, 1, 1), date(2025, 3, 29)),  # reaches day 28
        ("Q2", "en.wikipedia"): (date(2025, 1, 1), date(2025, 3, 3)),
    }
    due, unseen = daily.follow_ups_due(by_day, covered, date(2025, 3, 30))
    # Q2: its March 1 event is due (day 7 and day 28 not reached); Q3 has no series.
    assert due == {"Q2": date(2025, 3, 1)} and unseen == {"Q3"}
    covered[("Q2", "en.wikipedia")] = (date(2025, 1, 1), date(2025, 2, 20))
    due, _ = daily.follow_ups_due(by_day, covered, date(2025, 3, 30))
    assert due == {"Q2": date(2025, 2, 19)}  # no gap: from the day before its last day


def test_follow_up_updates_only_its_days(tmp_path):
    plan = [
        {"qid": "Q1", "project": "en.wikipedia", "title": "T", "kind": "current"},
        {
            "qid": "Q1",
            "project": "en.wikipedia",
            "title": "T",
            "kind": "current",
            "span_start": "2025-01-03",
            "span_end": "2025-01-04",
        },
    ]
    rows = {
        "plan_index": [0, 0, 1],
        "qid": ["Q1"] * 3,
        "project": ["en.wikipedia"] * 3,
        "title": ["T"] * 3,
        "kind": ["current"] * 3,
        "date": [date(2025, 1, 1), date(2025, 1, 3), date(2025, 1, 4)],
        "views": [5, 6, 9],
    }
    pq.write_table(pa.table(rows, schema=backfill.API_SCHEMA), tmp_path / "chunk-0000000.parquet")
    bank = tables.SeriesBank(date(2025, 1, 1), date(2025, 1, 5))
    bank.load([tmp_path / "chunk-0000000.parquet"], plan)
    assert np.array_equal(bank.series[("Q1", "en.wikipedia")], [5, 0, 0, 9, 0])


def test_daily_filters_a_country_file_that_came_late(make_client, tmp_path):
    store = Store(tmp_path / "store", tmp_path / "raw")
    late = "2025-03-15"

    def first_pass(method, url, params, headers):
        if url.startswith("https://analytics.wikimedia.org/") and late in url:
            return FakeResponse(404, {})
        return handler(method, url, params, headers)

    client, _ = make_client(first_pass)
    daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lambda m: None)
    assert not store.dp_rows(date.fromisoformat(late)).exists()
    # Later the file is there; the run has no new items, so nothing is filtered again by force.
    client2, _ = make_client(handler)
    out = daily.run_daily(client2, store, TODAY, date(2025, 1, 1), say=lambda m: None)
    assert out["links"]["new_items"] == 0 and out["dp"]["download"]["downloaded"] == 1
    assert out["dp"]["filter"]["days"] == 1
    assert pq.read_table(store.dp_rows(date.fromisoformat(late))).num_rows == 2


def test_daily_follows_up_redirect_titles_with_their_page(make_client, tmp_path):
    store = _store_with_q1(tmp_path, [OLD_DAY], OLD_DAY)
    redirect = {"qid": "Q1", "project": "en.wikipedia", "title": "Old Fakeland", "page_id": 100}
    redirect |= {"rank": 0, "kind": "redirect", "span_start": "2025-02-01"}
    backfill.append_jsonl(
        store.root / "api" / "plan.jsonl", [redirect | {"span_end": "2025-03-12"}]
    )
    client, _ = make_client(handler)
    daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lambda m: None)
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")
    new = [(p["title"], p["kind"], p["span_start"]) for p in plan[2:] if p["qid"] == "Q1"]
    assert new == [
        ("Fakeland", "current", "2025-03-11"),
        ("Old Fakeland", "redirect", "2025-03-11"),
    ]


def test_daily_plans_the_old_titles_of_a_new_item_that_moved(make_client, tmp_path):
    store = _store_with_q1(tmp_path, [OLD_DAY], OLD_DAY)
    move = {"logid": 1, "page_id": 200, "from_title": "Newland (old)", "from_ns": 0}
    move |= {"to_title": "Newland", "to_ns": 0, "timestamp": "2025-02-10T12:00:00Z"}
    backfill.append_jsonl(store.raw / "movelog" / "ns0" / "2025-02.jsonl", [move])
    client, _ = make_client(handler)
    daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lambda m: None)
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")
    old = [(p["title"], p["span_start"], p["span_end"]) for p in plan if p["kind"] == "old_title"]
    assert old == [("Newland (old)", "2025-01-01", "2025-02-10")]
