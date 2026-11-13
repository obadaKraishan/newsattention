"""The daily command against one fake server for every endpoint. All data are invented."""

from __future__ import annotations

from datetime import date, datetime, timezone

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
            pages = [{"title": t, "pageid": 5, "revisions": [
                {"revid": 9, "timestamp": "2025-03-20T00:00:00Z",
                 "slots": {"main": {"content": TEXT_NEW if "March 19" in t else TEXT}}}]}
                for t in params["titles"].split("|")]
            return FakeResponse(200, {"query": {"pages": pages}})
        if params.get("list") == "logevents":
            return FakeResponse(200, {"query": {"logevents": []}})
        pages = [{"title": t, "pageid": IDS[t][0], "pageprops": {"wikibase_item": IDS[t][1]}}
                 for t in params["titles"].split("|")]
        return FakeResponse(200, {"query": {"pages": pages}})
    if url == "https://de.wikipedia.org/w/api.php":
        return FakeResponse(200, {"query": {"pages": [
            {"pageid": 21, "title": "Neuland", "pageprops": {"wikibase_item": "Q2"}}]}})
    if url.startswith("https://analytics.wikimedia.org/"):
        if method == "HEAD":
            return FakeResponse(200, headers={"Content-Length": "60"})
        return FakeResponse(200, content=(
            "Fakeland\tFL\ten.wikipedia\t200\tNewland\tQ2\t300\n"
            "Fakeland\tFL\tde.wikipedia\t21\tNeuland\tQ2\t150\n").encode())
    if url.startswith("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"):
        return FakeResponse(200, {"items": [{"timestamp": "2025031900", "views": 42}]})
    raise AssertionError(f"unexpected {method} {url}")


def test_daily_runs_every_step(make_client, tmp_path):
    store = Store(tmp_path / "store", tmp_path / "raw")
    read_at = datetime(2025, 3, 13, tzinfo=timezone.utc)
    title = "Portal:Current events/2025 March 12"
    backfill.record_read(store, PortalPage(title, OLD_DAY, 5, 8, None, TEXT), "first", read_at)
    backfill.append_jsonl(store.resolved, [{"linked_title": "Fakeland", "title": "Fakeland",
                                            "page_id": 100, "qid": "Q1", "redirected": False,
                                            "resolved_at": "x"}])
    client, session = make_client(handler)
    lines: list[str] = []
    out = daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lines.append)
    assert [line.split(":")[0] for line in lines] == [
        "portal", "reread", "links", "moves", "dp", "api"
    ]
    assert out["portal"]["read"] == 1
    assert out["reread"]["due"] == 1  # the 7-day re-read of March 12
    assert out["links"]["new_items"] == 1
    assert out["dp"]["download"]["downloaded"] == 8  # the week of retries plus the new day
    assert out["dp"]["refilter"]["days"] == 7
    # New item Q2: English and German; follow-up for Q1 (its event is 7 days old).
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")
    assert [(p["qid"], p["project"], p.get("follow_up")) for p in plan] == [
        ("Q2", "en.wikipedia", None), ("Q2", "de.wikipedia", None),
        ("Q1", "en.wikipedia", 7),
    ]
    assert out["api"]["calls"] == 3
    again = daily.run_daily(client, store, TODAY, date(2025, 1, 1), say=lambda m: None)
    assert again["links"]["new_items"] == 0 and again["api"]["planned"] == 1


def test_follow_up_updates_only_its_days(tmp_path):
    plan = [
        {"qid": "Q1", "project": "en.wikipedia", "title": "T", "kind": "current"},
        {"qid": "Q1", "project": "en.wikipedia", "title": "T", "kind": "current",
         "span_start": "2025-01-03", "span_end": "2025-01-04"},
    ]
    rows = {"plan_index": [0, 0, 1], "qid": ["Q1"] * 3, "project": ["en.wikipedia"] * 3,
            "title": ["T"] * 3, "kind": ["current"] * 3,
            "date": [date(2025, 1, 1), date(2025, 1, 3), date(2025, 1, 4)],
            "views": [5, 6, 9]}
    pq.write_table(pa.table(rows, schema=backfill.API_SCHEMA), tmp_path / "chunk-0000000.parquet")
    bank = tables.SeriesBank(date(2025, 1, 1), date(2025, 1, 5))
    bank.load([tmp_path / "chunk-0000000.parquet"], plan)
    assert np.array_equal(bank.series[("Q1", "en.wikipedia")], [5, 0, 0, 9, 0])
