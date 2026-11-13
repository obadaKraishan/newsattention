"""The daily update: ``newsattention daily``.

On day T it processes T-1 and the follow-ups that fall due:

1. ``portal``: the day page for T-1 (first read).
2. ``reread``: the days whose 7-day or 30-day re-read is due.
3. ``links``: new linked titles to canonical titles, page ids and Wikidata ids.
4. ``moves``: the English move log for days not read yet.
5. ``dp``: the country file for T-1 (a missing length is asked for again once; an empty file
   is marked missing and tried again on later days for a week); then the rows of linked items,
   with the last 29 files filtered again when new items appeared, so they get a baseline.
6. ``api``: for new items, English and up to five other languages over the whole span; for
   items of events that are 7 or 28 days old, a follow-up call from the event day to T-1.

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


def run_daily(
    client: WikimediaClient,
    store: Store,
    today: date,
    span_start: date,
    say: Say = print,
    languages: int = 5,
) -> dict[str, Any]:
    day = today - timedelta(days=1)
    out: dict[str, Any] = {"day": day.isoformat()}
    before = set(linked_items(store))

    p = backfill.portal_backfill(client, store, day, day, say=lambda m: None)
    say(f"portal: {p['read']} day page read ({p['missing']} missing)")
    out["portal"] = p

    r = backfill.reread(client, store, today, say=lambda m: None)
    say(
        f"reread: {r['due']} due, {r['changed']} changed (+{r['added']} -{r['removed']} "
        f"~{r['reworded']} events)"
    )
    out["reread"] = r

    lk = backfill.resolve_links(client, store, say=lambda m: None)
    after_items = linked_items(store)
    new_items = sorted(set(after_items) - before)
    say(f"links: {lk['resolved_now']} new titles resolved, {len(new_items)} new items")
    out["links"] = {**lk, "new_items": len(new_items)}

    mv = backfill.scan_moves(client, store, day - timedelta(days=6), day, say=lambda m: None)
    say(f"moves: {mv['entries']} log entries in {mv['windows']} new windows")
    out["moves"] = mv

    retry_from = day - timedelta(days=RETRY_MISSING_DAYS)
    dl = backfill.dp_download(client, store, retry_from, day, say=lambda m: None)
    qids = set(after_items)
    filt = backfill.dp_filter(store, qids, day, day, say=lambda m: None)
    refilter = {"days": 0, "rows": 0}
    if new_items:
        refilter = backfill.dp_filter(
            store,
            qids,
            day - timedelta(days=29),
            day - timedelta(days=1),
            say=lambda m: None,
            force=True,
        )
    say(
        f"dp: {dl['downloaded']} downloaded, {dl['empty']} empty; {filt['rows']} rows kept; "
        f"{refilter['days']} days filtered again for new items"
    )
    out["dp"] = {"download": dl, "filter": filt, "refilter": refilter}

    plan_path = store.root / "api" / "plan.jsonl"
    entries: list[dict[str, Any]] = []
    if new_items:
        totals = backfill.dp_totals(store)
        fresh = backfill.plan_languages({q: after_items[q] for q in new_items}, totals, languages)
        fresh, _ = backfill.fill_titles(client, fresh, say=lambda m: None)
        entries.extend({**e, "kind": "current"} for e in fresh)
    for k in FOLLOW_UPS:
        event_day = day - timedelta(days=k)
        for qid in sorted(items_of_day(store, event_day)):
            if qid in after_items:
                title, pid = after_items[qid]
                entries.append(
                    {
                        "qid": qid,
                        "project": EN,
                        "title": title,
                        "page_id": pid,
                        "rank": 0,
                        "kind": "current",
                        "follow_up": k,
                        "span_start": event_day.isoformat(),
                        "span_end": day.isoformat(),
                    }
                )
    existing = backfill.read_jsonl(plan_path)
    backfill.append_jsonl(plan_path, entries)
    full = existing + entries
    api = backfill.api_backfill(client, store, full, span_start, day, say=lambda m: None)
    say(
        f"api: {len(entries)} calls planned ({len(new_items)} new items, follow-ups at "
        f"{'/'.join(str(k) for k in FOLLOW_UPS)} days); {api['calls']} made, "
        f"{api['errors']} errors"
    )
    out["api"] = {"planned": len(entries), **api}
    return out
