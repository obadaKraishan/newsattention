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

from newsattention import backfill, measures, roles
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
        ("role_confidence", pa.string()),
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
            pg["role_confidence"].append(None)
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
    """One row per English article that a current event links (not every title ever resolved)."""
    resolved = backfill.load_resolved(store)
    pages: dict[int, tuple[str | None, str]] = {}
    for link in backfill.collect_links(store):
        res = resolved.get(link["title"])
        if res is not None and res.page_id:
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
        ("page_id", pa.int64()),
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
                "page_id": table["page_id"],
            },
            schema=VIEWS_SCHEMA,
        )
        pq.write_table(part, folder / f"{month_dir.name}.parquet", compression="zstd")
        total += n
    say(f"views_dp: {total:,} rows")
    return {"views_dp": total}


class SeriesBank:
    """Daily views per (series, project) over the span, as arrays (missing days are zero).

    A series is an item's qid, or ``page:<id>`` for an English article with no Wikidata item
    (:func:`backfill.series_id`); the tables write the latter with an empty qid and its page id.

    English series of moved pages are joined across titles: each day takes the views of the
    title the page had that day, and the day of a move adds both titles.
    """

    def __init__(self, start: date, end: date) -> None:
        self.start = start
        self.end = end
        self.n = (end - start).days + 1
        self.series: dict[tuple[str, str], np.ndarray] = {}
        self.joined: set[tuple[str, str]] = set()
        #: First and last day fetched per series; a series without an entry counts as fetched
        #: over the whole span (the older behavior, kept for small tests).
        self.covered: dict[tuple[str, str], tuple[date, date]] = {}

    def last_of(self, key: tuple[str, str], last_day: date) -> date:
        """The last day of ``key`` that was fetched, and not later than ``last_day``."""
        span = self.covered.get(key)
        return min(last_day, span[1]) if span else last_day

    def index(self, day: date) -> int:
        return (day - self.start).days

    def load(
        self,
        chunks: Iterable[Path],
        plan: list[dict[str, Any]],
        covered: dict[tuple[str, str], tuple[date, date]] | None = None,
    ) -> None:
        """Read the raw chunks; ``covered`` (from :func:`backfill.coverage`) bounds each series."""
        self.covered = dict(covered or {})
        old: dict[tuple[str, str], list[tuple[int, int, np.ndarray]]] = defaultdict(list)
        # Views through a title that now redirects to the page, per (series, title); a later
        # call replaces the days it asked for, so overlapping calls never count a day twice.
        redirects: dict[tuple[tuple[str, str], str], np.ndarray] = {}
        for path in chunks:
            table = pq.read_table(path)
            if table.num_rows == 0:
                continue
            idx = table["plan_index"].to_numpy()
            days = np.array([(d - self.start).days for d in table["date"].to_pylist()])
            views = table["views"].to_numpy()
            for j in np.unique(idx):
                item = plan[int(j)]
                key = (backfill.series_id(item["qid"], item.get("page_id")), item["project"])
                sel = idx == j
                arr = np.zeros(self.n, dtype=np.int64)
                arr[days[sel]] = views[sel]
                if item["kind"] == "old_title":
                    first = self.index(date.fromisoformat(item["span_start"]))
                    last = self.index(date.fromisoformat(item["span_end"]))
                    old[key].append((first, last, arr))
                elif item["kind"] == "redirect":
                    first = self.index(date.fromisoformat(item["span_start"]))
                    last = self.index(date.fromisoformat(item["span_end"]))
                    red = redirects.setdefault(
                        (key, item["title"]), np.zeros(self.n, dtype=np.int64)
                    )
                    red[first : last + 1] = arr[first : last + 1]
                elif item.get("span_start") and key in self.series:
                    # A follow-up call: it updates only the days it asked for.
                    first = self.index(date.fromisoformat(item["span_start"]))
                    last = self.index(date.fromisoformat(item["span_end"]))
                    self.series[key][first : last + 1] = arr[first : last + 1]
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
        for (key, _title), red in sorted(redirects.items()):
            if key in self.series:
                self.series[key] = self.series[key] + red
                self.joined.add(key)

    def keep_pages(self, page_ids: set[int]) -> int:
        """Drop the page-id series of articles that now have an item (or are no longer linked).

        Their views are under the item's qid from then on; returns how many were dropped.
        """
        drop = [
            key
            for key in self.series
            if key[0].startswith(backfill.PAGE_SERIES)
            and backfill.split_series_id(key[0])[1] not in page_ids
        ]
        for key in drop:
            del self.series[key]
            self.joined.discard(key)
        return len(drop)

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
            qid, page_id = backfill.split_series_id(key[0])
            cols["date"].extend(bank.start + timedelta(days=int(lo + i)) for i in nz)
            cols["qid"].extend([qid] * len(nz))
            cols["project"].extend([key[1]] * len(nz))
            cols["country"].extend([""] * len(nz))
            cols["views"].extend(int(v) for v in arr[nz])
            cols["source"].extend(["api"] * len(nz))
            cols["noisy"].extend([False] * len(nz))
            cols["joined"].extend([key in bank.joined] * len(nz))
            cols["page_id"].extend([page_id] * len(nz))
        pq.write_table(
            pa.table(cols, schema=VIEWS_SCHEMA), folder / f"{month}.parquet", compression="zstd"
        )
        total += len(cols["date"])
    say(f"views_api: {total:,} rows over {len(keys):,} series")
    return {"views_api": total, "series": len(keys), "joined": len(bank.joined)}


SERIES_SCHEMA = pa.schema(
    [
        ("qid", pa.string()),
        ("page_id", pa.int64()),
        ("project", pa.string()),
        ("first_day", pa.date32()),
        ("last_day", pa.date32()),
        ("joined", pa.bool_()),
    ]
)


def write_series(bank: SeriesBank, out: Path, last_day: date) -> dict[str, int]:
    """One row per series: the days that were fetched, up to the table's last day."""
    cols: dict[str, list[Any]] = {n: [] for n in SERIES_SCHEMA.names}
    for key in sorted(bank.series):
        first, last = bank.covered.get(key, (bank.start, last_day))
        qid, page_id = backfill.split_series_id(key[0])
        cols["qid"].append(qid)
        cols["page_id"].append(page_id)
        cols["project"].append(key[1])
        cols["first_day"].append(first)
        cols["last_day"].append(min(last, last_day))
        cols["joined"].append(key in bank.joined)
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols, schema=SERIES_SCHEMA), out / "series.parquet", compression="zstd")
    return {"series_rows": len(cols["qid"])}


def event_links(out: Path) -> list[tuple[str, date, str]]:
    """(event_id, event date, series) for every event page that exists.

    The series is the page's qid, or ``page:<id>`` for an article with no Wikidata item.
    """
    table = ds.dataset(str(out / "event_pages"), format="parquet").to_table(
        columns=["event_id", "qid", "page_id"]
    )
    rows = []
    for eid, qid, pid in zip(
        table["event_id"].to_pylist(),
        table["qid"].to_pylist(),
        table["page_id"].to_pylist(),
        strict=True,
    ):
        if qid or pid:
            rows.append((eid, date.fromisoformat(eid[:10]), backfill.series_id(qid, pid)))
    return rows


def summary_from_array(
    arr: np.ndarray, start: date, event_day: date, last_day: date
) -> measures.Summary:
    """:func:`newsattention.measures.summarize` for a zero-filled array starting at ``start``."""
    e = (event_day - start).days
    last = (last_day - start).days
    base = float(np.median(arr[e - 28 : e])) if e >= 28 else None
    v0 = int(arr[e]) if 0 <= e <= last else None
    v1 = int(arr[e + 1]) if 0 <= e + 1 <= last else None

    def excess(k: int) -> float | None:
        if base is None or e + k > last:
            return None
        return float(np.sum(arr[e : e + k + 1] - base))

    window = arr[e : min(last, e + measures.HORIZON) + 1] if e <= last else arr[:0]
    peak_day = peak_views = half = None
    censored = False
    if len(window):
        best = int(np.argmax(window))
        peak_day, peak_views = best, int(window[best])
        if peak_views > 0:
            below = np.flatnonzero(window[best + 1 :] < peak_views / 2)
            if len(below):
                half = int(below[0]) + 1
            else:
                censored = True
    return measures.Summary(
        baseline=base,
        views_day0=v0,
        lift_day0=None if v0 is None else measures.lift(v0, base),
        lift_day1=None if v1 is None else measures.lift(v1, base),
        excess_7=excess(7),
        excess_28=excess(28),
        peak_day=peak_day,
        peak_views=peak_views,
        half_life_days=half,
        half_life_censored=censored,
        observed_days=len(window),
    )


ATTENTION_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("event_date", pa.date32()),
        ("qid", pa.string()),
        ("page_id", pa.int64()),
        ("project", pa.string()),
        ("country", pa.string()),
        ("date", pa.date32()),
        ("days_since_event", pa.int16()),
        ("views", pa.int64()),
        ("baseline", pa.float64()),
        ("lift", pa.float64()),
        ("source", pa.string()),
    ]
)

SUMMARY_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("event_date", pa.date32()),
        ("qid", pa.string()),
        ("page_id", pa.int64()),
        ("project", pa.string()),
        ("baseline", pa.float64()),
        ("views_day0", pa.int64()),
        ("lift_day0", pa.float64()),
        ("lift_day1", pa.float64()),
        ("excess_7", pa.float64()),
        ("excess_28", pa.float64()),
        ("peak_day", pa.int16()),
        ("peak_views", pa.int64()),
        ("half_life_days", pa.int16()),
        ("half_life_censored", pa.bool_()),
        ("observed_days", pa.int16()),
        ("joined", pa.bool_()),
        ("countries_day0", pa.int32()),
        ("languages_lift2", pa.int16()),
    ]
)

COUNTRY_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("event_date", pa.date32()),
        ("qid", pa.string()),
        ("project", pa.string()),
        ("country", pa.string()),
        ("country_status", pa.string()),
        ("baseline_published_days", pa.int16()),
        ("baseline_file_days", pa.int16()),
        ("baseline_median", pa.float64()),
        ("views_day0", pa.int64()),
        ("views_day1", pa.int64()),
        ("lift_day0", pa.float64()),
        ("older_method_days", pa.int16()),
    ]
)


def older_method(country: str, day: date) -> bool:
    """Wikimedia documents older-method rows here: US until 2023-09-19, and the rebuilt days."""
    if day in backfill.DP_REBUILT_DAYS:
        return True
    return country == "US" and backfill.DP_US_MISSING[0] <= day <= backfill.DP_US_MISSING[1]


def older_method_pairs(store: Store) -> set[tuple[date, str]]:
    """(day, country) pairs whose rows came from the older method, as the files show it.

    A pair counts when Wikimedia documents the older method there (:func:`older_method`)
    and that day's smallest count for the country is 450 or more (the older threshold). In
    the files, US rows inside the documented period start near 90 on some days.
    """
    out: set[tuple[date, str]] = set()
    for row in backfill.read_jsonl(store.root / "dp" / "filter_stats.jsonl"):
        day = date.fromisoformat(row["day"])
        for country in row.get("countries_min_450_or_more", []):
            if older_method(country, day):
                out.add((day, country))
    return out


def file_days(store: Store) -> frozenset[date]:
    """Days that have a country file on disk (from the download record; the last entry wins)."""
    status: dict[str, str] = {}
    for row in backfill.read_jsonl(store.coverage):
        status[row["day"]] = row["status"]
    return frozenset(date.fromisoformat(d) for d, s in status.items() if s == "on_disk")


def load_dp_window(store: Store, first: date, last: date, qids: set[str]) -> pa.Table | None:
    parts = []
    day = first
    while day <= last:
        path = store.dp_rows(day)
        if path.exists():
            parts.append(pq.read_table(path))
        day += timedelta(days=1)
    if not parts:
        return None
    table = pa.concat_tables(parts)
    import pyarrow.compute as pc

    table = table.filter(pc.is_in(table["qid"], value_set=pa.array(sorted(qids))))
    return table.sort_by(
        [
            ("qid", "ascending"),
            ("project", "ascending"),
            ("country", "ascending"),
            ("date", "ascending"),
        ]
    )


def build_attention(
    store: Store, out: Path, bank: SeriesBank, last_day: date, say: Say = print
) -> dict[str, int]:
    """attention, attention_summary and country_status, one file per event month."""
    links = sorted(set(event_links(out)), key=lambda x: (x[1], x[0], x[2]))
    projects: dict[str, list[str]] = defaultdict(list)
    for qid, project in sorted(bank.series):
        projects[qid].append(project)
    have_files = file_days(store)
    older = older_method_pairs(store)
    by_month: dict[str, list[tuple[str, date, str]]] = defaultdict(list)
    for link in links:
        by_month[link[1].strftime("%Y-%m")].append(link)
    totals = {"attention": 0, "attention_summary": 0, "country_status": 0}
    for month, month_links in sorted(by_month.items()):
        att: dict[str, list[Any]] = {n: [] for n in ATTENTION_SCHEMA.names}
        summ: dict[str, list[Any]] = {n: [] for n in SUMMARY_SCHEMA.names}
        ctry: dict[str, list[Any]] = {n: [] for n in COUNTRY_SCHEMA.names}
        first = min(d for _, d, _ in month_links) - timedelta(days=28)
        last = max(d for _, d, _ in month_links) + timedelta(days=1)
        dp = load_dp_window(store, first, last, {q for _, _, q in month_links})
        index: dict[str, tuple[int, int]] = {}
        if dp is not None and dp.num_rows:
            q = dp["qid"].to_numpy(zero_copy_only=False)
            starts = np.flatnonzero(np.r_[True, q[1:] != q[:-1]])
            ends = np.r_[starts[1:], len(q)]
            index = {q[a]: (int(a), int(b)) for a, b in zip(starts, ends, strict=True)}
            col_project = dp["project"].to_numpy(zero_copy_only=False)
            col_country = dp["country"].to_numpy(zero_copy_only=False)
            col_date = dp["date"].to_pylist()
            col_views = dp["views"].to_numpy()
        for eid, d, qid in month_links:
            # countries and their status
            countries_day0: set[str] = set()
            if qid in index:
                a, b = index[qid]
                groups: dict[tuple[str, str], dict[date, int]] = defaultdict(dict)
                lo, hi = d - timedelta(days=28), d + timedelta(days=1)
                for r in range(a, b):
                    day = col_date[r]
                    if lo <= day <= hi:
                        # Two pages of one item: keep the larger published count (the main
                        # page), never a sum and never an estimate.
                        g = groups[(col_project[r], col_country[r])]
                        g[day] = max(g.get(day, 0), int(col_views[r]))
                        if day == d:
                            countries_day0.add(col_country[r])
                for (project, country), published in sorted(groups.items()):
                    st = measures.country_status(published, d, have_files)
                    n_older = sum(1 for day in published if (day, country) in older)
                    for name, value in (
                        ("event_id", eid),
                        ("event_date", d),
                        ("qid", qid),
                        ("project", project),
                        ("country", country),
                        ("country_status", st.status),
                        ("baseline_published_days", st.baseline_published_days),
                        ("baseline_file_days", st.baseline_file_days),
                        ("baseline_median", st.baseline_median),
                        ("views_day0", st.views_day0),
                        ("views_day1", st.views_day1),
                        ("lift_day0", st.lift_day0),
                        ("older_method_days", n_older),
                    ):
                        ctry[name].append(value)
            # languages
            item, page_id = backfill.split_series_id(qid)
            sums = []
            for project in projects.get(qid, []):
                arr = bank.series[(qid, project)]
                sm = summary_from_array(arr, bank.start, d, bank.last_of((qid, project), last_day))
                sums.append((project, sm))
                e = (d - bank.start).days
                for k in range(sm.observed_days):
                    v = int(arr[e + k])
                    att["event_id"].append(eid)
                    att["event_date"].append(d)
                    att["qid"].append(item)
                    att["page_id"].append(page_id)
                    att["project"].append(project)
                    att["country"].append("")
                    att["date"].append(d + timedelta(days=k))
                    att["days_since_event"].append(k)
                    att["views"].append(v)
                    att["baseline"].append(sm.baseline)
                    att["lift"].append(measures.lift(v, sm.baseline))
                    att["source"].append("api")
            lifted = sum(1 for _, sm in sums if max(sm.lift_day0 or 0, sm.lift_day1 or 0) >= 2)
            for project, sm in sums:
                row = {
                    "event_id": eid,
                    "event_date": d,
                    "qid": item,
                    "page_id": page_id,
                    "project": project,
                    **{
                        k: getattr(sm, k)
                        for k in (
                            "baseline",
                            "views_day0",
                            "lift_day0",
                            "lift_day1",
                            "excess_7",
                            "excess_28",
                            "peak_day",
                            "peak_views",
                            "half_life_days",
                            "half_life_censored",
                            "observed_days",
                        )
                    },
                    "joined": (qid, project) in bank.joined,
                    "countries_day0": len(countries_day0),
                    "languages_lift2": lifted,
                }
                for name in SUMMARY_SCHEMA.names:
                    summ[name].append(row[name])
        for name, cols, schema in (
            ("attention", att, ATTENTION_SCHEMA),
            ("attention_summary", summ, SUMMARY_SCHEMA),
            ("country_status", ctry, COUNTRY_SCHEMA),
        ):
            folder = out / name
            folder.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                pa.table(cols, schema=schema), folder / f"{month}.parquet", compression="zstd"
            )
            totals[name] += len(cols["event_id"])
        say(f"attention: {month} done ({len(month_links)} event pages)")
    return totals


def json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def page_facts(store: Store, out: Path, use_classes: bool = True) -> dict[int, roles.PageFacts]:
    """Creation estimate, moves into the articles and Wikidata class kind of each linked page.

    With ``use_classes=False`` no page has a class kind, as if no class had been fetched: the
    rule's variant without classes, scored against the same hand answers.
    """
    pages = pq.read_table(out / "pages.parquet", columns=["page_id", "qid", "created_estimate"])
    item_classes, classes = backfill.load_classes(store) if use_classes else ({}, {})
    ids = set(pages["page_id"].to_pylist())
    into: dict[int, list[date]] = defaultdict(list)
    for pid, moves in backfill.load_moves(store, ids).items():
        for m in moves:
            if m.get("to_ns") == 0 and m.get("from_ns") != 0:
                into[pid].append(date.fromisoformat(m["timestamp"][:10]))
    facts = {}
    for pid, qid, created in zip(
        pages["page_id"].to_pylist(),
        pages["qid"].to_pylist(),
        pages["created_estimate"].to_pylist(),
        strict=True,
    ):
        kind = roles.class_kind(item_classes.get(qid, []), classes)[0] if qid else None
        facts[pid] = roles.PageFacts(created, tuple(into.get(pid, [])), kind)
    return facts


def compute_roles(
    store: Store, out: Path, use_classes: bool = True
) -> tuple[dict[Path, list[dict[str, Any]]], dict[str, list[tuple[str, str]]], dict[str, Any]]:
    """Roles for every event page, without writing: ``(rows by file, roles by event, events)``."""
    events = {
        r["event_id"]: r
        for r in ds.dataset(str(out / "events"), format="parquet")
        .to_table(columns=["event_id", "date", "category", "text"])
        .to_pylist()
    }
    summaries = {}
    dataset = ds.dataset(str(out / "attention_summary"), format="parquet")
    # Tables built before articles with no item had views have no page_id column.
    with_pages = "page_id" in dataset.schema.names
    summ = dataset.to_table(
        columns=[
            "event_id",
            "qid",
            *(["page_id"] if with_pages else []),
            "project",
            "baseline",
            "lift_day0",
            "lift_day1",
            "peak_day",
            "peak_views",
        ]
    )
    for r in summ.to_pylist():
        if r["project"] == EN:
            summaries[(r["event_id"], backfill.series_id(r["qid"], r.get("page_id")))] = r
    facts = page_facts(store, out, use_classes)
    all_roles: dict[str, list[tuple[str, str]]] = {}
    files: dict[Path, list[dict[str, Any]]] = {}
    for path in sorted((out / "event_pages").glob("*.parquet")):
        rows = pq.read_table(path).to_pylist()
        by_event: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(rows):
            by_event[r["event_id"]].append(i)
        for eid, idx in by_event.items():
            idx.sort(key=lambda i: rows[i]["link_order"])
            ev = events[eid]
            links = [rows[i] for i in idx]
            sigs = [
                roles.signals(
                    ev["date"],
                    ev["text"],
                    link,
                    facts.get(link["page_id"]) if link["page_id"] else None,
                    summaries.get((eid, backfill.series_id(link["qid"], link["page_id"])))
                    if link["qid"] or link["page_id"]
                    else None,
                )
                for link in links
            ]
            assigned = roles.assign(links, sigs)
            all_roles[eid] = assigned
            for i, (role, conf) in zip(idx, assigned, strict=True):
                rows[i]["role"] = role
                rows[i]["role_confidence"] = conf
        files[path] = rows
    return files, all_roles, events


def build_roles(store: Store, out: Path, say: Say = print) -> dict[str, Any]:
    """Give every event page its role and confidence (rewrites ``event_pages``)."""
    files, all_roles, events = compute_roles(store, out)
    for path, rows in files.items():
        tmp = path.with_name(path.name + ".part")
        table = pa.Table.from_pylist(rows, schema=EVENT_PAGES_SCHEMA)
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(path)
    stats = roles.summarize(events, all_roles)
    json_dump(out / "roles_summary.json", stats)
    say(f"roles: {stats['roles']}; events {stats['events_have']}")
    return {"roles": stats["roles"], "events_have": stats["events_have"]}
