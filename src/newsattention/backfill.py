"""Backfill steps over a store folder, each resumable.

The store (``data/interim/store`` by default) holds the working state; raw answers go to the raw
folder (``data/raw``, on the external drive) and are written once.

``store/``
- ``portal/days/YYYY-MM/YYYY-MM-DD.json``: the current parse of each day page (events, links,
  parse statistics). Replaced when a re-read finds a new revision.
- ``portal/revisions.jsonl``: every read of every day (append-only). Old revision ids stay here.
- ``links/resolved.jsonl``: linked title to canonical title, page id and Wikidata id
  (append-only cache).
- ``pages/anchors.jsonl``: first-revision times of sampled page ids, for creation dates.
- ``dp/coverage.jsonl``: one line per country-file day (read, empty, missing).
- ``dp/rows/YYYY-MM/YYYY-MM-DD.parquet``: country-file rows of linked items.
- ``api/``: the language-view plan, its progress file and per-call status.

``raw/``
- ``portal/<day>_<revision>.json``, ``country_project_page/<day>.tsv``,
  ``movelog/ns<N>/<window>.jsonl``, ``api/chunk-<first>.parquet``.
"""

from __future__ import annotations

import bisect
import calendar
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from newsattention import dpviews, durable, pageviews, portal, wikidata
from newsattention.client import CallCapReached, SourceBlocked, WikimediaClient

EN = "en.wikipedia"
ENWIKI_API = "https://en.wikipedia.org/w/api.php"
OTHER_LANGUAGES = 5
REREAD_AFTER = (7, 30)

#: The seven 2023 days that Wikimedia rebuilt with the historical method (README, update #2).
DP_REBUILT_DAYS = frozenset(
    date.fromisoformat(d)
    for d in (
        "2023-06-19",
        "2023-10-25",
        "2023-11-13",
        "2023-11-17",
        "2023-11-19",
        "2023-11-23",
        "2023-11-27",
    )
)
DP_US_MISSING = (date(2023, 2, 6), date(2023, 9, 19))
DP_HIGHER_RISK_FROM = date(2024, 2, 15)
DP_STRICT_BOT_FILTER_FROM = date(2023, 5, 25)

Say = Callable[[str], None]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=k) for k in range((end - start).days + 1)]


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            n += 1
        durable.flush_file(fh)
    return n


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    durable.publish(tmp, path, replace=True)


def write_once(path: Path, text: str) -> bool:
    """Write a raw file that must never change. False when it already exists."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    durable.publish(tmp, path, read_only=True)
    return True


class Store:
    def __init__(self, root: Path | str, raw: Path | str) -> None:
        self.root = Path(root)
        self.raw = Path(raw)

    def day_file(self, day: date) -> Path:
        return self.root / "portal" / "days" / f"{day:%Y-%m}" / f"{day.isoformat()}.json"

    @property
    def revisions(self) -> Path:
        return self.root / "portal" / "revisions.jsonl"

    @property
    def resolved(self) -> Path:
        return self.root / "links" / "resolved.jsonl"

    @property
    def anchors(self) -> Path:
        return self.root / "pages" / "anchors.jsonl"

    @property
    def coverage(self) -> Path:
        return self.root / "dp" / "coverage.jsonl"

    def dp_rows(self, day: date) -> Path:
        return self.root / "dp" / "rows" / f"{day:%Y-%m}" / f"{day.isoformat()}.parquet"

    def day_files(self) -> Iterator[Path]:
        yield from sorted((self.root / "portal" / "days").glob("*/*.json"))

    def load_day(self, day: date) -> dict[str, Any] | None:
        path = self.day_file(day)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def days(self) -> Iterator[dict[str, Any]]:
        for path in self.day_files():
            yield json.loads(path.read_text(encoding="utf-8"))


# 1. Portal ---------------------------------------------------------------------------------


def _event_fingerprints(day: dict[str, Any] | None) -> dict[str, str]:
    if not day:
        return {}
    return {
        e["event_id"]: hashlib.sha1(e["text"].encode("utf-8")).hexdigest()
        for e in day.get("events", [])
    }


def record_read(
    store: Store, page: portal.PortalPage, kind: str, read_at: datetime
) -> dict[str, Any]:
    """Store one read of a day page; reparse it only when the revision changed."""
    previous = store.load_day(page.day)
    entry: dict[str, Any] = {
        "day": page.day.isoformat(),
        "title": page.title,
        "revision_id": page.revision_id,
        "revision_time": page.revision_time,
        "read_at": iso(read_at),
        "kind": kind,
        "previous_revision_id": previous.get("revision_id") if previous else None,
    }
    if previous is not None and previous.get("revision_id") == page.revision_id:
        entry.update(changed=False, events=len(previous.get("events", [])))
        append_jsonl(store.revisions, [entry])
        return entry
    if not page.missing:
        raw = store.raw / "portal" / f"{page.day.isoformat()}_{page.revision_id}.json"
        write_once(raw, json.dumps(asdict(page), default=str, ensure_ascii=False))
    stats = portal.ParseStats()
    events, links = portal.build_events(page, read_at, stats)
    day = {
        "day": page.day.isoformat(),
        "title": page.title,
        "page_id": page.page_id,
        "revision_id": page.revision_id,
        "revision_time": page.revision_time,
        "read_at": iso(read_at),
        "kind": kind,
        "missing": page.missing,
        "events": [e.model_dump(mode="json") for e in events],
        "links": [asdict(link) for link in links],
        "stats": asdict(stats),
    }
    write_json(store.day_file(page.day), day)
    old, new = _event_fingerprints(previous), _event_fingerprints(day)
    entry.update(
        changed=previous is not None,
        events=len(events),
        added=len(new.keys() - old.keys()),
        removed=len(old.keys() - new.keys()),
        reworded=sum(1 for k in new.keys() & old.keys() if new[k] != old[k]),
    )
    append_jsonl(store.revisions, [entry])
    return entry


def portal_backfill(
    client: WikimediaClient,
    store: Store,
    start: date,
    end: date,
    now: Callable[[], datetime] = utc_now,
    say: Say = print,
) -> dict[str, int]:
    """Read every day page from ``start`` to ``end`` that the store does not hold yet."""
    todo = [d for d in days_between(start, end) if not store.day_file(d).exists()]
    out = {"days_wanted": len(todo), "read": 0, "missing": 0, "requests": 0}
    for i in range(0, len(todo), 50):
        chunk = todo[i : i + 50]
        pages = portal.fetch_pages(client, chunk)
        out["requests"] += 1
        read_at = now()
        for page in pages:
            record_read(store, page, "first", read_at)
            out["read"] += 1
            out["missing"] += page.missing
        say(f"portal: {out['read']} of {len(todo)} day pages read")
    return out


def due_rereads(store: Store, today: date) -> list[tuple[date, str]]:
    """Days whose 7-day or 30-day re-read is due on ``today``.

    A day D ends at the start of D+1, so its 7-day re-read is due from D+8 and its 30-day
    re-read from D+31. A read made on or after the due date counts, whatever its kind.
    """
    latest: dict[str, str] = {}
    for entry in read_jsonl(store.revisions):
        if entry["read_at"] > latest.get(entry["day"], ""):
            latest[entry["day"]] = entry["read_at"]
    due = []
    for day_str, read_at in sorted(latest.items()):
        day = date.fromisoformat(day_str)
        read_day = date.fromisoformat(read_at[:10])
        for after in sorted(REREAD_AFTER, reverse=True):
            due_on = day + timedelta(days=after + 1)
            if today >= due_on and read_day < due_on:
                due.append((day, f"reread{after}"))
                break
    return due


def reread(
    client: WikimediaClient,
    store: Store,
    today: date,
    now: Callable[[], datetime] = utc_now,
    say: Say = print,
) -> dict[str, int]:
    """Read again the days that are due; a changed revision replaces the day's events."""
    due = due_rereads(store, today)
    out = {"due": len(due), "changed": 0, "unchanged": 0, "added": 0, "removed": 0, "reworded": 0}
    kinds = dict(due)
    for i in range(0, len(due), 50):
        chunk = [d for d, _ in due[i : i + 50]]
        read_at = now()
        for page in portal.fetch_pages(client, chunk):
            entry = record_read(store, page, kinds[page.day], read_at)
            if entry["changed"]:
                out["changed"] += 1
                for key in ("added", "removed", "reworded"):
                    out[key] += entry.get(key, 0)
            else:
                out["unchanged"] += 1
    say(f"reread: {out['due']} due, {out['changed']} changed, {out['unchanged']} unchanged")
    return out


def reparse(store: Store, say: Say = print) -> dict[str, int]:
    """Parse every day again from its raw revision with the current parser (no requests)."""
    out = {"days": 0, "events": 0}
    for path in list(store.day_files()):
        day = json.loads(path.read_text(encoding="utf-8"))
        if day["missing"]:
            continue
        raw = store.raw / "portal" / f"{day['day']}_{day['revision_id']}.json"
        data = json.loads(raw.read_text(encoding="utf-8"))
        page = portal.PortalPage(
            title=data["title"],
            day=date.fromisoformat(data["day"]),
            page_id=data["page_id"],
            revision_id=data["revision_id"],
            revision_time=data["revision_time"],
            wikitext=data["wikitext"],
        )
        read_at = datetime.fromisoformat(day["read_at"].replace("Z", "+00:00"))
        stats = portal.ParseStats()
        events, links = portal.build_events(page, read_at, stats)
        day.update(
            events=[e.model_dump(mode="json") for e in events],
            links=[asdict(link) for link in links],
            stats=asdict(stats),
        )
        write_json(path, day)
        out["days"] += 1
        out["events"] += len(events)
    say(f"reparse: {out['days']} days, {out['events']} events")
    return out


def parse_report(store: Store) -> dict[str, dict[str, Any]]:
    """What the parser could not read, summed by month."""
    months: dict[str, dict[str, Any]] = {}
    for day in store.days():
        m = months.setdefault(
            day["day"][:7],
            {
                "days": 0,
                "missing_pages": 0,
                "layout": defaultdict(int),
                "events": 0,
                "story_headings": 0,
                "uncategorized_events": 0,
                "events_without_links": 0,
                "events_without_sources": 0,
                "empty_bullets": 0,
                "mapped_headings": 0,
                "other_headings": defaultdict(int),
                "unknown_templates": defaultdict(int),
                "stray_lines": defaultdict(int),
            },
        )
        m["days"] += 1
        if day["missing"]:
            m["missing_pages"] += 1
            continue
        stats = day["stats"]
        m["layout"][stats["layout"]] += 1
        for key in (
            "events",
            "story_headings",
            "uncategorized_events",
            "events_without_links",
            "events_without_sources",
            "empty_bullets",
            "mapped_headings",
        ):
            m[key] += stats.get(key, 0)
        for key in ("other_headings", "unknown_templates", "stray_lines"):
            for name, n in stats[key].items():
                m[key][name] += n
    return {
        k: {kk: dict(vv) if isinstance(vv, defaultdict) else vv for kk, vv in v.items()}
        for k, v in sorted(months.items())
    }


# 2. Links ----------------------------------------------------------------------------------


def collect_links(store: Store) -> list[dict[str, Any]]:
    out = []
    for day in store.days():
        for link in day.get("links", []):
            out.append({**link, "day": day["day"]})
    return out


def load_resolved(store: Store) -> dict[str, wikidata.Resolved]:
    out = {}
    for row in read_jsonl(store.resolved):
        row = {k: v for k, v in row.items() if k != "resolved_at"}
        out[row["linked_title"]] = wikidata.Resolved(**row)
    return out


def resolve_links(
    client: WikimediaClient, store: Store, say: Say = print, now: Callable[[], datetime] = utc_now
) -> dict[str, int]:
    """Resolve every linked title the cache does not hold yet (50 titles a request).

    A title that led to an article without a Wikidata item is asked about again once its
    answer is a day old: new articles often get their item a day or two after they appear,
    and language views are planned per item. The newer answer replaces the older one.
    """
    cache = load_resolved(store)
    titles = list(dict.fromkeys(link["title"] for link in collect_links(store)))
    todo = [t for t in titles if t not in cache]
    latest: dict[str, str] = {}
    for row in read_jsonl(store.resolved):
        latest[row["linked_title"]] = row.get("resolved_at", "")
    a_day_ago = iso(now() - timedelta(days=1))
    linked = set(titles)
    recheck = [
        t
        for t, r in cache.items()
        if t in linked and r.page_id and r.qid is None and latest.get(t, "") < a_day_ago
    ]
    todo += recheck
    done = 0
    for i in range(0, len(todo), 500):
        chunk = todo[i : i + 500]
        found = wikidata.resolve_titles(client, chunk, EN)
        stamp = iso(now())
        append_jsonl(store.resolved, ({**asdict(r), "resolved_at": stamp} for r in found.values()))
        done += len(found)
        say(f"links: {done} of {len(todo)} titles resolved")
    return {
        "titles": len(titles),
        "resolved_now": done,
        "rechecked": len(recheck),
        "cached": len(titles) - len(todo) + len(recheck),
    }


# 2b. Page creation and moves ----------------------------------------------------------------


def first_revision(client: WikimediaClient, page_id: int, api: str = ENWIKI_API) -> str | None:
    """The timestamp of a page's first surviving revision (one request per page)."""
    data = client.action_api(
        api,
        {
            "action": "query",
            "prop": "revisions",
            "pageids": str(page_id),
            "rvdir": "newer",
            "rvlimit": "1",
            "rvprop": "ids|timestamp",
        },
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        return None
    return pages[0]["revisions"][0]["timestamp"]


def pick_anchors(page_ids: Iterable[int], n: int) -> list[int]:
    """``n`` page ids spread evenly over the sorted ids (quantiles), smallest and largest kept."""
    ids = sorted(set(page_ids))
    if len(ids) <= n:
        return ids
    return sorted({ids[round(k * (len(ids) - 1) / (n - 1))] for k in range(n)})


def creation_anchors(
    client: WikimediaClient, store: Store, page_ids: Iterable[int], n: int, say: Say = print
) -> list[dict[str, Any]]:
    have = {a["page_id"]: a for a in read_jsonl(store.anchors)}
    wanted = [pid for pid in pick_anchors(page_ids, n) if pid not in have]
    for k, pid in enumerate(wanted, start=1):
        ts = first_revision(client, pid)
        row = {"page_id": pid, "first_revision": ts}
        append_jsonl(store.anchors, [row])
        have[pid] = row
        if k % 50 == 0:
            say(f"anchors: {k} of {len(wanted)}")
    return sorted(have.values(), key=lambda a: a["page_id"])


class CreationModel:
    """Creation time from the page id: ids are given out in order, so time grows with the id.

    The model interpolates linearly between anchors (page ids with a known first revision),
    after making their times non-decreasing. Ids below the first anchor or above the last get
    the nearest anchor's time and are marked as outside.
    """

    def __init__(self, anchors: Iterable[dict[str, Any]]) -> None:
        pts = sorted(
            (a["page_id"], datetime.fromisoformat(a["first_revision"].replace("Z", "+00:00")))
            for a in anchors
            if a.get("first_revision")
        )
        self.ids: list[int] = []
        self.times: list[float] = []
        best = float("-inf")
        for pid, ts in pts:
            best = max(best, ts.timestamp())
            self.ids.append(pid)
            self.times.append(best)
        if len(self.ids) < 2:
            raise ValueError("At least two anchors with a first revision are needed.")

    def estimate(self, page_id: int) -> tuple[datetime, bool]:
        """(estimated creation time, inside the anchors' range)."""
        if page_id <= self.ids[0]:
            return datetime.fromtimestamp(self.times[0], timezone.utc), page_id == self.ids[0]
        if page_id >= self.ids[-1]:
            return datetime.fromtimestamp(self.times[-1], timezone.utc), page_id == self.ids[-1]
        j = bisect.bisect_right(self.ids, page_id)
        x0, x1 = self.ids[j - 1], self.ids[j]
        t0, t1 = self.times[j - 1], self.times[j]
        t = t0 + (t1 - t0) * (page_id - x0) / (x1 - x0)
        return datetime.fromtimestamp(t, timezone.utc), True


def _months(start: date, end: date) -> list[tuple[date, date]]:
    out = []
    cur = start.replace(day=1)
    while cur <= end:
        last = cur.replace(day=calendar.monthrange(cur.year, cur.month)[1])
        out.append((max(cur, start), min(last, end)))
        cur = last + timedelta(days=1)
    return out


def _covered_days(folder: Path) -> set[date]:
    """Days already in a move-log folder: month files (``2023-01``) and ranges (``A_B``)."""
    out: set[date] = set()
    for path in folder.glob("*.jsonl"):
        name = path.stem
        if "_" in name:
            a, b = (date.fromisoformat(x) for x in name.split("_"))
            out.update(days_between(a, b))
        else:
            y, m = (int(x) for x in name.split("-"))
            out.update(days_between(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])))
    return out


def _move_windows(folder: Path, start: date, end: date) -> list[tuple[date, date, str]]:
    """Windows still to read: whole months as ``YYYY-MM``, the rest as ``A_B`` day ranges."""
    covered = _covered_days(folder)
    out = []
    for first, last in _months(start, end):
        todo = [d for d in days_between(first, last) if d not in covered]
        if not todo:
            continue
        month_end = calendar.monthrange(first.year, first.month)[1]
        whole = first.day == 1 and last.day == month_end and len(todo) == month_end
        if whole:
            out.append((first, last, f"{first:%Y-%m}"))
            continue
        run_start = prev = todo[0]
        for d in [*todo[1:], None]:  # type: ignore[list-item]
            if d is not None and (d - prev).days == 1:
                prev = d
                continue
            out.append((run_start, prev, f"{run_start.isoformat()}_{prev.isoformat()}"))
            if d is not None:
                run_start = prev = d
    return out


def scan_moves(
    client: WikimediaClient,
    store: Store,
    start: date,
    end: date,
    namespaces: tuple[int, ...] = (0, 118),
    say: Say = print,
) -> dict[str, int]:
    """Read the English move log (articles and drafts) into raw files, each written once.

    A finished month read in one go is one file (``ns0/2023-01.jsonl``); any other stretch of
    days is a range file (``ns0/2026-11-01_2026-11-12.jsonl``). Days already in a file are
    never read again, so a daily run reads only the new day.
    """
    out = {"windows": 0, "entries": 0, "requests": 0}
    for ns in namespaces:
        folder = store.raw / "movelog" / f"ns{ns}"
        for first, last, stem in _move_windows(folder, start, end):
            name = f"{stem}.jsonl"
            path = folder / name
            entries: list[dict[str, Any]] = []
            cont: dict[str, Any] = {}
            while True:
                data = client.action_api(
                    ENWIKI_API,
                    {
                        "action": "query",
                        "list": "logevents",
                        "letype": "move",
                        "lenamespace": ns,
                        "lestart": f"{first.isoformat()}T00:00:00Z",
                        "leend": f"{last.isoformat()}T23:59:59Z",
                        "ledir": "newer",
                        "lelimit": "max",
                        "leprop": "ids|title|type|timestamp|details",
                        **cont,
                    },
                )
                out["requests"] += 1
                for ev in data.get("query", {}).get("logevents", []):
                    params = ev.get("params", {})
                    entries.append(
                        {
                            "logid": ev.get("logid"),
                            "page_id": ev.get("logpage"),
                            "from_title": ev.get("title"),
                            "from_ns": ev.get("ns"),
                            "to_title": params.get("target_title"),
                            "to_ns": params.get("target_ns"),
                            "timestamp": ev.get("timestamp"),
                        }
                    )
                if "continue" not in data:
                    break
                cont = data["continue"]
            write_once(path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
            out["windows"] += 1
            out["entries"] += len(entries)
            say(f"moves: ns{ns} {name}: {len(entries)} entries")
    return out


def load_moves(store: Store, page_ids: set[int]) -> dict[int, list[dict[str, Any]]]:
    """Moves of the given pages, oldest first, from the raw move-log files."""
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[Any] = set()
    for path in sorted((store.raw / "movelog").glob("ns*/*.jsonl")):
        for entry in read_jsonl(path):
            if entry["page_id"] in page_ids and entry["logid"] not in seen:
                seen.add(entry["logid"])
                out[entry["page_id"]].append(entry)
    for moves in out.values():
        moves.sort(key=lambda e: e["timestamp"])
    return dict(out)


def title_spans(
    current_title: str, moves: list[dict[str, Any]], start: date, end: date
) -> list[tuple[str, date, date]]:
    """The title a page had on each day from ``start`` to ``end``, from its moves.

    Returns (title, first day, last day) spans. The day of a move belongs to both titles, so
    the joined series can add both sides of that day. Moves into a namespace other than the
    articles (0) end the article's history at that point; drafts moved into the articles start
    it.
    """
    spans: list[tuple[str, date, date]] = []
    cursor = start
    article_moves = [m for m in moves if m.get("to_ns") == 0 or m.get("from_ns") == 0]
    for move in article_moves:
        day = date.fromisoformat(move["timestamp"][:10])
        if day < start or day > end:
            continue
        if move.get("from_ns") == 0:
            spans.append((move["from_title"], cursor, day))
        cursor = day
    spans.append((current_title, cursor, end))
    return [s for s in spans if s[1] <= s[2]]


def fetch_classes(
    client: WikimediaClient,
    store: Store,
    qids: Iterable[str],
    depth: int = 3,
    say: Say = print,
    now: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    """Each item's "instance of" classes, then the classes' labels and superclasses.

    ``depth`` tiers of classes get a label and their "subclass of" values: the items' own
    classes, their superclasses and so on. Resumable: each batch of 50 is appended to
    ``wikidata/instance_of.jsonl`` or ``wikidata/classes.jsonl`` as it comes. When Wikidata
    stays lagged (``maxlag``) after the client's waits, the step stops and is run again later.
    """
    items_path = store.root / "wikidata" / "instance_of.jsonl"
    classes_path = store.root / "wikidata" / "classes.jsonl"
    out: dict[str, Any] = {"items_fetched": 0, "classes_fetched": 0, "stopped": None}
    have = {r["qid"] for r in read_jsonl(items_path)}
    todo = [q for q in sorted(set(qids)) if q not in have]
    out["items_wanted"] = len(todo)
    try:
        for i in range(0, len(todo), wikidata.BATCH):
            chunk = todo[i : i + wikidata.BATCH]
            got = wikidata.instance_of(client, chunk)
            at = iso(now())
            rows = [
                {"qid": q, "instance_of": got.get(q, []), "missing": q not in got, "at": at}
                for q in chunk
            ]
            append_jsonl(items_path, rows)
            out["items_fetched"] += len(chunk)
            if (i // wikidata.BATCH) % 40 == 39:
                say(f"classes: {out['items_fetched']:,} of {len(todo):,} items")
        known = {r["qid"]: r for r in read_jsonl(classes_path)}
        tier = {c for r in read_jsonl(items_path) for c in r["instance_of"]}
        for level in range(depth):
            wanted = sorted(c for c in tier if c not in known)
            for i in range(0, len(wanted), wikidata.BATCH):
                chunk = wanted[i : i + wikidata.BATCH]
                got_c = wikidata.class_info(client, chunk)
                at = iso(now())
                rows = [
                    {
                        "qid": c,
                        "label": got_c.get(c, (None, []))[0],
                        "subclass_of": got_c.get(c, (None, []))[1],
                        "level": level,
                        "at": at,
                    }
                    for c in chunk
                ]
                append_jsonl(classes_path, rows)
                known.update({r["qid"]: r for r in rows})
                out["classes_fetched"] += len(chunk)
            tier = {s for c in tier if c in known for s in known[c]["subclass_of"]}
    except (CallCapReached, SourceBlocked, RuntimeError) as exc:
        out["stopped"] = str(exc)
        say(f"classes: stopped ({exc}); run the command again later to go on")
    say(f"classes: {out['items_fetched']:,} items and {out['classes_fetched']:,} classes fetched")
    return out


def load_classes(store: Store) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """``(item -> its classes, class -> {label, subclass_of})`` from the store."""
    items = {
        r["qid"]: r["instance_of"]
        for r in read_jsonl(store.root / "wikidata" / "instance_of.jsonl")
    }
    classes = {r["qid"]: r for r in read_jsonl(store.root / "wikidata" / "classes.jsonl")}
    return items, classes


def redirect_periods(own: list[tuple[date, date]], end: date) -> list[tuple[date, date]]:
    """The days after a title stopped being the page's own title, up to ``end``.

    ``own`` are the spans in which the page had that title (the day of a move belongs to both
    titles). The title counts as a redirect from the day after each own span to the day before
    the next one, and after the last one up to ``end``.
    """
    out = []
    spans = sorted(own)
    for k, (_, last) in enumerate(spans):
        first_free = last + timedelta(days=1)
        stop = spans[k + 1][0] - timedelta(days=1) if k + 1 < len(spans) else end
        if first_free <= stop:
            out.append((first_free, stop))
    return out


def plan_redirects(
    client: WikimediaClient,
    store: Store,
    plan: list[dict[str, Any]],
    covered: dict[tuple[str, str], tuple[date, date]],
    say: Say = print,
    now: Callable[[], datetime] = utc_now,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Calls for the views that reach a moved page through its old titles after each move.

    Each old title is looked up on Wikipedia as it is now (``pages/old_title_targets.jsonl``,
    append-only). Only a title that now redirects to the same page gets calls, for the days
    after the page left it, up to the last day of the page's own series: a title that became
    another article or a disambiguation page, or that no longer exists, is left out, since
    its later views are not this page's.
    """
    cache_path = store.root / "pages" / "old_title_targets.jsonl"
    cache = {r["title"]: r for r in read_jsonl(cache_path)}
    own: dict[tuple[str, int], dict[str, list[tuple[date, date]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    current: dict[tuple[str, int], str] = {}
    meta: dict[tuple[str, int], dict[str, Any]] = {}
    for item in plan:
        if item["project"] != EN or item.get("page_id") is None:
            continue
        key = (item["qid"], item["page_id"])
        if item["kind"] == "old_title":
            span = (date.fromisoformat(item["span_start"]), date.fromisoformat(item["span_end"]))
            own[key][item["title"]].append(span)
            meta[key] = item
        elif item["kind"] == "current" and not item.get("span_start"):
            current[key] = item["title"]
    titles = sorted({t for spans in own.values() for t in spans} - set(cache))
    found = wikidata.resolve_titles(client, titles, EN) if titles else {}
    at = iso(now())
    rows = [
        {
            "title": t,
            "page_id": found[t].page_id if t in found else None,
            "redirected": found[t].redirected if t in found else False,
            "at": at,
        }
        for t in titles
    ]
    if rows:
        append_jsonl(cache_path, rows)
        cache.update({r["title"]: r for r in rows})
    stats = {"pages": len(own), "old_titles": 0, "redirect_here": 0, "elsewhere": 0, "gone": 0}
    have = {(e["qid"], e["title"], e["kind"], e.get("span_start")) for e in plan}
    entries: list[dict[str, Any]] = []
    for key, by_title in sorted(own.items()):
        qid, page_id = key
        span = covered.get((qid, EN))
        if span is None:
            continue
        for title, spans in sorted(by_title.items()):
            stats["old_titles"] += 1
            target = cache.get(title, {})
            if title == current.get(key):
                continue  # the page has this title again now
            if target.get("page_id") is None:
                stats["gone"] += 1
                continue
            if target["page_id"] != page_id or not target.get("redirected"):
                stats["elsewhere"] += 1
                continue
            stats["redirect_here"] += 1
            for first, last in redirect_periods(spans, span[1]):
                if (qid, title, "redirect", first.isoformat()) in have:
                    continue
                entries.append(
                    {
                        **{k: meta[key][k] for k in ("qid", "project", "page_id", "rank")},
                        "title": title,
                        "kind": "redirect",
                        "span_start": first.isoformat(),
                        "span_end": last.isoformat(),
                    }
                )
    stats["calls"] = len(entries)
    say(
        f"redirects: {stats['old_titles']:,} old titles of {stats['pages']:,} pages; "
        f"{stats['redirect_here']:,} redirect to their page now, {stats['elsewhere']:,} lead "
        f"elsewhere, {stats['gone']:,} are gone; {stats['calls']:,} calls planned"
    )
    return entries, stats


# 4. Country files --------------------------------------------------------------------------


def dp_download(
    client: WikimediaClient, store: Store, start: date, end: date, say: Say = print
) -> dict[str, int]:
    """Download every country file not on disk yet; mark empty files as missing."""
    seen = {row["day"] for row in read_jsonl(store.coverage) if row["status"] != "missing"}
    out = {"downloaded": 0, "on_disk": 0, "empty": 0}
    for day in days_between(start, end):
        if day.isoformat() in seen:
            out["on_disk"] += 1
            continue
        try:
            path, size = dpviews.fetch_day(client, day, store.raw)
        except (CallCapReached, SourceBlocked) as exc:
            say(f"dp: stopped at {day}: {exc}")
            break
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            append_jsonl(
                store.coverage,
                [{"day": day.isoformat(), "status": "missing", "reason": f"HTTP {code}"}],
            )
            continue
        if path is None:
            out["empty"] += 1
            append_jsonl(
                store.coverage,
                [
                    {
                        "day": day.isoformat(),
                        "status": "missing",
                        "reason": "empty file",
                        "bytes": size or 0,
                    }
                ],
            )
            continue
        append_jsonl(
            store.coverage,
            [{"day": day.isoformat(), "status": "on_disk", "bytes": path.stat().st_size}],
        )
        out["downloaded"] += 1
        if out["downloaded"] % 25 == 0:
            say(f"dp: {out['downloaded']} files downloaded (now at {day})")
    say(
        f"dp: {out['downloaded']} downloaded, {out['on_disk']} already on disk, "
        f"{out['empty']} empty"
    )
    return out


def dp_known_gaps(day: date) -> dict[str, bool]:
    """Wikimedia's documented gaps for one day, as data."""
    return {
        "us_not_published": DP_US_MISSING[0] <= day <= DP_US_MISSING[1],
        "rebuilt_with_older_method": day in DP_REBUILT_DAYS,
        "medium_and_higher_risk_included": day >= DP_HIGHER_RISK_FROM,
        "strict_bot_filter": day >= DP_STRICT_BOT_FILTER_FROM,
    }


DP_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("qid", pa.string()),
        ("project", pa.string()),
        ("page_id", pa.int64()),
        ("country", pa.string()),
        ("views", pa.int32()),
    ]
)


def dp_filter(
    store: Store, qids: set[str], start: date, end: date, say: Say = print, force: bool = False
) -> dict[str, int]:
    """Stream each country file once and keep the Wikipedia rows of the linked items."""
    out = {"days": 0, "rows": 0, "skipped": 0}
    stats_path = store.root / "dp" / "filter_stats.jsonl"
    for day in days_between(start, end):
        src = store.raw / dpviews.CURRENT / f"{day.isoformat()}.tsv"
        dest = store.dp_rows(day)
        if not src.exists() or (dest.exists() and not force):
            out["skipped"] += 1
            continue
        tally = {"read": 0, "skipped": 0}
        cols: dict[str, list[Any]] = {name: [] for name in DP_SCHEMA.names}
        country_min: dict[str, int] = {}
        for row in dpviews._iter_rows(src, None, None, tally):
            tally["read"] += 1
            if row.views < country_min.get(row.country, 1 << 30):
                country_min[row.country] = row.views
            if row.item_id not in qids or not row.project.endswith(".wikipedia"):
                continue
            cols["date"].append(day)
            cols["qid"].append(row.item_id)
            cols["project"].append(row.project)
            cols["page_id"].append(row.page_id)
            cols["country"].append(row.country)
            cols["views"].append(row.views)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        pq.write_table(pa.table(cols, schema=DP_SCHEMA), tmp, compression="zstd")
        durable.publish(tmp, dest, replace=True)
        append_jsonl(
            stats_path,
            [
                {
                    "day": day.isoformat(),
                    "rows_in_file": tally["read"],
                    "malformed": tally["skipped"],
                    "kept": len(cols["qid"]),
                    "countries": len(country_min),
                    "us_rows": "US" in country_min,
                    "us_min_count": country_min.get("US"),
                    # Rows released with the older method start at 450, not 90.
                    "countries_min_450_or_more": sorted(
                        c for c, v in country_min.items() if v >= 450
                    ),
                    "countries_min_below_450": sum(1 for v in country_min.values() if v < 450),
                    **dp_known_gaps(day),
                }
            ],
        )
        out["days"] += 1
        out["rows"] += len(cols["qid"])
        if out["days"] % 50 == 0:
            say(f"dp-filter: {out['days']} days, {out['rows']:,} rows kept (at {day})")
    return out


def dp_totals(store: Store) -> dict[tuple[str, str], tuple[int, int]]:
    """(qid, project) -> (summed published views, page id) over every filtered day."""
    import pyarrow.dataset as ds

    dataset = ds.dataset(str(store.root / "dp" / "rows"), format="parquet")
    table = dataset.to_table(columns=["qid", "project", "page_id", "views"])
    grouped = table.group_by(["qid", "project"]).aggregate([("views", "sum"), ("page_id", "max")])
    return {
        (q, p): (int(v), int(pid))
        for q, p, v, pid in zip(
            grouped["qid"].to_pylist(),
            grouped["project"].to_pylist(),
            grouped["views_sum"].to_pylist(),
            grouped["page_id_max"].to_pylist(),
            strict=True,
        )
    }


# 5. Language views -------------------------------------------------------------------------


def plan_languages(
    en_pages: dict[str, tuple[str, int]],
    totals: dict[tuple[str, str], tuple[int, int]],
    languages: int = OTHER_LANGUAGES,
) -> list[dict[str, Any]]:
    """English for every item, then up to ``languages`` others, ranked by country-file views.

    Other-language entries carry the page id from the country files; their titles are filled
    in by :func:`fill_titles`. The plan is ordered English first, then rank 1 for every item,
    rank 2 for every item, and so on, so a partial run keeps the most useful series.
    """
    by_qid: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    for (qid, project), (views, page_id) in totals.items():
        if project != EN and qid in en_pages:
            by_qid[qid].append((-views, project, page_id))
    plan: list[dict[str, Any]] = [
        {"qid": q, "project": EN, "title": t, "page_id": pid, "rank": 0, "kind": "current"}
        for q, (t, pid) in sorted(en_pages.items())
    ]
    ranked = {q: sorted(v)[:languages] for q, v in by_qid.items()}
    for rank in range(languages):
        for qid in sorted(ranked):
            if rank < len(ranked[qid]):
                _, project, page_id = ranked[qid][rank]
                plan.append(
                    {
                        "qid": qid,
                        "project": project,
                        "title": None,
                        "page_id": page_id,
                        "rank": rank + 1,
                        "kind": "current",
                    }
                )
    return plan


def fill_titles(
    client: WikimediaClient, plan: list[dict[str, Any]], say: Say = print
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Titles for other-language entries from each wiki's own API, checked against the qid."""
    wanted: dict[str, list[int]] = defaultdict(list)
    for item in plan:
        if item["title"] is None:
            wanted[item["project"]].append(item["page_id"])
    found: dict[str, dict[int, tuple[str, str | None]]] = {}
    for k, (project, ids) in enumerate(sorted(wanted.items(), key=lambda x: -len(x[1])), 1):
        found[project] = wikidata.titles_for_page_ids(client, project, ids)
        if k % 10 == 0:
            say(f"titles: {k} of {len(wanted)} languages")
    out, dropped, mismatched = [], 0, 0
    for item in plan:
        if item["title"] is None:
            hit = found.get(item["project"], {}).get(item["page_id"])
            if hit is None:
                dropped += 1
                continue
            if hit[1] != item["qid"]:
                mismatched += 1
                continue
            item = {**item, "title": hit[0]}
        out.append(item)
    return out, {"languages": len(wanted), "dropped_missing": dropped, "dropped_qid": mismatched}


def add_old_titles(
    plan: list[dict[str, Any]],
    moves: dict[int, list[dict[str, Any]]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """For English pages that moved inside the span, one entry per earlier title."""
    out = list(plan)
    for item in plan:
        if item["project"] != EN or item["page_id"] not in moves:
            continue
        spans = title_spans(item["title"], moves[item["page_id"]], start, end)
        for title, first, last in spans[:-1]:
            out.append(
                {
                    **item,
                    "title": title,
                    "kind": "old_title",
                    "span_start": first.isoformat(),
                    "span_end": last.isoformat(),
                }
            )
    return out


API_SCHEMA = pa.schema(
    [
        ("plan_index", pa.int32()),
        ("qid", pa.string()),
        ("project", pa.string()),
        ("title", pa.string()),
        ("kind", pa.string()),
        ("date", pa.date32()),
        ("views", pa.int64()),
    ]
)


def api_backfill(
    client: WikimediaClient,
    store: Store,
    plan: list[dict[str, Any]],
    start: date,
    end: date,
    chunk: int = 250,
    say: Say = print,
) -> dict[str, int]:
    """Fetch the plan in chunks; each finished chunk is one raw Parquet file.

    The progress file names the next plan index; a re-run starts there. Days the API leaves
    out are zeros and are not stored (the plan's span says which days are covered).
    """
    progress_path = store.root / "api" / "progress.json"
    status_path = store.root / "api" / "status.jsonl"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {"next": 0}
    out = {"calls": 0, "ok": 0, "no_views": 0, "errors": 0}
    i = progress["next"]
    while i < len(plan):
        rows: dict[str, list[Any]] = {name: [] for name in API_SCHEMA.names}
        statuses = []
        stop = None
        for j in range(i, min(i + chunk, len(plan))):
            item = plan[j]
            first = date.fromisoformat(item.get("span_start") or start.isoformat())
            last = date.fromisoformat(item.get("span_end") or end.isoformat())
            try:
                data = client.get_json(
                    pageviews.per_article_url(item["project"], item["title"], first, last)
                )
            except (CallCapReached, SourceBlocked) as exc:
                stop = exc
                break
            except (requests.HTTPError, ValueError) as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                statuses.append({"plan_index": j, "status": f"error {code or type(exc).__name__}"})
                out["errors"] += 1
                out["calls"] += 1
                continue
            out["calls"] += 1
            items = (data or {}).get("items", [])
            if not items:
                out["no_views"] += 1
            else:
                out["ok"] += 1
            statuses.append(
                {
                    "plan_index": j,
                    "status": "ok" if items else "no views",
                    "days": len(items),
                    "first": first.isoformat(),
                    "last": last.isoformat(),
                }
            )
            for it in items:
                ts = it["timestamp"]
                rows["plan_index"].append(j)
                rows["qid"].append(item["qid"])
                rows["project"].append(item["project"])
                rows["title"].append(item["title"])
                rows["kind"].append(item["kind"])
                rows["date"].append(date(int(ts[:4]), int(ts[4:6]), int(ts[6:8])))
                rows["views"].append(int(it["views"]))
        done_to = i + len(statuses)
        if statuses:
            dest = store.raw / "api" / f"chunk-{i:07d}.parquet"
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".part")
                pq.write_table(pa.table(rows, schema=API_SCHEMA), tmp, compression="zstd")
                # On the disk before the status and progress files say the calls are done.
                durable.publish(tmp, dest, read_only=True)
            append_jsonl(status_path, statuses)
            write_json(progress_path, {"next": done_to, "updated": iso(utc_now())})
        if stop is not None:
            say(f"api: stopped at plan index {done_to}: {stop}")
            break
        i = done_to
        say(f"api: {i:,} of {len(plan):,} calls done")
    return out


def full_span_end(store: Store) -> date | None:
    """The last day asked for by plan entries without a span of their own.

    Status lines record the days each call asked for; lines written before that (the 2026
    backfill) take this day from ``api/meta.json``.
    """
    path = store.root / "api" / "meta.json"
    if not path.exists():
        return None
    return date.fromisoformat(json.loads(path.read_text())["full_span_end"])


def write_full_span_end(store: Store, end: date) -> None:
    write_json(store.root / "api" / "meta.json", {"full_span_end": end.isoformat()})


def coverage(
    plan: list[dict[str, Any]],
    statuses: Iterable[dict[str, Any]],
    full_end: date | None,
    start: date,
) -> dict[tuple[str, str], tuple[date, date]]:
    """First and last day fetched for each item and language under its current title.

    A call counts once its status line says ``ok`` or ``no views``: an empty answer means no
    views on those days, not unknown days. Old-title and redirect calls add views to a series
    but do not extend its days. Days between the first and the last are all fetched: follow-up
    calls start no later than the day before the series' last day (see :mod:`daily`).
    """
    last_status: dict[int, dict[str, Any]] = {}
    for row in statuses:
        last_status[int(row["plan_index"])] = row
    out: dict[tuple[str, str], tuple[date, date]] = {}
    for j, row in last_status.items():
        if not str(row.get("status", "")).startswith(("ok", "no views")) or j >= len(plan):
            continue
        item = plan[j]
        if item.get("kind") != "current":
            continue
        if "first" in row:
            first, last = date.fromisoformat(row["first"]), date.fromisoformat(row["last"])
        else:
            last_s = item.get("span_end")
            if last_s is None and full_end is None:
                raise ValueError(
                    "store/api/meta.json is missing: it names the last day of the calls made "
                    "before status lines recorded their days (the --end of that api-backfill)."
                )
            first = date.fromisoformat(item.get("span_start") or start.isoformat())
            last = date.fromisoformat(last_s) if last_s else full_end  # type: ignore[assignment]
        key = (item["qid"], item["project"])
        if key in out:
            a, b = out[key]
            first, last = min(a, first), max(b, last)
        out[key] = (first, last)
    return out


def check_api(store: Store, plan: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    """Check, without a request, that every planned call has its saved result on disk.

    Each chunk file covers the plan from its first index up to the next file's first index.
    Every file is read in full, and each plan index must have one status line and, in its
    chunk, as many rows as that line says days, with the plan's qid, project, title and kind,
    dates inside its span and no day twice. ``refetch`` lists the indices to fetch again.
    """
    progress_path = store.root / "api" / "progress.json"
    done = json.loads(progress_path.read_text())["next"] if progress_path.exists() else 0
    statuses: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(store.root / "api" / "status.jsonl"):
        statuses[int(row["plan_index"])].append(row)
    folder = store.raw / "api"
    problems: list[dict[str, Any]] = []
    refetch: set[int] = set()
    chunks: list[tuple[int, Path]] = []
    for path in sorted(folder.glob("chunk-*.parquet")) if folder.exists() else []:
        try:
            first = int(path.stem.split("-", 1)[1])
        except ValueError:
            first = -1
        if 0 <= first < done:
            chunks.append((first, path))
        else:
            problems.append({"problem": "unexpected file", "where": path.name, "indices": 0})
    chunks.sort()
    firsts = [first for first, _ in chunks]

    def flag(kind: str, where: str, indices: Iterable[int], detail: str = "") -> None:
        idx = sorted(set(indices))
        refetch.update(idx)
        problems.append({"problem": kind, "where": where, "indices": len(idx), "detail": detail})

    by_status: dict[str, int] = defaultdict(int)
    for j in range(done):
        rows = statuses.get(j, [])
        if not rows:
            flag("no status line", "status.jsonl", [j])
        elif len(rows) > 1:
            problems.append({"problem": "status lines", "where": f"index {j}", "indices": 1})
        if rows:
            by_status[str(rows[-1]["status"])] += 1
            if not str(rows[-1]["status"]).startswith(("ok", "no views")):
                flag("call failed", "status.jsonl", [j], str(rows[-1]["status"]))
    if any(j >= done for j in statuses):
        problems.append({"problem": "status past progress", "where": "status.jsonl", "indices": 1})
    covered = 0
    if done and (not firsts or firsts[0] != 0):
        upto = firsts[0] if firsts else done
        flag("no chunk file", f"plan 0 to {upto - 1}", range(upto))
    rows_read = 0
    for k, (first, path) in enumerate(chunks):
        last = (firsts[k + 1] if k + 1 < len(firsts) else done) - 1
        span_idx = range(first, last + 1)
        covered += len(span_idx)
        try:
            table = pq.read_table(path)
            if table.schema.remove_metadata() != API_SCHEMA:
                raise ValueError(f"columns {table.schema.names}")
            groups = table.group_by(["plan_index", "qid", "project", "title", "kind"]).aggregate(
                [
                    ("date", "count"),
                    ("date", "count_distinct"),
                    ("date", "min"),
                    ("date", "max"),
                    ("views", "min"),
                    ("views", "count"),
                ]
            )
            got = {int(g["plan_index"]): g for g in groups.to_pylist()}
        except Exception as exc:  # any read failure means the file is damaged
            flag("unreadable", path.name, span_idx, f"{type(exc).__name__}: {exc}")
            continue
        rows_read += table.num_rows
        outside = [j for j in got if j not in span_idx]
        if outside:
            flag("rows outside chunk", path.name, span_idx, f"{len(outside)} indices")
            continue
        bad: list[int] = []
        if len(got) != groups.num_rows:  # one index with two identities
            bad.extend(span_idx)
        for j in span_idx:
            want = statuses[j][-1].get("days", 0) if statuses.get(j) else None
            g = got.get(j)
            n = g["date_count"] if g else 0
            if want is None or n != want:
                bad.append(j)
                continue
            if g is None:
                continue
            item = plan[j]
            first_day = date.fromisoformat(item.get("span_start") or start.isoformat())
            last_day = date.fromisoformat(item.get("span_end") or end.isoformat())
            if (
                (g["qid"], g["project"], g["title"], g["kind"])
                != (item["qid"], item["project"], item["title"], item["kind"])
                or g["date_count_distinct"] != n
                or g["views_count"] != n
                or g["views_min"] < 0
                or not first_day <= g["date_min"] <= g["date_max"] <= last_day
            ):
                bad.append(j)
        if sum(g["date_count"] for g in got.values()) != table.num_rows:  # null dates or keys
            bad.extend(span_idx)
        if bad:
            flag("rows do not match", path.name, bad)
    return {
        "plan": len(plan),
        "progress_next": done,
        "status_lines": sum(len(v) for v in statuses.values()),
        "by_status": dict(sorted(by_status.items())),
        "chunk_files": len(chunks),
        "indices_covered_by_files": covered,
        "rows_read": rows_read,
        "problems": problems,
        "refetch": sorted(refetch),
    }
