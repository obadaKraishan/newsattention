"""Build the tables as Parquet, one file per month, from the store and the raw files.

``tables/``
- ``events/YYYY-MM.parquet``: one row per event (CC BY-SA 4.0 text).
- ``event_pages/YYYY-MM.parquet``: one row per event and linked article (by the event's month).
- ``pages.parquet``: one row per linked English article: creation estimate and moves.
- ``views_dp/YYYY-MM.parquet``: country rows of linked items, as published.
- ``views_api/YYYY-MM.parquet``: daily views per item and language; days without a row are 0
  within the span. Series of moved English pages are joined across their titles.
- ``attention/YYYY-MM.parquet``: per event, item, language and day (days 0 to 28).
- ``attention_summary/YYYY-MM.parquet``: per event, item and language: the measures.
- ``country_status/YYYY-MM.parquet``: per event, item, language and country.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from newsattention import backfill, measures
from newsattention.backfill import EN, Store

Say = Callable[[str], None]


def _write_by_month(rows: dict[str, list[Any]], schema: pa.Schema, folder: Path, key: str) -> int:
    """Write a column dict split by the month of ``key`` (a date column)."""
    if not rows[key]:
        return 0
    table = pa.table(rows, schema=schema)
    months = sorted({d.strftime("%Y-%m") for d in rows[key]})
    folder.mkdir(parents=True, exist_ok=True)
    keys = np.array([d.strftime("%Y-%m") for d in rows[key]])
    for month in months:
        idx = np.flatnonzero(keys == month)
        pq.write_table(table.take(pa.array(idx)), folder / f"{month}.parquet", compression="zstd")
    return len(rows[key])


EVENTS_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("date", pa.date32()),
        ("category", pa.string()),
        ("text", pa.string()),
        ("portal_page", pa.string()),
        ("revision_id", pa.int64()),
        ("source_domains", pa.list_(pa.string())),
        ("story_titles", pa.list_(pa.string())),
        ("depth", pa.int16()),
        ("retrieved_at", pa.timestamp("s", tz="UTC")),
    ]
)

EVENT_PAGES_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("qid", pa.string()),
        ("project", pa.string()),
        ("page_id", pa.int64()),
        ("page_title", pa.string()),
        ("link_order", pa.int16()),
        ("in_text", pa.bool_()),
        ("story_level", pa.int16()),
        ("role", pa.string()),
    ]
)


def build_events(store: Store, out: Path) -> dict[str, int]:
    from datetime import datetime

    ev: dict[str, list[Any]] = {n: [] for n in EVENTS_SCHEMA.names}
    pg: dict[str, list[Any]] = {n: [] for n in EVENT_PAGES_SCHEMA.names}
    pg_date: list[date] = []
    resolved = backfill.load_resolved(store)
    for day in store.days():
        for e in day["events"]:
            for name in EVENTS_SCHEMA.names:
                value = e[name]
                if name == "date":
                    value = date.fromisoformat(value)
                elif name == "retrieved_at":
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                ev[name].append(value)
        seen: set[tuple[str, str]] = set()
        order: dict[str, int] = defaultdict(int)
        for link in sorted(day["links"], key=lambda x: (x["event_id"], x["link_order"])):
            res = resolved.get(link["title"])
            if res is None:
                continue
            key = (link["event_id"], str(res.page_id) if res.page_id else res.title)
            if key in seen:
                continue
            seen.add(key)
            order[link["event_id"]] += 1
            pg["event_id"].append(link["event_id"])
            pg["qid"].append(res.qid)
            pg["project"].append(EN)
            pg["page_id"].append(res.page_id)
            pg["page_title"].append(res.title)
            pg["link_order"].append(order[link["event_id"]])
            pg["in_text"].append(link["in_text"])
            pg["story_level"].append(link.get("story_level"))
            pg["role"].append("unknown")
            pg_date.append(date.fromisoformat(day["day"]))
    n_events = _write_by_month(ev, EVENTS_SCHEMA, out / "events", "date")
    pg["_d"] = pg_date
    schema = EVENT_PAGES_SCHEMA.append(pa.field("_d", pa.date32()))
    table = pa.table(pg, schema=schema)
    keys = np.array([d.strftime("%Y-%m") for d in pg_date])
    (out / "event_pages").mkdir(parents=True, exist_ok=True)
    for month in sorted(set(keys)):
        part = table.take(pa.array(np.flatnonzero(keys == month))).drop_columns(["_d"])
        pq.write_table(part, out / "event_pages" / f"{month}.parquet", compression="zstd")
    return {"events": n_events, "event_pages": len(pg_date)}


PAGES_SCHEMA = pa.schema(
    [
        ("page_id", pa.int64()),
        ("qid", pa.string()),
        ("title", pa.string()),
        ("created_estimate", pa.date32()),
        ("created_estimate_inside_anchors", pa.bool_()),
        ("moves_in_span", pa.int16()),
        ("old_titles", pa.list_(pa.string())),
        ("move_dates", pa.list_(pa.date32())),
    ]
)


def build_pages(store: Store, out: Path, span_start: date, span_end: date) -> dict[str, int]:
    pages: dict[int, tuple[str | None, str]] = {}
    for res in backfill.load_resolved(store).values():
        if res.page_id:
            pages[res.page_id] = (res.qid, res.title)
    model = backfill.CreationModel(backfill.read_jsonl(store.anchors))
    moves = backfill.load_moves(store, set(pages))
    cols: dict[str, list[Any]] = {n: [] for n in PAGES_SCHEMA.names}
    for pid, (qid, title) in sorted(pages.items()):
        est, inside = model.estimate(pid)
        spans = backfill.title_spans(title, moves.get(pid, []), span_start, span_end)
        cols["page_id"].append(pid)
        cols["qid"].append(qid)
        cols["title"].append(title)
        cols["created_estimate"].append(est.date())
        cols["created_estimate_inside_anchors"].append(inside)
        cols["moves_in_span"].append(len(spans) - 1)
        cols["old_titles"].append([s[0] for s in spans[:-1]])
        cols["move_dates"].append([s[2] for s in spans[:-1]])
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols, schema=PAGES_SCHEMA), out / "pages.parquet", compression="zstd")
    return {"pages": len(pages), "moved": sum(1 for n in cols["moves_in_span"] if n)}


VIEWS_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("qid", pa.string()),
        ("project", pa.string()),
        ("country", pa.string()),
        ("views", pa.int64()),
        ("source", pa.string()),
        ("noisy", pa.bool_()),
        ("joined", pa.bool_()),
    ]
)


def build_views_dp(store: Store, out: Path, say: Say = print) -> dict[str, int]:
    """Country rows as published: one Parquet file per month."""
    folder = out / "views_dp"
    folder.mkdir(parents=True, exist_ok=True)
    total = 0
    for month_dir in sorted((store.root / "dp" / "rows").iterdir()):
        table = ds.dataset(str(month_dir), format="parquet").to_table()
        n = table.num_rows
        part = pa.table(
            {
                "date": table["date"],
                "qid": table["qid"],
                "project": table["project"],
                "country": table["country"],
                "views": table["views"].cast(pa.int64()),
                "source": pa.array(["dp"] * n),
                "noisy": pa.array([True] * n),
                "joined": pa.array([False] * n),
            },
            schema=VIEWS_SCHEMA,
        )
        pq.write_table(part, folder / f"{month_dir.name}.parquet", compression="zstd")
        total += n
    say(f"views_dp: {total:,} rows")
    return {"views_dp": total}


class SeriesBank:
    """Daily views per (qid, project) over the span, as arrays (missing days are zero).

    English series of moved pages are joined across titles: each day takes the views of the
    title the page had that day, and the day of a move adds both titles.
    """

    def __init__(self, start: date, end: date) -> None:
        self.start = start
        self.end = end
        self.n = (end - start).days + 1
        self.series: dict[tuple[str, str], np.ndarray] = {}
        self.joined: set[tuple[str, str]] = set()
        self.covered: dict[tuple[str, str], tuple[int, int]] = {}

    def index(self, day: date) -> int:
        return (day - self.start).days

    def load(self, chunks: Iterable[Path], plan: list[dict[str, Any]]) -> None:
        old: dict[tuple[str, str], list[tuple[int, int, np.ndarray]]] = defaultdict(list)
        for path in chunks:
            table = pq.read_table(path)
            if table.num_rows == 0:
                continue
            idx = table["plan_index"].to_numpy()
            days = np.array([(d - self.start).days for d in table["date"].to_pylist()])
            views = table["views"].to_numpy()
            for j in np.unique(idx):
                item = plan[int(j)]
                key = (item["qid"], item["project"])
                sel = idx == j
                arr = np.zeros(self.n, dtype=np.int64)
                arr[days[sel]] = views[sel]
                if item["kind"] == "old_title":
                    first = self.index(date.fromisoformat(item["span_start"]))
                    last = self.index(date.fromisoformat(item["span_end"]))
                    old[key].append((first, last, arr))
                else:
                    self.series[key] = arr
        for key, spans in old.items():
            if key not in self.series:
                continue
            cur = self.series[key]
            first_current = max(last for _, last, _ in spans)
            joined = np.zeros(self.n, dtype=np.int64)
            for first, last, arr in spans:
                joined[first : last + 1] += arr[first : last + 1]
            joined[first_current:] += cur[first_current:]
            self.series[key] = joined
            self.joined.add(key)

    def as_dict(self, key: tuple[str, str], last: date) -> dict[date, int]:
        arr = self.series[key]
        upto = self.index(last)
        return {self.start + timedelta(days=i): int(arr[i]) for i in range(upto + 1)}


def write_views_api(bank: SeriesBank, out: Path, say: Say = print) -> dict[str, int]:
    """Nonzero days of every series, one Parquet file per month."""
    folder = out / "views_api"
    folder.mkdir(parents=True, exist_ok=True)
    months: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for day_i in range(bank.n):
        d = bank.start + timedelta(days=day_i)
        months[d.strftime("%Y-%m")].append((day_i, day_i))
    keys = sorted(bank.series)
    total = 0
    for month, spans in sorted(months.items()):
        lo, hi = spans[0][0], spans[-1][0]
        cols: dict[str, list[Any]] = {n: [] for n in VIEWS_SCHEMA.names}
        for key in keys:
            arr = bank.series[key][lo : hi + 1]
            nz = np.flatnonzero(arr)
            if not len(nz):
                continue
            cols["date"].extend(bank.start + timedelta(days=int(lo + i)) for i in nz)
            cols["qid"].extend([key[0]] * len(nz))
            cols["project"].extend([key[1]] * len(nz))
            cols["country"].extend([""] * len(nz))
            cols["views"].extend(int(v) for v in arr[nz])
            cols["source"].extend(["api"] * len(nz))
            cols["noisy"].extend([False] * len(nz))
            cols["joined"].extend([key in bank.joined] * len(nz))
        pq.write_table(
            pa.table(cols, schema=VIEWS_SCHEMA), folder / f"{month}.parquet", compression="zstd"
        )
        total += len(cols["date"])
    say(f"views_api: {total:,} rows over {len(keys):,} series")
    return {"views_api": total, "series": len(keys), "joined": len(bank.joined)}


def event_links(out: Path) -> list[tuple[str, date, str]]:
    """(event_id, event date, qid) for every event page with a qid."""
    table = ds.dataset(str(out / "event_pages"), format="parquet").to_table(
        columns=["event_id", "qid"]
    )
    rows = []
    for eid, qid in zip(table["event_id"].to_pylist(), table["qid"].to_pylist(), strict=True):
        if qid:
            rows.append((eid, date.fromisoformat(eid[:10]), qid))
    return rows


def json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def _measures_unused() -> None:  # pragma: no cover - keeps the import for later stages
    _ = measures
