"""Backfill steps on invented pages, counts and log entries. No network."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pyarrow.parquet as pq
import pytest

from newsattention import backfill
from newsattention.backfill import CreationModel, Store
from newsattention.portal import PortalPage
from tests.conftest import FakeResponse

T0 = datetime(2025, 3, 10, 12, 0, tzinfo=timezone.utc)
PAGE_V1 = "'''Sports'''\n*[[Made-up Cup]]\n**[[Fakeland]] wins. [https://example.com/a (X)]\n"
PAGE_V2 = PAGE_V1 + "*[[Otherland]] votes. [https://example.org/b (Y)]\n"


def page(day: date, rev: int, text: str | None) -> PortalPage:
    title = f"Portal:Current events/{day.year} {day.strftime('%B')} {day.day}"
    if text is None:
        return PortalPage(title, day, None, None, None, None)
    return PortalPage(title, day, 9, rev, "2025-03-05T00:00:00Z", text)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store", tmp_path / "raw")


def test_record_read_writes_raw_once_and_logs_every_read(store):
    day = date(2025, 3, 2)
    first = backfill.record_read(store, page(day, 1, PAGE_V1), "first", T0)
    assert first["changed"] is False and first["events"] == 1
    raw = store.raw / "portal" / "2025-03-02_1.json"
    assert raw.exists() and not (raw.stat().st_mode & 0o222)
    same = backfill.record_read(store, page(day, 1, PAGE_V1), "reread7", T0)
    assert same["changed"] is False
    changed = backfill.record_read(store, page(day, 2, PAGE_V2), "reread30", T0)
    assert changed["changed"] is True
    assert (changed["added"], changed["removed"], changed["reworded"]) == (1, 0, 0)
    assert changed["previous_revision_id"] == 1
    current = store.load_day(day)
    assert current["revision_id"] == 2 and len(current["events"]) == 2
    log = backfill.read_jsonl(store.revisions)
    assert [e["revision_id"] for e in log] == [1, 1, 2]
    assert current["links"][1]["story_level"] == 1


def test_missing_page_is_recorded(store):
    entry = backfill.record_read(store, page(date(2025, 3, 3), 0, None), "first", T0)
    assert entry["events"] == 0
    assert store.load_day(date(2025, 3, 3))["missing"] is True


def test_due_rereads_at_7_and_30_days(store):
    for d in (1, 2, 3):
        backfill.record_read(
            store,
            page(date(2025, 1, d), d, PAGE_V1),
            "first",
            datetime(2025, 1, 4, tzinfo=timezone.utc),
        )
    # Day 1 ends on Jan 2: 7-day re-read due from Jan 9, 30-day from Feb 1.
    assert backfill.due_rereads(store, date(2025, 1, 8)) == []
    assert backfill.due_rereads(store, date(2025, 1, 9)) == [(date(2025, 1, 1), "reread7")]
    # On Feb 2, days 1 and 2 are due for their 30-day re-read; day 3 still owes its 7-day one.
    assert backfill.due_rereads(store, date(2025, 2, 2)) == [
        (date(2025, 1, 1), "reread30"),
        (date(2025, 1, 2), "reread30"),
        (date(2025, 1, 3), "reread7"),
    ]
    # A read on or after the due date satisfies it.
    backfill.record_read(
        store,
        page(date(2025, 1, 1), 1, PAGE_V1),
        "reread30",
        datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    assert backfill.due_rereads(store, date(2025, 2, 2))[0] == (date(2025, 1, 2), "reread30")


def test_portal_backfill_and_reread(make_client, store):
    revs = {"v": 1}

    def handler(method, url, params, headers):
        pages = []
        for title in params["titles"].split("|"):
            text = PAGE_V1 if revs["v"] == 1 else PAGE_V2
            pages.append(
                {
                    "title": title,
                    "pageid": 9,
                    "revisions": [
                        {
                            "revid": revs["v"],
                            "timestamp": "2025-03-01T00:00:00Z",
                            "slots": {"main": {"content": text}},
                        }
                    ],
                }
            )
        return FakeResponse(200, {"query": {"pages": pages}})

    client, session = make_client(handler)
    out = backfill.portal_backfill(
        client,
        store,
        date(2025, 1, 1),
        date(2025, 1, 3),
        now=lambda: datetime(2025, 1, 4, tzinfo=timezone.utc),
    )
    assert out == {"days_wanted": 3, "read": 3, "missing": 0, "requests": 1}
    again = backfill.portal_backfill(client, store, date(2025, 1, 1), date(2025, 1, 3))
    assert again["days_wanted"] == 0 and len(session.calls) == 1
    revs["v"] = 2
    result = backfill.reread(
        client, store, date(2025, 1, 10), now=lambda: datetime(2025, 1, 10, tzinfo=timezone.utc)
    )
    assert result["due"] == 2 and result["changed"] == 2 and result["added"] == 2
    report = backfill.parse_report(store)
    assert report["2025-01"]["days"] == 3
    assert report["2025-01"]["events"] == 5
    assert backfill.reparse(store) == {"days": 3, "events": 5}


def test_resolve_links_caches(make_client, store):
    backfill.record_read(store, page(date(2025, 3, 2), 1, PAGE_V2), "first", T0)

    def handler(method, url, params, headers):
        pages = [
            {"title": t, "pageid": len(t), "pageprops": {"wikibase_item": f"Q{len(t)}"}}
            for t in params["titles"].split("|")
        ]
        return FakeResponse(200, {"query": {"pages": pages}})

    client, session = make_client(handler)
    out = backfill.resolve_links(client, store, say=lambda m: None)
    assert out == {"titles": 3, "resolved_now": 3, "rechecked": 0, "cached": 0}
    assert backfill.resolve_links(client, store, say=lambda m: None)["cached"] == 3
    assert len(session.calls) == 1
    assert backfill.load_resolved(store)["Fakeland"].qid == "Q8"


def test_first_revision_and_anchors(make_client, store):
    def handler(method, url, params, headers):
        pid = int(params["pageids"])
        if pid == 30:
            return FakeResponse(200, {"query": {"pages": [{"pageid": 30, "missing": True}]}})
        return FakeResponse(
            200,
            {
                "query": {
                    "pages": [
                        {
                            "pageid": pid,
                            "revisions": [
                                {"revid": 1, "timestamp": f"2024-01-{pid // 10:02d}T00:00:00Z"}
                            ],
                        }
                    ]
                }
            },
        )

    client, session = make_client(handler)
    assert backfill.pick_anchors(range(10, 101), 4) == [10, 40, 70, 100]
    assert backfill.pick_anchors([5, 6], 4) == [5, 6]
    anchors = backfill.creation_anchors(client, store, [10, 20, 30], 3, say=lambda m: None)
    assert [a["first_revision"] for a in anchors] == [
        "2024-01-01T00:00:00Z",
        "2024-01-02T00:00:00Z",
        None,
    ]
    backfill.creation_anchors(client, store, [10, 20, 30], 3, say=lambda m: None)
    assert len(session.calls) == 3


def test_creation_model_interpolates_and_clamps():
    anchors = [
        {"page_id": 100, "first_revision": "2024-01-01T00:00:00Z"},
        {"page_id": 200, "first_revision": "2024-01-11T00:00:00Z"},
        {"page_id": 150, "first_revision": "2023-12-01T00:00:00Z"},  # older: made monotone
        {"page_id": 300, "first_revision": None},
    ]
    model = CreationModel(anchors)
    est, inside = model.estimate(175)
    assert inside and est == datetime(2024, 1, 6, tzinfo=timezone.utc)
    assert model.estimate(50) == (datetime(2024, 1, 1, tzinfo=timezone.utc), False)
    assert model.estimate(999)[1] is False
    assert model.estimate(100)[1] is True
    with pytest.raises(ValueError, match="two anchors"):
        CreationModel(anchors[:1])


def test_months():
    assert backfill._months(date(2025, 1, 20), date(2025, 3, 5)) == [
        (date(2025, 1, 20), date(2025, 1, 31)),
        (date(2025, 2, 1), date(2025, 2, 28)),
        (date(2025, 3, 1), date(2025, 3, 5)),
    ]


def test_scan_moves_writes_month_files_and_load_moves(make_client, store):
    def handler(method, url, params, headers):
        if params.get("lecontinue"):
            return FakeResponse(
                200,
                {
                    "query": {
                        "logevents": [
                            {
                                "logid": 2,
                                "logpage": 7,
                                "title": "Old name",
                                "ns": 0,
                                "params": {"target_title": "New name", "target_ns": 0},
                                "timestamp": "2025-01-20T10:00:00Z",
                            }
                        ]
                    }
                },
            )
        if params["lenamespace"] == 0 and params["lestart"].startswith("2025-01"):
            return FakeResponse(
                200,
                {
                    "query": {
                        "logevents": [
                            {
                                "logid": 1,
                                "logpage": 8,
                                "title": "Draft-free",
                                "ns": 0,
                                "params": {"target_title": "Elsewhere", "target_ns": 0},
                                "timestamp": "2025-01-05T10:00:00Z",
                            }
                        ]
                    },
                    "continue": {"lecontinue": "x"},
                },
            )
        return FakeResponse(200, {"query": {"logevents": []}})

    client, session = make_client(handler)
    out = backfill.scan_moves(
        client, store, date(2025, 1, 1), date(2025, 2, 10), namespaces=(0,), say=lambda m: None
    )
    assert out == {"windows": 2, "entries": 2, "requests": 3}
    assert (store.raw / "movelog" / "ns0" / "2025-01.jsonl").exists()
    assert (store.raw / "movelog" / "ns0" / "2025-02-01_2025-02-10.jsonl").exists()
    backfill.scan_moves(
        client, store, date(2025, 1, 1), date(2025, 2, 10), namespaces=(0,), say=lambda m: None
    )
    assert len(session.calls) == 3
    moves = backfill.load_moves(store, {7})
    assert list(moves) == [7] and moves[7][0]["from_title"] == "Old name"


def test_title_spans():
    moves = [
        {
            "from_title": "Draft:Thing",
            "from_ns": 118,
            "to_title": "Thing (2025)",
            "to_ns": 0,
            "timestamp": "2025-01-05T09:00:00Z",
        },
        {
            "from_title": "Thing (2025)",
            "from_ns": 0,
            "to_title": "Thing",
            "to_ns": 0,
            "timestamp": "2025-01-20T09:00:00Z",
        },
        {
            "from_title": "Thing",
            "from_ns": 0,
            "to_title": "Old",
            "to_ns": 0,
            "timestamp": "2024-01-01T00:00:00Z",
        },
    ]
    spans = backfill.title_spans(
        "Thing", sorted(moves, key=lambda m: m["timestamp"]), date(2025, 1, 1), date(2025, 2, 1)
    )
    assert spans == [
        ("Thing (2025)", date(2025, 1, 5), date(2025, 1, 20)),
        ("Thing", date(2025, 1, 20), date(2025, 2, 1)),
    ]
    assert backfill.title_spans("X", [], date(2025, 1, 1), date(2025, 1, 2)) == [
        ("X", date(2025, 1, 1), date(2025, 1, 2))
    ]


def test_dp_known_gaps():
    gaps = backfill.dp_known_gaps(date(2023, 6, 19))
    assert gaps == {
        "us_not_published": True,
        "rebuilt_with_older_method": True,
        "medium_and_higher_risk_included": False,
        "strict_bot_filter": True,
    }
    assert backfill.dp_known_gaps(date(2024, 3, 1))["medium_and_higher_risk_included"] is True


def test_dp_download_marks_empty_files_missing(make_client, store):
    def handler(method, url, params, headers):
        empty = url.endswith("2025-01-02.tsv")
        if method == "HEAD":
            return FakeResponse(200, headers={"Content-Length": "0" if empty else "6"})
        if url.endswith("2025-01-03.tsv"):
            return FakeResponse(404, {})
        return FakeResponse(200, content=b"x\ty\n\n\n")

    client, _ = make_client(handler)
    out = backfill.dp_download(
        client, store, date(2025, 1, 1), date(2025, 1, 3), say=lambda m: None
    )
    assert out["downloaded"] == 1 and out["empty"] == 1
    cov = {r["day"]: r for r in backfill.read_jsonl(store.coverage)}
    assert cov["2025-01-02"]["status"] == "missing"
    assert cov["2025-01-03"]["reason"] == "HTTP 404"
    again = backfill.dp_download(
        client, store, date(2025, 1, 1), date(2025, 1, 1), say=lambda m: None
    )
    assert again["on_disk"] == 1


def test_dp_filter_and_totals(store):
    folder = store.raw / "country_project_page"
    folder.mkdir(parents=True)
    (folder / "2025-01-01.tsv").write_text(
        "Fakeland\tFL\ten.wikipedia\t7\tFakeland\tQ1\t120\n"
        "Fakeland\tFL\tde.wikipedia\t8\tFakeland\tQ1\t95\n"
        "Fakeland\tFL\tcommons.wikimedia\t9\tFile\tQ1\t500\n"
        "Otherland\tOL\ten.wikipedia\t3\tOther\tQ2\t460\n"
        "United States\tUS\ten.wikipedia\t4\tElse\tQ3\t470\n"
    )
    out = backfill.dp_filter(
        store, {"Q1", "Q2"}, date(2025, 1, 1), date(2025, 1, 2), say=lambda m: None
    )
    assert out == {"days": 1, "rows": 3, "skipped": 1}
    table = pq.read_table(store.dp_rows(date(2025, 1, 1)))
    assert table.column("project").to_pylist() == ["en.wikipedia", "de.wikipedia", "en.wikipedia"]
    stats = backfill.read_jsonl(store.root / "dp" / "filter_stats.jsonl")[0]
    assert stats["rows_in_file"] == 5 and stats["kept"] == 3
    assert stats["us_rows"] is True and stats["us_min_count"] == 470
    assert stats["countries_min_450_or_more"] == ["OL", "US"]
    assert stats["countries_min_below_450"] == 1
    totals = backfill.dp_totals(store)
    assert totals[("Q1", "de.wikipedia")] == (95, 8)
    assert (
        backfill.dp_filter(store, {"Q1"}, date(2025, 1, 1), date(2025, 1, 1), say=lambda m: None)[
            "skipped"
        ]
        == 1
    )


def test_plan_languages_fill_titles_and_old_titles(make_client):
    totals = {
        ("Q1", "de.wikipedia"): (900, 11),
        ("Q1", "fr.wikipedia"): (100, 12),
        ("Q2", "fr.wikipedia"): (500, 21),
        ("Q1", "en.wikipedia"): (5000, 1),
        ("Q9", "de.wikipedia"): (1, 1),
    }
    plan = backfill.plan_languages({"Q1": ("Fakeland", 1), "Q2": ("Otherland", 2)}, totals, 1)
    assert [(p["qid"], p["project"], p["rank"]) for p in plan] == [
        ("Q1", "en.wikipedia", 0),
        ("Q2", "en.wikipedia", 0),
        ("Q1", "de.wikipedia", 1),
        ("Q2", "fr.wikipedia", 1),
    ]

    def handler(method, url, params, headers):
        if "de.wikipedia" in url:
            return FakeResponse(
                200,
                {
                    "query": {
                        "pages": [
                            {
                                "pageid": 11,
                                "title": "Fakeland (Staat)",
                                "pageprops": {"wikibase_item": "Q1"},
                            }
                        ]
                    }
                },
            )
        return FakeResponse(
            200,
            {
                "query": {
                    "pages": [
                        {"pageid": 21, "title": "Autre", "pageprops": {"wikibase_item": "Q77"}}
                    ]
                }
            },
        )

    client, _ = make_client(handler)
    filled, stats = backfill.fill_titles(client, plan, say=lambda m: None)
    assert [p["title"] for p in filled] == ["Fakeland", "Otherland", "Fakeland (Staat)"]
    assert stats == {"languages": 2, "dropped_missing": 0, "dropped_qid": 1}
    moves = {
        1: [
            {
                "from_title": "Fakeland (country)",
                "from_ns": 0,
                "to_title": "Fakeland",
                "to_ns": 0,
                "timestamp": "2025-01-10T00:00:00Z",
            }
        ]
    }
    full = backfill.add_old_titles(filled, moves, date(2025, 1, 1), date(2025, 2, 1))
    assert full[-1] == {
        **filled[0],
        "title": "Fakeland (country)",
        "kind": "old_title",
        "span_start": "2025-01-01",
        "span_end": "2025-01-10",
    }


def test_api_backfill_chunks_and_resumes(make_client, store):
    plan = [
        {
            "qid": f"Q{i}",
            "project": "en.wikipedia",
            "title": f"T{i}",
            "page_id": i,
            "rank": 0,
            "kind": "current",
        }
        for i in range(5)
    ]
    plan[4] = {**plan[4], "kind": "old_title", "span_start": "2025-01-01", "span_end": "2025-01-02"}

    def handler(method, url, params, headers):
        if "/T1/" in url:
            return FakeResponse(404, {})
        if "/T2/" in url:
            return FakeResponse(400, {})
        return FakeResponse(
            200,
            {
                "items": [
                    {"timestamp": "2025010100", "views": 5},
                    {"timestamp": "2025010200", "views": 7},
                ]
            },
        )

    from newsattention.client import Budget

    client, _ = make_client(handler, budget=Budget(caps={"analytics": 3}))
    out = backfill.api_backfill(
        client, store, plan, date(2025, 1, 1), date(2025, 1, 31), chunk=2, say=lambda m: None
    )
    assert out == {"calls": 3, "ok": 1, "no_views": 1, "errors": 1}
    progress = json.loads((store.root / "api" / "progress.json").read_text())
    assert progress["next"] == 3
    client2, _ = make_client(handler)
    out2 = backfill.api_backfill(
        client2, store, plan, date(2025, 1, 1), date(2025, 1, 31), chunk=2, say=lambda m: None
    )
    assert out2["calls"] == 2
    files = sorted(p.name for p in (store.raw / "api").iterdir())
    assert files == ["chunk-0000000.parquet", "chunk-0000002.parquet", "chunk-0000003.parquet"]
    table = pq.read_table(store.raw / "api" / "chunk-0000003.parquet")
    assert set(table.column("kind").to_pylist()) == {"current", "old_title"}
    status = backfill.read_jsonl(store.root / "api" / "status.jsonl")
    assert [s["status"] for s in status] == ["ok", "no views", "error 400", "ok", "ok"]
    # Each answered call records the days it asked for (its span, or the run's span).
    assert (status[0]["first"], status[0]["last"]) == ("2025-01-01", "2025-01-31")
    assert (status[4]["first"], status[4]["last"]) == ("2025-01-01", "2025-01-02")


def test_move_windows_skip_covered_days(tmp_path):
    folder = tmp_path / "ns0"
    folder.mkdir()
    (folder / "2025-01.jsonl").write_text("")
    (folder / "2025-02-01_2025-02-10.jsonl").write_text("")
    windows = backfill._move_windows(folder, date(2025, 1, 1), date(2025, 3, 31))
    assert windows == [
        (date(2025, 2, 11), date(2025, 2, 28), "2025-02-11_2025-02-28"),
        (date(2025, 3, 1), date(2025, 3, 31), "2025-03"),
    ]
    assert backfill._move_windows(folder, date(2025, 1, 5), date(2025, 1, 20)) == []


def _api_store(make_client, store, fail_title: str | None = None):
    """Five planned calls in chunks of two; T1 has no views, ``fail_title`` answers 400."""
    plan = [
        {"qid": f"Q{i}", "project": "en.wikipedia", "title": f"T{i}", "page_id": i, "rank": 0}
        | {"kind": "current"}
        for i in range(5)
    ]
    plan[4] = {**plan[4], "kind": "old_title", "span_start": "2025-01-01", "span_end": "2025-01-02"}

    def handler(method, url, params, headers):
        if "/T1/" in url:
            return FakeResponse(404, {})
        if fail_title and f"/{fail_title}/" in url:
            return FakeResponse(400, {})
        days = ["2025010100", "2025010200"] if "/T4/" in url else ["2025010100", "2025012000"]
        return FakeResponse(200, {"items": [{"timestamp": t, "views": 3} for t in days]})

    client, _ = make_client(handler)
    backfill.api_backfill(
        client, store, plan, date(2025, 1, 1), date(2025, 1, 31), chunk=2, say=lambda m: None
    )
    return plan


def _check(store, plan):
    return backfill.check_api(store, plan, date(2025, 1, 1), date(2025, 1, 31))


def test_check_api_passes_a_whole_run(make_client, store):
    plan = _api_store(make_client, store)
    out = _check(store, plan)
    assert out["problems"] == [] and out["refetch"] == []
    assert out["by_status"] == {"no views": 1, "ok": 4}
    assert out["chunk_files"] == 3 and out["indices_covered_by_files"] == 5
    assert out["rows_read"] == 8


def _aside(store, name):
    path = store.raw / "api" / name
    path.rename(store.raw / name)


def test_check_api_finds_a_missing_middle_chunk(make_client, store):
    plan = _api_store(make_client, store)
    _aside(store, "chunk-0000002.parquet")
    out = _check(store, plan)
    assert out["refetch"] == [2, 3]
    assert out["problems"][0]["problem"] == "rows do not match"


def test_check_api_finds_a_missing_first_chunk(make_client, store):
    plan = _api_store(make_client, store)
    _aside(store, "chunk-0000000.parquet")
    out = _check(store, plan)
    assert out["refetch"] == [0, 1]
    assert out["problems"][0]["problem"] == "no chunk file"


def test_check_api_finds_a_damaged_chunk(make_client, store):
    plan = _api_store(make_client, store)
    path = store.raw / "api" / "chunk-0000002.parquet"
    data = path.read_bytes()
    _aside(store, path.name)
    path.write_bytes(data[: len(data) // 2])
    out = _check(store, plan)
    assert out["refetch"] == [2, 3]
    assert out["problems"][0]["problem"] == "unreadable"


def test_check_api_finds_rows_of_another_title(make_client, store):
    plan = _api_store(make_client, store)
    plan[4] = {**plan[4], "title": "Renamed"}
    out = _check(store, plan)
    assert out["refetch"] == [4]


def test_check_api_finds_days_outside_the_span(make_client, store):
    plan = _api_store(make_client, store)
    plan[3] = {**plan[3], "span_start": "2025-01-01", "span_end": "2025-01-10"}
    assert _check(store, plan)["refetch"] == [3]


def test_check_api_finds_lost_and_doubled_status_lines(make_client, store):
    plan = _api_store(make_client, store)
    path = store.root / "api" / "status.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[0], *lines[1:3], lines[4]]) + "\n")
    out = _check(store, plan)
    kinds = [p["problem"] for p in out["problems"]]
    assert "no status line" in kinds and "status lines" in kinds
    assert out["refetch"] == [3]


def test_check_api_lists_failed_calls_and_stray_files(make_client, store):
    plan = _api_store(make_client, store, fail_title="T2")
    (store.raw / "api" / "chunk-9999999.parquet").write_bytes(b"")
    (store.raw / "api" / "chunk-x.parquet").write_bytes(b"")
    out = _check(store, plan)
    kinds = [p["problem"] for p in out["problems"]]
    assert kinds.count("unexpected file") == 2 and "call failed" in kinds
    assert out["refetch"] == [2]


def test_api_backfill_flushes_each_chunk_before_its_progress(make_client, store, monkeypatch):
    from newsattention import durable

    seen: list[str] = []
    real = durable.publish

    def publish(tmp, dest, **kwargs):
        real(tmp, dest, **kwargs)
        seen.append(dest.name)

    monkeypatch.setattr(durable, "publish", publish)
    _api_store(make_client, store)
    assert seen == [
        "chunk-0000000.parquet",
        "progress.json",
        "chunk-0000002.parquet",
        "progress.json",
        "chunk-0000004.parquet",
        "progress.json",
    ]


def test_resolve_links_asks_again_for_articles_that_had_no_item(make_client, store):
    day = date(2025, 3, 2)
    backfill.record_read(store, page(day, 1, PAGE_V1), "first", T0)
    old = {"page_id": 5, "qid": None, "redirected": False, "resolved_at": "2025-03-01T00:00:00Z"}
    backfill.append_jsonl(
        store.resolved,
        [
            {"linked_title": "Fakeland", "title": "Fakeland", **old},
            {"linked_title": "Made-up Cup", "title": "Made-up Cup", **old, "qid": "Q9"},
        ],
    )

    def handler(method, url, params, headers):
        assert params["titles"] == "Fakeland"  # only the article that had no item
        pages = [{"title": "Fakeland", "pageid": 5, "pageprops": {"wikibase_item": "Q5"}}]
        return FakeResponse(200, {"query": {"pages": pages}})

    client, _ = make_client(handler)
    out = backfill.resolve_links(client, store, say=lambda m: None, now=lambda: T0)
    assert out["rechecked"] == 1 and backfill.load_resolved(store)["Fakeland"].qid == "Q5"
    # Asked again only once a day has passed since the last answer.
    again = backfill.resolve_links(client, store, say=lambda m: None, now=lambda: T0)
    assert again["rechecked"] == 0


def test_api_backfill_stops_at_a_chunk_boundary_after_max_calls(make_client, store):
    plan = [
        {"qid": f"Q{i}", "project": "en.wikipedia", "title": f"T{i}", "page_id": i, "rank": 0}
        | {"kind": "current"}
        for i in range(7)
    ]
    ok = FakeResponse(200, {"items": [{"timestamp": "2025010100", "views": 5}]})
    client, _ = make_client(lambda m, u, p, h: ok)
    lines: list[str] = []
    out = backfill.api_backfill(
        client,
        store,
        plan,
        date(2025, 1, 1),
        date(2025, 1, 31),
        chunk=2,
        say=lines.append,
        max_calls=3,
    )
    assert out["calls"] == 4  # two chunks of two: the first boundary at or after 3
    assert json.loads((store.root / "api" / "progress.json").read_text())["next"] == 4
    assert "run again to go on" in lines[-1]
