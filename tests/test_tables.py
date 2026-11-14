"""Table builders on an invented store: events, pages, country rows and API chunks."""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from newsattention import backfill, measures, tables
from newsattention.backfill import Store
from newsattention.portal import PortalPage
from newsattention.validate import validate_file

START = date(2025, 1, 1)
EVENT_DAY = date(2025, 2, 5)
LAST = date(2025, 2, 20)
TEXT = "'''Sports'''\n*[[Made-up Cup]]\n**[[Fakeland]] wins. [https://example.com/a (X)]\n"


def test_summary_from_array_matches_measures():
    rng = random.Random(3)
    for _ in range(50):
        n = 70
        arr = np.array([rng.choice([0, 5, 20, 100, 400]) for _ in range(n)], dtype=np.int64)
        event = START + timedelta(days=rng.randint(20, 60))
        last = START + timedelta(days=rng.randint(30, n - 1))
        series = {START + timedelta(days=i): int(arr[i]) for i in range(n)}
        series = {d: v for d, v in series.items() if d <= last}
        expect = measures.summarize(series, event, last)
        got = tables.summary_from_array(arr, START, event, last)
        if event > last:
            assert got.observed_days == 0 and got.views_day0 is None
            continue
        assert got == expect


def test_series_bank_joins_moved_titles(tmp_path):
    plan = [
        {"qid": "Q1", "project": "en.wikipedia", "title": "New", "kind": "current"},
        {"qid": "Q2", "project": "de.wikipedia", "title": "Zwei", "kind": "current"},
        {
            "qid": "Q1",
            "project": "en.wikipedia",
            "title": "Old",
            "kind": "old_title",
            "span_start": "2025-01-01",
            "span_end": "2025-01-03",
        },
    ]
    rows = {
        "plan_index": [0, 0, 1, 2, 2, 2],
        "qid": ["Q1", "Q1", "Q2", "Q1", "Q1", "Q1"],
        "project": ["en.wikipedia"] * 2 + ["de.wikipedia"] + ["en.wikipedia"] * 3,
        "title": ["New", "New", "Zwei", "Old", "Old", "Old"],
        "kind": ["current", "current", "current", "old_title", "old_title", "old_title"],
        "date": [
            date(2025, 1, 3),
            date(2025, 1, 4),
            date(2025, 1, 2),
            date(2025, 1, 1),
            date(2025, 1, 2),
            date(2025, 1, 3),
        ],
        "views": [10, 20, 7, 100, 90, 30],
    }
    pq.write_table(pa.table(rows, schema=backfill.API_SCHEMA), tmp_path / "chunk-0000000.parquet")
    pq.write_table(
        pa.table({k: [] for k in rows}, schema=backfill.API_SCHEMA),
        tmp_path / "chunk-0000003.parquet",
    )
    bank = tables.SeriesBank(START, date(2025, 1, 5))
    bank.load(sorted(tmp_path.glob("chunk-*.parquet")), plan)
    assert list(bank.series[("Q1", "en.wikipedia")]) == [100, 90, 40, 20, 0]
    assert bank.joined == {("Q1", "en.wikipedia")}
    assert bank.as_dict(("Q2", "de.wikipedia"), date(2025, 1, 3)) == {
        date(2025, 1, 1): 0,
        date(2025, 1, 2): 7,
        date(2025, 1, 3): 0,
    }
    out = tables.write_views_api(bank, tmp_path / "tables", say=lambda m: None)
    assert out == {"views_api": 5, "series": 2, "joined": 1}
    assert validate_file(tmp_path / "tables" / "views_api" / "2025-01.parquet").ok


def make_store(tmp_path) -> Store:
    store = Store(tmp_path / "store", tmp_path / "raw")
    title = "Portal:Current events/2025 February 5"
    page = PortalPage(title, EVENT_DAY, 9, 5, "2025-02-06T00:00:00Z", TEXT)
    backfill.record_read(store, page, "first", datetime(2025, 2, 21, tzinfo=timezone.utc))
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
            },
            {
                "linked_title": "Made-up Cup",
                "title": "Made-up Cup",
                "page_id": 200,
                "qid": "Q2",
                "redirected": False,
                "resolved_at": "x",
            },
        ],
    )
    backfill.append_jsonl(
        store.anchors,
        [
            {"page_id": 50, "first_revision": "2020-01-01T00:00:00Z"},
            {"page_id": 300, "first_revision": "2025-01-01T00:00:00Z"},
        ],
    )
    moves = store.raw / "movelog" / "ns0"
    moves.mkdir(parents=True)
    (moves / "2025-01.jsonl").write_text(
        json.dumps(
            {
                "logid": 1,
                "page_id": 200,
                "from_title": "Made-up Cup (2025)",
                "from_ns": 0,
                "to_title": "Made-up Cup",
                "to_ns": 0,
                "timestamp": "2025-01-10T00:00:00Z",
            }
        )
        + "\n"
    )
    # Country rows: FL published every day for Q1 (tracked); OL only on the event day (appeared).
    for k in range(-30, 3):
        day = EVENT_DAY + timedelta(days=k)
        cols = {
            "date": [day],
            "qid": ["Q1"],
            "project": ["en.wikipedia"],
            "page_id": [100],
            "country": ["FL"],
            "views": [800 if k == 0 else 200],
        }
        if k == 0:
            for name, value in (
                ("date", day),
                ("qid", "Q1"),
                ("project", "en.wikipedia"),
                ("page_id", 100),
                ("country", "OL"),
                ("views", 300),
            ):
                cols[name].append(value)
            # A second page of the same item on the same day: the larger count is kept.
            for name, value in (
                ("date", day),
                ("qid", "Q1"),
                ("project", "en.wikipedia"),
                ("page_id", 101),
                ("country", "FL"),
                ("views", 120),
            ):
                cols[name].append(value)
        path = store.dp_rows(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table(cols, schema=backfill.DP_SCHEMA), path)
        backfill.append_jsonl(store.coverage, [{"day": day.isoformat(), "status": "on_disk"}])
    return store


def test_build_everything_on_a_tiny_store(tmp_path):
    store = make_store(tmp_path)
    out = tmp_path / "tables"
    assert tables.build_events(store, out) == {"events": 1, "event_pages": 2}
    assert tables.build_pages(store, out, START, LAST) == {"pages": 2, "moved": 1}
    pages = pq.read_table(out / "pages.parquet").to_pylist()
    assert pages[1]["old_titles"] == ["Made-up Cup (2025)"]
    assert tables.build_views_dp(store, out, say=lambda m: None)["views_dp"] == 35
    bank = tables.SeriesBank(START, LAST)
    n = bank.n
    arr = np.full(n, 50, dtype=np.int64)
    arr[(EVENT_DAY - START).days] = 500
    bank.series[("Q1", "en.wikipedia")] = arr
    bank.series[("Q1", "de.wikipedia")] = np.full(n, 5, dtype=np.int64)
    totals = tables.build_attention(store, out, bank, LAST, say=lambda m: None)
    assert totals == {"attention": 32, "attention_summary": 2, "country_status": 2}
    summary = pq.read_table(out / "attention_summary" / "2025-02.parquet").to_pylist()
    en = next(r for r in summary if r["project"] == "en.wikipedia")
    assert en["lift_day0"] == 10.0 and en["countries_day0"] == 2 and en["languages_lift2"] == 1
    de = next(r for r in summary if r["project"] == "de.wikipedia")
    assert de["lift_day0"] is None  # baseline 5 is under the floor
    status = {
        r["country"]: r
        for r in pq.read_table(out / "country_status" / "2025-02.parquet").to_pylist()
    }
    assert status["FL"]["country_status"] == "tracked" and status["FL"]["lift_day0"] == 4.0
    assert (
        status["FL"]["baseline_file_days"] == 28 and status["FL"]["baseline_published_days"] == 28
    )
    assert status["OL"]["country_status"] == "appeared"
    roles_out = tables.build_roles(store, out, say=lambda m: None)
    assert sum(roles_out["roles"].values()) == 2
    for path in sorted(out.rglob("*.parquet")):
        report = validate_file(path)
        assert report.ok, (path, report.errors)


def test_older_method_days():
    assert tables.older_method("US", date(2023, 5, 1))
    assert not tables.older_method("US", date(2023, 10, 1))
    assert tables.older_method("FR", date(2023, 11, 13))
    assert not tables.older_method("FR", date(2023, 11, 14))


def test_older_method_pairs_need_the_data_to_agree(tmp_path):
    store = Store(tmp_path / "store", tmp_path / "raw")
    backfill.append_jsonl(
        store.root / "dp" / "filter_stats.jsonl",
        [
            {"day": "2023-05-01", "countries_min_450_or_more": ["US", "TV"]},
            {"day": "2023-05-02", "countries_min_450_or_more": []},
            {"day": "2023-11-13", "countries_min_450_or_more": ["FR"]},
        ],
    )
    assert tables.older_method_pairs(store) == {
        (date(2023, 5, 1), "US"),
        (date(2023, 11, 13), "FR"),
    }


def test_pages_leave_out_titles_no_current_event_links(tmp_path):
    store = make_store(tmp_path)
    backfill.append_jsonl(
        store.resolved,
        [
            {
                "linked_title": "Unlinked Place",
                "title": "Unlinked Place",
                "page_id": 999,
                "qid": "Q999",
                "redirected": False,
                "resolved_at": "x",
            }
        ],
    )
    out = tmp_path / "tables"
    assert tables.build_pages(store, out, START, LAST)["pages"] == 2
    assert 999 not in pq.read_table(out / "pages.parquet")["page_id"].to_pylist()


def test_summaries_stop_at_the_last_fetched_day(tmp_path):
    store = make_store(tmp_path)
    out = tmp_path / "tables"
    tables.build_events(store, out)
    tables.build_views_dp(store, out, say=lambda m: None)
    bank = tables.SeriesBank(START, LAST)
    bank.series[("Q1", "en.wikipedia")] = np.full(bank.n, 50, dtype=np.int64)
    # Fetched only up to two days after the event: later days are unknown, not zero.
    bank.covered = {("Q1", "en.wikipedia"): (START, EVENT_DAY + timedelta(days=2))}
    tables.build_attention(store, out, bank, LAST, say=lambda m: None)
    summary = pq.read_table(out / "attention_summary" / "2025-02.parquet").to_pylist()[0]
    assert summary["observed_days"] == 3  # not 16 (to the table's last day)
    assert tables.write_series(bank, out, LAST) == {"series_rows": 1}
    row = pq.read_table(out / "series.parquet").to_pylist()[0]
    assert row["last_day"] == EVENT_DAY + timedelta(days=2)
    assert validate_file(out / "series.parquet").ok


def test_coverage_from_status_lines():
    plan = [
        {"qid": "Q1", "project": "en.wikipedia", "title": "A", "kind": "current"},
        {"qid": "Q1", "project": "en.wikipedia", "title": "Old A", "kind": "old_title"},
        {"qid": "Q1", "project": "en.wikipedia", "title": "A", "kind": "current"}
        | {"span_start": "2025-02-01", "span_end": "2025-02-20"},
        {"qid": "Q2", "project": "en.wikipedia", "title": "B", "kind": "current"},
        {"qid": "Q3", "project": "en.wikipedia", "title": "C", "kind": "current"},
    ]
    statuses = [
        {"plan_index": 0, "status": "ok", "days": 3},  # written before spans were recorded
        {"plan_index": 1, "status": "ok", "days": 3, "first": "2025-01-01", "last": "2025-03-01"},
        {"plan_index": 2, "status": "ok", "days": 3, "first": "2025-02-01", "last": "2025-02-20"},
        {"plan_index": 3, "status": "no views", "days": 0},
        {"plan_index": 4, "status": "error 500"},
    ]
    got = backfill.coverage(plan, statuses, date(2025, 2, 10), START)
    assert got == {
        ("Q1", "en.wikipedia"): (START, date(2025, 2, 20)),
        ("Q2", "en.wikipedia"): (START, date(2025, 2, 10)),
    }
    import pytest

    with pytest.raises(ValueError, match="meta.json is missing"):
        backfill.coverage(plan, statuses, None, START)


def test_review_sheets_command_writes_blind_sheets_and_a_separate_key(tmp_path, monkeypatch):
    from newsattention import cli, review

    store = make_store(tmp_path)
    out = tmp_path / "tables"
    tables.build_events(store, out)
    tables.build_pages(store, out, START, LAST)
    tables.build_views_dp(store, out, say=lambda m: None)
    bank = tables.SeriesBank(START, LAST)
    bank.series[("Q1", "en.wikipedia")] = np.full(bank.n, 50, dtype=np.int64)
    tables.build_attention(store, out, bank, LAST, say=lambda m: None)
    monkeypatch.setattr(review, "YEAR_SIZES", {2025: 1})
    key = tmp_path / "key" / "answer_key.json"
    sheets = tmp_path / "sheets"
    argv = ["review-sheets", "--store", str(store.root), "--raw", str(store.raw)]
    argv += ["--tables", str(out), "--out", str(sheets), "--key", str(key)]
    assert cli.main(argv) == 0
    assert sorted(p.name for p in sheets.iterdir()) == ["guide.md", "sheet-1.xlsx"]
    entry = json.loads(key.read_text())["events"][0]
    assert entry["sheet"] == "sheet-1.xlsx" and entry["Q1"] in ("none", 1, 2)
    check = review.check_sheet(sheets / "sheet-1.xlsx")
    assert check.events == 1 and check.answers[0]["event_id"] == entry["event_id"]
