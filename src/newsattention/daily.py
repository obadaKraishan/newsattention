"""The daily update: ``newsattention daily``.

On day T it brings the store up to T-1. Every step starts where the store stops, so a run
after missed days (a weekly run, say) catches up, and a missed day costs nothing:

1. ``portal``: the day pages from the day after the last one read to T-1 (first reads).
2. ``reread``: every day whose 7-day or 30-day re-read is due.
3. ``links``: new linked titles to canonical titles, page ids and Wikidata ids.
4. ``moves``: the English move log for days not read yet.
5. ``dp``: the country files from the day after the last one known (and at least the last week,
   so a missing or empty file is asked for again for a week); then the rows of linked items in
   every file of that window not filtered yet. When new items appeared, every file from 29 days
   before the first new portal day is filtered again, so they get a baseline.
6. ``api``: for items with no English series yet, English and up to five other languages over
   the whole span, and for linked articles with no Wikidata item an English call by title over
   the span (their series is named by the page id). Follow-ups close each series' gap up to
   T-1: English when an event is 1, 7 or 28 days old and its series does not reach that day
   (so day-0 views of an existing item arrive the next day); every other language once, when
   an event is 27 days old (days 0 to 27, on the 28th day), so other-language measures of an
   event are complete 28 days after it.

Each step prints one summary line. Tables are rebuilt with ``newsattention tables``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from newsattention import backfill
from newsattention.backfill import EN, Store
from newsattention.client import WikimediaClient

Say = Callable[[str], None]
#: English follow-ups: days after the event whose views the series must reach.
FOLLOW_UPS = (1, 7, 28)
#: Other languages: one follow-up, for days 0 to 27 of the event.
OTHER_FOLLOW_UP = 27
RETRY_MISSING_DAYS = 7


def linked_items(store: Store) -> dict[str, tuple[str, int]]:
    resolved = backfill.load_resolved(store)
    out: dict[str, tuple[str, int]] = {}
    for link in backfill.collect_links(store):
        res = resolved.get(link["title"])
        if res and res.qid and res.page_id:
            out.setdefault(res.qid, (res.title, res.page_id))
    return out


def items_of_day(store: Store, day: date) -> set[str]:
    resolved = backfill.load_resolved(store)
    data = store.load_day(day) or {"links": []}
    out = set()
    for link in data["links"]:
        res = resolved.get(link["title"])
        if res and res.qid:
            out.add(res.qid)
    return out


def items_by_day(store: Store) -> dict[date, set[str]]:
    """The linked series of every portal day in the store (one pass over the day files).

    A series is an item's qid, or ``page:<id>`` for a linked article with no Wikidata item.
    """
    resolved = backfill.load_resolved(store)
    out: dict[date, set[str]] = {}
    for data in store.days():
        qids = set()
        for link in data.get("links", []):
            res = resolved.get(link["title"])
            if res and (res.qid or res.page_id):
                qids.add(backfill.series_id(res.qid, res.page_id))
        out[date.fromisoformat(data["day"])] = qids
    return out


def last_portal_day(store: Store) -> date | None:
    files = list(store.day_files())
    return date.fromisoformat(files[-1].stem) if files else None


def last_known_file_day(store: Store) -> date | None:
    days = [row["day"] for row in backfill.read_jsonl(store.coverage)]
    return date.fromisoformat(max(days)) if days else None


def follow_ups_due(
    by_day: dict[date, set[str]],
    covered: dict[tuple[str, str], tuple[date, date]],
    day: date,
) -> tuple[dict[str, date], set[str]]:
    """English follow-ups that are due on ``day`` (T-1), however many days were missed.

    An item is due when one of its events is at least 7 (or 28) days old and its series does
    not yet reach that follow-up day. The call starts at the earliest such event day, and no
    later than the day before the series' last fetched day, so the series has no gap and the
    last days, which may have been incomplete when they were fetched, are read again. Items
    with no English series at all are returned apart: they need a call for the whole span.
    """
    due: dict[str, date] = {}
    unseen: set[str] = set()
    for event_day, qids in by_day.items():
        for k in FOLLOW_UPS:
            target = event_day + timedelta(days=k)
            if target > day:
                continue
            for qid in qids:
                span = covered.get((qid, EN))
                if span is None:
                    unseen.add(qid)
                elif span[1] < target:
                    start = min(event_day, span[1] - timedelta(days=1))
                    due[qid] = min(due.get(qid, start), start)
    return due, unseen


def other_language_follow_ups(
    by_day: dict[date, set[str]],
    covered: dict[tuple[str, str], tuple[date, date]],
    day: date,
) -> dict[tuple[str, str], date]:
    """Other-language follow-ups due on ``day`` (T-1): one per series, at day 27 of an event.

    A series of another language is due when one of its item's events is at least 27 days old
    and the series does not reach that event's day 27. As for English, the call starts at the
    earliest such event day and no later than the day before the series' last fetched day.
    Only series that were fetched before are followed up.
    """
    projects: dict[str, list[str]] = {}
    for qid, project in covered:
        if project != EN:
            projects.setdefault(qid, []).append(project)
    due: dict[tuple[str, str], date] = {}
    for event_day, qids in by_day.items():
        target = event_day + timedelta(days=OTHER_FOLLOW_UP)
        if target > day:
            continue
        for qid in qids:
            for project in projects.get(qid, ()):
                last = covered[(qid, project)][1]
                if last < target:
                    start = min(event_day, last - timedelta(days=1))
                    key = (qid, project)
                    due[key] = min(due.get(key, start), start)
    return due


def run_daily(
    client: WikimediaClient,
    store: Store,
    today: date,
    span_start: date,
    say: Say = print,
    languages: int = 5,
) -> dict[str, Any]:
    """The daily update for ``today``: every step catches up from where the store stops."""
    day = today - timedelta(days=1)
    out: dict[str, Any] = {"day": day.isoformat()}
    last_read = last_portal_day(store)
    first_new = min(last_read + timedelta(days=1), day) if last_read else day

    p = backfill.portal_backfill(client, store, first_new, day, say=lambda m: None)
    say(f"portal: {p['read']} day pages read from {first_new} to {day} ({p['missing']} missing)")
    out["portal"] = {**p, "from": first_new.isoformat()}

    r = backfill.reread(client, store, today, say=lambda m: None)
    say(
        f"reread: {r['due']} due, {r['changed']} changed (+{r['added']} -{r['removed']} "
        f"~{r['reworded']} events)"
    )
    out["reread"] = r

    lk = backfill.resolve_links(client, store, say=lambda m: None)
    after_items = linked_items(store)
    plan_path = store.root / "api" / "plan.jsonl"
    existing = backfill.read_jsonl(plan_path)
    statuses = backfill.read_jsonl(store.root / "api" / "status.jsonl")
    covered = backfill.coverage(existing, statuses, backfill.full_span_end(store), span_start)
    planned = {(e["qid"], e["project"]) for e in existing if e.get("kind") == "current"}
    new_items = sorted(q for q in after_items if (q, EN) not in planned)
    no_item = backfill.linked_without_item(store)
    planned_pages = {
        e["page_id"] for e in existing if e.get("kind") == "current" and not e.get("qid")
    }
    new_pages = sorted(pid for pid in no_item if pid not in planned_pages)
    say(
        f"links: {lk['resolved_now']} new titles resolved, {len(new_items)} new items; "
        f"{len(no_item)} linked articles with no item ({len(new_pages)} new)"
    )
    out["links"] = {
        **lk,
        "new_items": len(new_items),
        "no_item": len(no_item),
        "no_item_new": len(new_pages),
    }

    mv = backfill.scan_moves(client, store, first_new - timedelta(days=6), day, say=lambda m: None)
    say(f"moves: {mv['entries']} log entries in {mv['windows']} new windows")
    out["moves"] = mv

    known = last_known_file_day(store)
    dp_from = day - timedelta(days=RETRY_MISSING_DAYS)
    if known is not None and known + timedelta(days=1) < dp_from:
        dp_from = known + timedelta(days=1)
    dl = backfill.dp_download(client, store, dp_from, day, say=lambda m: None)
    qids = set(after_items)
    if new_items:
        # New items need rows in every file of their events' baseline windows.
        filter_from = min(dp_from, first_new - timedelta(days=29))
        filt = backfill.dp_filter(store, qids, filter_from, day, say=lambda m: None, force=True)
    else:
        # Every file of the window not filtered yet, so a file that came late gets its rows.
        filter_from = dp_from
        filt = backfill.dp_filter(store, qids, dp_from, day, say=lambda m: None)
    say(
        f"dp: {dl['downloaded']} downloaded from {dp_from}, {dl['empty']} empty; "
        f"{filt['days']} files filtered from {filter_from}"
        f"{' again for new items' if new_items else ''}, {filt['rows']} rows kept"
    )
    out["dp"] = {"from": dp_from.isoformat(), "download": dl, "filter": filt}

    entries: list[dict[str, Any]] = []
    if new_items:
        totals = backfill.dp_totals(store)
        fresh = backfill.plan_languages({q: after_items[q] for q in new_items}, totals, languages)
        fresh, _ = backfill.fill_titles(client, fresh, say=lambda m: None)
        span = {"span_start": span_start.isoformat(), "span_end": day.isoformat()}
        current = [{**e, "kind": "current", **span} for e in fresh]
        entries.extend(current)
        # A new item whose English page moved inside the span needs its old titles too.
        english = [e for e in current if e["project"] == EN]
        moves = backfill.load_moves(store, {e["page_id"] for e in english})
        with_old = backfill.add_old_titles(english, moves, span_start, day)
        entries.extend(with_old[len(english) :])
    if new_pages:
        # Articles with no Wikidata item: English by title over the span, named by page id.
        span = {"span_start": span_start.isoformat(), "span_end": day.isoformat()}
        pages = [
            {"qid": None, "project": EN, "title": no_item[pid], "page_id": pid, "rank": 0}
            | {"kind": "current", **span}
            for pid in new_pages
        ]
        entries.extend(pages)
        moves = backfill.load_moves(store, set(new_pages))
        entries.extend(backfill.add_old_titles(pages, moves, span_start, day)[len(pages) :])
    by_day = items_by_day(store)
    due, unseen = follow_ups_due(by_day, covered, day)
    for sid in sorted(due):
        qid, page_id = backfill.split_series_id(sid)
        if qid is not None and (qid not in after_items or qid in unseen):
            continue
        if page_id is not None and page_id not in no_item:
            continue
        title, pid = after_items[qid] if qid is not None else (no_item[page_id], page_id)
        entries.append(
            {
                "qid": qid,
                "project": EN,
                "title": title,
                "page_id": pid,
                "rank": 0,
                "kind": "current",
                "follow_up": True,
                "span_start": due[sid].isoformat(),
                "span_end": day.isoformat(),
            }
        )
    # Other languages: once, at day 27, under the title of the series' latest call.
    latest = {
        (e["qid"], e["project"]): e
        for e in existing
        if e.get("kind") == "current" and e["project"] != EN and e.get("qid")
    }
    other_due = other_language_follow_ups(by_day, covered, day)
    for key in sorted(other_due):
        e = latest.get(key)
        if e is None:
            continue
        entries.append(
            {
                **{k: e[k] for k in ("qid", "project", "title", "page_id", "rank")},
                "kind": "current",
                "follow_up": True,
                "span_start": other_due[key].isoformat(),
                "span_end": day.isoformat(),
            }
        )
    # Old titles that redirect to a followed page get the same days (see plan_redirects).
    since: dict[tuple[str, str], tuple[date, dict[str, Any]]] = {}
    for e in existing:
        if e.get("kind") == "redirect":
            k = (backfill.series_id(e["qid"], e.get("page_id")), e["title"])
            start_e = date.fromisoformat(e["span_start"])
            if k not in since or start_e < since[k][0]:
                since[k] = (start_e, e)
    followed = {
        backfill.series_id(e["qid"], e["page_id"]): date.fromisoformat(e["span_start"])
        for e in entries
        if e.get("follow_up") and e["project"] == EN
    }
    for (qid, title), (start_r, e) in sorted(since.items()):
        if qid in followed:
            entries.append(
                {
                    **{k: e[k] for k in ("qid", "project", "page_id", "rank")},
                    "title": title,
                    "kind": "redirect",
                    "follow_up": True,
                    "span_start": max(followed[qid], start_r).isoformat(),
                    "span_end": day.isoformat(),
                }
            )
    backfill.append_jsonl(plan_path, entries)
    full = existing + entries
    api = backfill.api_backfill(client, store, full, span_start, day, say=lambda m: None)
    follow = [e for e in entries if e.get("follow_up")]
    kinds = {
        "new_items_and_pages": len(entries) - len(follow),
        "follow_ups_english": sum(
            1 for e in follow if e["project"] == EN and e["kind"] != "redirect"
        ),
        "follow_ups_redirects": sum(1 for e in follow if e["kind"] == "redirect"),
        "follow_ups_other_languages": sum(1 for e in follow if e["project"] != EN),
    }
    say(
        f"api: {len(entries)} calls planned ({len(new_items)} new items and {len(new_pages)} "
        f"articles with no item, {kinds['new_items_and_pages']} for them; {len(follow)} "
        f"follow-ups: {kinds['follow_ups_english']} English, {kinds['follow_ups_redirects']} "
        f"redirects, {kinds['follow_ups_other_languages']} other languages); "
        f"{api['calls']} made, {api['errors']} errors"
    )
    out["api"] = {"planned": len(entries), **kinds, **api}
    return out
