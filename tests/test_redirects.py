"""Views through old titles that now redirect to a moved page. Invented titles; no network."""

from __future__ import annotations

from datetime import date

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from newsattention import backfill, tables
from newsattention.backfill import Store
from tests.conftest import FakeResponse

D = date.fromisoformat


def test_redirect_periods_skip_the_days_a_title_is_the_page_own():
    end = D("2025-01-31")
    assert backfill.redirect_periods([(D("2025-01-01"), D("2025-01-10"))], end) == [
        (D("2025-01-11"), end)
    ]
    # A to B on the 10th, back to A on the 20th, to C on the 25th: A redirects 11-19, 26-31.
    own = [(D("2025-01-20"), D("2025-01-25")), (D("2025-01-01"), D("2025-01-10"))]
    assert backfill.redirect_periods(own, end) == [
        (D("2025-01-11"), D("2025-01-19")),
        (D("2025-01-26"), end),
    ]
    assert backfill.redirect_periods([(D("2025-01-01"), end)], end) == []


def plan_entry(title, kind, start=None, end=None, qid="Q1", page_id=7):
    e = {"qid": qid, "project": "en.wikipedia", "title": title, "page_id": page_id, "rank": 0}
    e["kind"] = kind
    if start:
        e |= {"span_start": start, "span_end": end}
    return e


def handler(method, url, params, headers):
    # Old A now redirects to page 7; Old B is a separate article; Old C is gone.
    query = {
        "redirects": [{"from": "Old A", "to": "Fakeland Cup"}],
        "pages": [
            {"title": "Fakeland Cup", "pageid": 7},
            {"title": "Old B", "pageid": 99},
            {"title": "Old C", "missing": True},
        ],
    }
    return FakeResponse(200, {"query": query})


def test_plan_redirects_only_for_titles_that_lead_to_the_page(make_client, tmp_path):
    store = Store(tmp_path / "store", tmp_path / "raw")
    plan = [
        plan_entry("Fakeland Cup", "current"),
        plan_entry("Old A", "old_title", "2025-01-01", "2025-01-10"),
        plan_entry("Old B", "old_title", "2025-01-10", "2025-01-15"),
        plan_entry("Old C", "old_title", "2025-01-15", "2025-01-16"),
    ]
    covered = {("Q1", "en.wikipedia"): (D("2025-01-01"), D("2025-01-31"))}
    client, session = make_client(handler)
    entries, stats = backfill.plan_redirects(client, store, plan, covered, say=lambda m: None)
    assert [(e["title"], e["span_start"], e["span_end"], e["kind"]) for e in entries] == [
        ("Old A", "2025-01-11", "2025-01-31", "redirect")
    ]
    assert stats == {
        "pages": 1, "old_titles": 3, "redirect_here": 1, "elsewhere": 1, "gone": 1, "calls": 1
    }  # fmt: skip
    calls = len(session.calls)
    again, _ = backfill.plan_redirects(client, store, plan + entries, covered, say=lambda m: None)
    assert again == [] and len(session.calls) == calls  # cached titles, nothing planned twice


def test_redirect_views_add_to_the_series_without_counting_a_day_twice(tmp_path):
    plan = [
        plan_entry("Fakeland Cup", "current"),
        plan_entry("Old A", "redirect", "2025-01-03", "2025-01-05"),
        plan_entry("Old A", "redirect", "2025-01-05", "2025-01-06"),  # a follow-up, overlapping
    ]
    rows = {
        "plan_index": [0, 0, 1, 1, 1, 2, 2],
        "date": [D("2025-01-01"), D("2025-01-04"), D("2025-01-03"), D("2025-01-04"),
                 D("2025-01-05"), D("2025-01-05"), D("2025-01-06")],
        "views": [10, 10, 1, 2, 3, 4, 5],
    }  # fmt: skip
    n = len(rows["date"])
    rows |= {"qid": ["Q1"] * n, "project": ["en.wikipedia"] * n}
    rows |= {"title": [plan[j]["title"] for j in rows["plan_index"]]}
    rows |= {"kind": [plan[j]["kind"] for j in rows["plan_index"]]}
    path = tmp_path / "chunk-0000000.parquet"
    pq.write_table(pa.table(rows, schema=backfill.API_SCHEMA), path)
    bank = tables.SeriesBank(D("2025-01-01"), D("2025-01-07"))
    bank.load([path], plan)
    # Day 5 takes the later call's 4, not 3 + 4.
    assert np.array_equal(bank.series[("Q1", "en.wikipedia")], [10, 0, 1, 12, 4, 5, 0])
    assert ("Q1", "en.wikipedia") in bank.joined
