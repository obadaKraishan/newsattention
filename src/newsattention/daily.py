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
   the whole span; for items whose events are 7 or 28 days old and whose English series does not
   reach that day, one follow-up call that closes the gap up to T-1.

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
FOLLOW_UPS = (7, 28)
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
    """The linked items of every portal day in the store (one pass over the day files)."""
    resolved = backfill.load_resolved(store)
    out: dict[date, set[str]] = {}
    for data in store.days():
        qids = set()
        for link in data.get("links", []):
            res = resolved.get(link["title"])
            if res and res.qid:
                qids.add(res.qid)
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
    say(f"links: {lk['resolved_now']} new titles resolved, {len(new_items)} new items")
    out["links"] = {**lk, "new_items": len(new_items)}

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
        entries.extend({**e, "kind": "current", **span} for e in fresh)
    due, unseen = follow_ups_due(items_by_day(store), covered, day)
    for qid in sorted(due):
        if qid not in after_items or qid in unseen:
            continue
        title, pid = after_items[qid]
        entries.append(
            {
                "qid": qid,
                "project": EN,
                "title": title,
                "page_id": pid,
                "rank": 0,
                "kind": "current",
                "follow_up": True,
                "span_start": due[qid].isoformat(),
                "span_end": day.isoformat(),
            }
        )
    # Old titles that redirect to a followed page get the same days (see plan_redirects).
    since: dict[tuple[str, str], tuple[date, dict[str, Any]]] = {}
    for e in existing:
        if e.get("kind") == "redirect":
            k = (e["qid"], e["title"])
            start_e = date.fromisoformat(e["span_start"])
            if k not in since or start_e < since[k][0]:
                since[k] = (start_e, e)
    followed = {
        e["qid"]: date.fromisoformat(e["span_start"]) for e in entries if e.get("follow_up")
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
    say(
        f"api: {len(entries)} calls planned ({len(new_items)} new items, "
        f"{len(entries) - sum(1 for e in entries if e.get('follow_up'))} for them; "
        f"{sum(1 for e in entries if e.get('follow_up'))} follow-ups); "
        f"{api['calls']} made, {api['errors']} errors"
    )
    out["api"] = {"planned": len(entries), **api}
    return out
