"""Build a linked sample: events, their pages, country views and language views.

Each step writes its table to the output folder and is skipped on a re-run when the table is
already there, so a re-run never spends requests twice. Raw portal revisions and the
differentially private daily files go to the raw folder, written once.

Steps:
1. ``portal``: the day pages, their events and links (one request per 50 days).
2. ``resolve``: linked titles to canonical titles, page ids and Wikidata ids (50 per request).
3. ``dp``: the daily country files, filtered to the linked items.
4. ``sitelinks``: the items' titles in other languages (50 per Wikidata request).
5. ``api``: daily views per article from the Analytics API, English first, then up to five
   other languages per item, ranked by the item's views in the country files.
6. ``attention``: baseline, lift and days since the event for every event page and day.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel

from newsattention import dpviews, measures, pageviews, portal, wikidata
from newsattention.client import CallCapReached, SourceBlocked, WikimediaClient
from newsattention.schema import Attention, Event, EventPage, Views

EN = "en.wikipedia"
OTHER_LANGUAGES = 5


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=k) for k in range((end - start).days + 1)]


def write_jsonl(path: Path, rows: Iterable[Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    tmp = path.with_name(path.name + ".part")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            data = row.model_dump(mode="json") if isinstance(row, BaseModel) else row
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")
            n += 1
    tmp.rename(path)
    return n


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_views_csv(path: Path, rows: Iterable[Views]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(Views.model_fields)
    n = 0
    tmp = path.with_name(path.name + ".part")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(fields)
        for row in rows:
            data = row.model_dump(mode="json")
            writer.writerow(
                [
                    "true" if v is True else "false" if v is False else v
                    for v in (data[f] for f in fields)
                ]
            )
            n += 1
    tmp.rename(path)
    return n


def read_views_csv(path: Path) -> list[Views]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [Views.model_validate(row) for row in csv.DictReader(fh)]


class Sample:
    """One sample run: an output folder, a raw folder and a client."""

    def __init__(
        self,
        client: WikimediaClient,
        out_dir: Path,
        raw_dir: Path,
        start: date,
        end: date,
        complete_until: date,
        say: Callable[[str], None] = print,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.client = client
        self.out = Path(out_dir)
        self.raw = Path(raw_dir)
        self.start = start
        self.end = end
        self.complete_until = complete_until
        self.say = say
        self.now = now

    # 1 ------------------------------------------------------------------------------------
    def portal(self) -> tuple[list[Event], list[dict[str, Any]]]:
        events_path, links_path = self.out / "events.jsonl", self.out / "links.jsonl"
        if events_path.exists() and links_path.exists():
            events = [Event.model_validate(r) for r in read_jsonl(events_path)]
            return events, read_jsonl(links_path)
        retrieved = self.now().replace(microsecond=0)
        pages = portal.fetch_pages(self.client, days_between(self.start, self.end))
        events: list[Event] = []
        links: list[dict[str, Any]] = []
        meta = []
        for page in pages:
            if not page.missing:
                raw = self.raw / "portal" / f"{page.day.isoformat()}_{page.revision_id}.json"
                if not raw.exists():
                    raw.parent.mkdir(parents=True, exist_ok=True)
                    raw.write_text(json.dumps(asdict(page), default=str, ensure_ascii=False))
                    raw.chmod(0o444)
            evs, lks = portal.build_events(page, retrieved)
            events.extend(evs)
            links.extend(asdict(link) for link in lks)
            meta.append(
                {
                    "title": page.title,
                    "day": page.day.isoformat(),
                    "page_id": page.page_id,
                    "revision_id": page.revision_id,
                    "revision_time": page.revision_time,
                    "events": len(evs),
                    "retrieved_at": retrieved.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
        write_jsonl(self.out / "portal_pages.jsonl", meta)
        write_jsonl(links_path, links)
        write_jsonl(events_path, events)
        self.say(f"portal: {len(pages)} day pages, {len(events)} events, {len(links)} links")
        return events, links

    # 2 ------------------------------------------------------------------------------------
    def resolve(self, links: list[dict[str, Any]]) -> list[EventPage]:
        path = self.out / "event_pages.jsonl"
        if path.exists():
            return [EventPage.model_validate(r) for r in read_jsonl(path)]
        resolved = wikidata.resolve_titles(self.client, (link["title"] for link in links), EN)
        write_jsonl(self.out / "resolved.jsonl", (asdict(r) for r in resolved.values()))
        pages = []
        for link in links:
            res = resolved[link["title"]]
            pages.append(
                EventPage(
                    event_id=link["event_id"],
                    qid=res.qid,
                    project=EN,
                    page_id=res.page_id,
                    page_title=res.title,
                    link_order=link["link_order"],
                    in_text=link["in_text"],
                )
            )
        write_jsonl(path, pages)
        self.say(f"resolve: {len(resolved)} titles, {len(pages)} event pages")
        return pages

    # 3 ------------------------------------------------------------------------------------
    def dp(self, qids: set[str], days: list[date]) -> list[Views]:
        path = self.out / "views_dp.csv"
        pages_path = self.out / "dp_pages.jsonl"
        if path.exists() and pages_path.exists():
            self.dp_pages = {(r["qid"], r["project"]): r["page_id"] for r in read_jsonl(pages_path)}
            return read_views_csv(path)
        rows: list[Views] = []
        status = []
        seen: dict[tuple[str, str], int] = {}
        for day in days:
            try:
                local, size = dpviews.fetch_day(self.client, day, self.raw)
            except (CallCapReached, SourceBlocked) as exc:
                self.say(f"dp: stopped at {day}: {exc}")
                status.append({"day": day.isoformat(), "status": "stopped", "detail": str(exc)})
                break
            if local is None:
                status.append({"day": day.isoformat(), "status": "empty", "bytes": size or 0})
                continue
            kept = 0
            for row in dpviews.iter_rows(local, item_ids=qids):
                if not row.project.endswith(".wikipedia"):
                    continue
                rows.append(
                    Views(
                        date=day,
                        qid=row.item_id,
                        project=row.project,
                        country=row.country,
                        views=row.views,
                        source="dp",
                        noisy=True,
                    )
                )
                seen.setdefault((row.item_id, row.project), row.page_id)
                kept += 1
            status.append({"day": day.isoformat(), "status": "read", "bytes": size, "kept": kept})
        write_jsonl(self.out / "dp_status.jsonl", status)
        write_jsonl(
            pages_path,
            ({"qid": q, "project": p, "page_id": pid} for (q, p), pid in sorted(seen.items())),
        )
        self.dp_pages = seen
        write_views_csv(path, rows)
        self.say(f"dp: {sum(1 for s in status if s['status'] == 'read')} files, {len(rows)} rows")
        return rows

    # 4 ------------------------------------------------------------------------------------
    @staticmethod
    def plan_api(
        en_titles: dict[str, str],
        dp_rows: Iterable[Views],
        budget: int,
        languages: int = OTHER_LANGUAGES,
        other_order: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """English for every item first, then up to ``languages`` other languages per item.

        Other languages are ranked per item by its views in the country files (all countries
        and days summed); a language is in the country files only when it has the article.
        With ``other_order``, items get all their languages one item at a time in that order,
        so a cut at ``budget`` leaves complete language sets for the first items; without it,
        languages go round by rank. Other-language entries have no title yet (see
        :meth:`titles`).
        """
        totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in dp_rows:
            if row.project != EN:
                totals[row.qid][row.project] += row.views
        plan: list[dict[str, Any]] = [
            {"qid": q, "project": EN, "title": t, "rank": 0} for q, t in en_titles.items()
        ]
        ranked: dict[str, list[str]] = {}
        for qid in en_titles:
            have = totals.get(qid, {})
            ranked[qid] = sorted(have, key=lambda p, h=have: (-h[p], p))[:languages]  # type: ignore[misc]

        def entry(qid: str, rank: int) -> dict[str, Any]:
            return {"qid": qid, "project": ranked[qid][rank], "title": None, "rank": rank + 1}

        if other_order is not None:
            for qid in dict.fromkeys(other_order):
                plan.extend(entry(qid, rank) for rank in range(len(ranked.get(qid, []))))
        else:
            for rank in range(languages):
                plan.extend(entry(qid, rank) for qid in ranked if rank < len(ranked[qid]))
        return plan[:budget]

    def titles(self, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fill in other-language titles from the page ids in the country files.

        Each language's own API gives the current title and Wikidata id of the page id; an
        entry is dropped when the page is gone or its Wikidata id is not the item's.
        """
        path = self.out / "api_plan.jsonl"
        if path.exists():
            return read_jsonl(path)
        wanted: dict[str, list[int]] = defaultdict(list)
        for item in plan:
            if item["title"] is None:
                wanted[item["project"]].append(self.dp_pages[(item["qid"], item["project"])])
        found: dict[str, dict[int, tuple[str, str | None]]] = {}
        for project, ids in sorted(wanted.items()):
            found[project] = wikidata.titles_for_page_ids(self.client, project, ids)
        out, dropped = [], 0
        for item in plan:
            if item["title"] is None:
                pid = self.dp_pages[(item["qid"], item["project"])]
                hit = found[item["project"]].get(pid)
                if hit is None or hit[1] != item["qid"]:
                    dropped += 1
                    continue
                item = {**item, "title": hit[0], "page_id": pid}
            out.append(item)
        write_jsonl(path, out)
        self.say(f"titles: {len(wanted)} languages, {dropped} entries dropped")
        return out

    # 5 ------------------------------------------------------------------------------------
    def api(self, plan: list[dict[str, Any]], start: date, end: date) -> list[Views]:
        path = self.out / "views_api.csv"
        if path.exists():
            return read_views_csv(path)
        rows: list[Views] = []
        status = []
        for i, item in enumerate(plan):
            try:
                series = pageviews.daily_views(
                    self.client, item["project"], item["title"], start, end, self.complete_until
                )
            except (CallCapReached, SourceBlocked) as exc:
                self.say(f"api: stopped after {i} calls: {exc}")
                status.extend({**p, "status": "not fetched"} for p in plan[i:])
                break
            except (requests.HTTPError, ValueError) as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                status.append({**item, "status": f"error {code or type(exc).__name__}"})
                continue
            status.append(
                {**item, "status": "ok", "days_with_views": sum(1 for v in series.values() if v)}
            )
            rows.extend(
                Views(
                    date=day,
                    qid=item["qid"],
                    project=item["project"],
                    views=views,
                    source="api",
                    noisy=False,
                )
                for day, views in series.items()
            )
            if (i + 1) % 250 == 0:
                self.say(f"api: {i + 1} of {len(plan)} calls")
        write_jsonl(self.out / "api_status.jsonl", status)
        write_views_csv(path, rows)
        self.say(f"api: {sum(1 for s in status if s['status'] == 'ok')} series, {len(rows)} rows")
        return rows

    # 6 ------------------------------------------------------------------------------------
    def attention(
        self, events: list[Event], pages: list[EventPage], api_rows: list[Views]
    ) -> list[Attention]:
        series: dict[tuple[str, str], dict[date, int]] = defaultdict(dict)
        for row in api_rows:
            series[(row.qid, row.project)][row.date] = row.views
        projects_by_qid: dict[str, set[str]] = defaultdict(set)
        for qid, project in series:
            projects_by_qid[qid].add(project)
        by_id = {e.event_id: e for e in events}
        out: list[Attention] = []
        done: set[tuple[str, str, str]] = set()
        for page in pages:
            if page.qid is None:
                continue
            event = by_id[page.event_id]
            for project in sorted(projects_by_qid.get(page.qid, ())):
                key = (page.event_id, page.qid, project)
                if key in done:
                    continue
                done.add(key)
                out.extend(
                    measures.attention_rows(
                        page.event_id, event.date, page.qid, project, series[(page.qid, project)]
                    )
                )
        write_jsonl(self.out / "attention.jsonl", out)
        self.say(f"attention: {len(out)} rows")
        return out
