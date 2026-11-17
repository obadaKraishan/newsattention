"""Backfill, re-read and daily commands for the ``newsattention`` command line."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from newsattention import backfill, lock
from newsattention.client import Budget, UsageLog, WikimediaClient

DEFAULT_STORE = Path("data/interim/store")
DEFAULT_RAW = Path("data/raw")
DEFAULT_LOG = Path("data/interim/logs/usage.csv")
SPAN_START = date(2023, 1, 9)  # 28 days before 2023-02-06
V1_START = date(2023, 2, 6)


def yesterday() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def command_name(args: argparse.Namespace) -> str:
    func = getattr(args, "func", None)
    return func.__name__.removeprefix("cmd_").replace("_", "-") if func else "newsattention"


def make_client(args: argparse.Namespace) -> WikimediaClient:
    """A client whose caps count every request in the log since ``--since``.

    It first takes the Wikimedia lock (one command at a time on this machine, whatever the
    host); a second command refuses with a plain message, or waits with ``--wait``.
    """
    try:
        lock.hold(command_name(args), wait=getattr(args, "wait", False))
    except lock.CommandBusy as exc:
        raise SystemExit(str(exc)) from None
    usage = UsageLog(args.log)
    since = args.since or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    caps: dict[str, int] = {"analytics": args.cap_analytics}
    for family in ("action", "wikidata"):
        cap = getattr(args, f"cap_{family}", None)
        if cap is not None:
            caps[family] = cap
    groups = {"mediawiki": (("action", "wikidata"), args.cap_mediawiki)}
    budget = Budget.from_log(usage.rows(), since, caps, args.max_bytes, groups)
    return WikimediaClient(usage, budget, min_interval=args.min_interval)


def store_of(args: argparse.Namespace) -> backfill.Store:
    return backfill.Store(args.store, args.raw)


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_portal_backfill(args: argparse.Namespace) -> int:
    out = backfill.portal_backfill(make_client(args), store_of(args), args.start, args.end)
    _print(out)
    return 0


def cmd_reread(args: argparse.Namespace) -> int:
    out = backfill.reread(make_client(args), store_of(args), args.today)
    _print(out)
    return 0


def cmd_reparse(args: argparse.Namespace) -> int:
    _print(backfill.reparse(store_of(args)))
    return 0


def cmd_parse_report(args: argparse.Namespace) -> int:
    report = backfill.parse_report(store_of(args))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    _print({m: {k: v for k, v in r.items() if not isinstance(v, dict)} for m, r in report.items()})
    return 0


def cmd_links(args: argparse.Namespace) -> int:
    _print(backfill.resolve_links(make_client(args), store_of(args)))
    return 0


def linked_pages(store: backfill.Store) -> dict[str, tuple[str, int]]:
    """qid -> (canonical English title, page id) for every linked page with a qid."""
    resolved = backfill.load_resolved(store)
    out: dict[str, tuple[str, int]] = {}
    for link in backfill.collect_links(store):
        res = resolved.get(link["title"])
        if res and res.qid and res.page_id:
            out.setdefault(res.qid, (res.title, res.page_id))
    return out


def cmd_pages(args: argparse.Namespace) -> int:
    store = store_of(args)
    client = make_client(args)
    pages = linked_pages(store)
    ids = sorted({pid for _, pid in pages.values()})
    anchors = backfill.creation_anchors(client, store, ids, args.anchors)
    check = validate_creation(client, store, ids, anchors, args.check, args.seed)
    moves = backfill.scan_moves(client, store, args.moves_start, args.end)
    _print({"pages": len(pages), "anchors": len(anchors), "creation_check": check, "moves": moves})
    return 0


def validate_creation(
    client: WikimediaClient,
    store: backfill.Store,
    ids: list[int],
    anchors: list[dict[str, Any]],
    n: int,
    seed: int,
) -> dict[str, Any]:
    """Compare the page-id estimate with the true first revision on ``n`` random other pages."""
    import random

    path = store.root / "pages" / "creation_check.jsonl"
    have = {r["page_id"]: r for r in backfill.read_jsonl(path)}
    taken = {a["page_id"] for a in anchors}
    pool = [pid for pid in ids if pid not in taken]
    for pid in random.Random(seed).sample(pool, min(n, len(pool))):
        if pid not in have:
            row = {"page_id": pid, "first_revision": backfill.first_revision(client, pid)}
            backfill.append_jsonl(path, [row])
            have[pid] = row
    model = backfill.CreationModel(anchors)
    errors = []
    for row in have.values():
        if not row["first_revision"]:
            continue
        true = datetime.fromisoformat(row["first_revision"].replace("Z", "+00:00"))
        est, _ = model.estimate(row["page_id"])
        errors.append(abs((est - true).total_seconds()) / 86400)
    errors.sort()
    if not errors:
        return {"checked": 0}
    return {
        "checked": len(errors),
        "median_error_days": round(errors[len(errors) // 2], 2),
        "p90_error_days": round(errors[int(len(errors) * 0.9)], 2),
        "max_error_days": round(errors[-1], 2),
    }


def cmd_dp_download(args: argparse.Namespace) -> int:
    _print(backfill.dp_download(make_client(args), store_of(args), args.start, args.end))
    return 0


def cmd_dp_filter(args: argparse.Namespace) -> int:
    store = store_of(args)
    qids = set(linked_pages(store))
    _print(backfill.dp_filter(store, qids, args.start, args.end, force=args.force))
    return 0


def plan_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item["qid"], item["project"], item["title"], item["kind"], item.get("span_start"))


def cmd_plan(args: argparse.Namespace) -> int:
    """Write the language-view plan, or append to it.

    ``--english-only`` writes the English current titles alone, so the backfill can start
    before the country files are filtered. A later run without it appends the other
    languages and the old titles of moved pages; entries already planned keep their index, so
    a running or resumed backfill is never disturbed.
    """
    store = store_of(args)
    pages = linked_pages(store)
    path = store.root / "api" / "plan.jsonl"
    existing = backfill.read_jsonl(path)
    if existing and args.force:
        raise SystemExit("A plan exists; it is only ever appended to. Move it aside by hand.")
    totals = {} if args.english_only else backfill.dp_totals(store)
    plan = backfill.plan_languages(pages, totals, args.languages)
    client = make_client(args)
    plan, title_stats = backfill.fill_titles(client, plan)
    if not args.english_only:
        moves = backfill.load_moves(store, {pid for _, pid in pages.values()})
        plan = backfill.add_old_titles(plan, moves, SPAN_START, args.end)
    have = {plan_key(p) for p in existing}
    new = [p for p in plan if plan_key(p) not in have]
    path.parent.mkdir(parents=True, exist_ok=True)
    backfill.append_jsonl(path, new)
    full = existing + new
    summary = {
        "items": len(pages),
        "calls": len(full),
        "appended_now": len(new),
        "english": sum(
            1 for p in full if p["project"] == "en.wikipedia" and p["kind"] == "current"
        ),
        "english_old_titles": sum(1 for p in full if p["kind"] == "old_title"),
        "other_languages": sum(1 for p in full if p["project"] != "en.wikipedia"),
        "hours_at_api_interval": round(len(full) * args.api_interval / 3600, 1),
        **title_stats,
    }
    (store.root / "api" / "plan_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    _print(summary)
    return 0


def cmd_classes(args: argparse.Namespace) -> int:
    """Wikidata "instance of" classes of every linked item, with labels and superclasses."""
    store = store_of(args)
    qids = set(linked_pages(store))
    out = backfill.fetch_classes(make_client(args), store, qids, depth=args.depth)
    _print(out)
    return 0 if out["stopped"] is None else 1


def cmd_old_titles(args: argparse.Namespace) -> int:
    """Plan the views that reach moved pages through their old titles after each move."""
    store = store_of(args)
    path = store.root / "api" / "plan.jsonl"
    plan = backfill.read_jsonl(path)
    statuses = backfill.read_jsonl(store.root / "api" / "status.jsonl")
    covered = backfill.coverage(plan, statuses, backfill.full_span_end(store), SPAN_START)
    entries, stats = backfill.plan_redirects(make_client(args), store, plan, covered)
    backfill.append_jsonl(path, entries)
    _print({**stats, "appended": len(entries), "plan": len(plan) + len(entries)})
    return 0


def cmd_roles(args: argparse.Namespace) -> int:
    """Give the event pages of built tables their roles again (after new Wikidata classes)."""
    from newsattention import tables

    _print(tables.build_roles(store_of(args), args.tables))
    return 0


def rule_answers(rows: list[dict[str, Any]], assigned: list[tuple[str, str]]) -> dict[str, Any]:
    """The rule's two answers for one event (link numbers or "none"), with their confidence."""
    from newsattention import roles

    conf = {r["link_order"]: c for r, (_, c) in zip(rows, assigned, strict=True)}
    event_link = next(
        (r["link_order"] for r, (role, _) in zip(rows, assigned, strict=True) if role == "event"),
        None,
    )
    story = roles.main_story(rows, assigned)
    return {
        "Q1": event_link or "none",
        "Q2": story or "none",
        "Q1_confidence": conf.get(event_link) if event_link else None,
        "Q2_confidence": conf.get(story) if story else None,
        "roles": [[role, c] for role, c in assigned],
    }


def file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def roles_sha256() -> str:
    """The SHA-256 of ``roles.py``, the rule's code: the freeze records it."""
    from newsattention import roles

    return file_sha256(Path(roles.__file__))


def links_by_event(files: dict[Path, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    links: dict[str, list[dict[str, Any]]] = {}
    for rows in files.values():
        for r in rows:
            links.setdefault(r["event_id"], []).append(r)
    for rows in links.values():
        rows.sort(key=lambda r: r["link_order"])
    return links


def sheets_titles(folder: Path) -> dict[str, list[str]]:
    from newsattention import review

    out: dict[str, list[str]] = {}
    for path in sorted(folder.glob("sheet-*.xlsx")):
        out.update(review.sheet_links(path))
    return out


def check_same_links(
    design: list[dict[str, Any]],
    links: dict[str, list[dict[str, Any]]],
    shown: dict[str, list[str]],
) -> None:
    """Refuse when the tables show an event's links otherwise than its sheet did."""
    gone, other = [], []
    for d in design:
        where = f"{d['sheet']} event {d['number']}"
        rows = links.get(d["event_id"])
        if rows is None:
            gone.append(where)
        elif [r["page_title"] for r in rows] != shown.get(d["event_id"]):
            other.append(where)
    if gone or other:
        raise SystemExit(
            f"{len(gone)} sampled events are no longer in the tables and {len(other)} show "
            f"other links than on their sheet ({', '.join((gone + other)[:8])}). The rule's "
            "answers would not match what was answered: build them from the tables the sheets "
            "were drawn from."
        )


def cmd_review_key(args: argparse.Namespace) -> int:
    """The rule's answers for the drawn events, from the current code, with or without classes."""
    from newsattention import roles, tables

    store = store_of(args)
    design = json.loads(args.design.read_text())["events"]
    use_classes = not args.without_classes
    files, all_roles, _ = tables.compute_roles(store, args.tables, use_classes=use_classes)
    links = links_by_event(files)
    check_same_links(design, links, sheets_titles(args.sheets))
    key = [
        {
            **{k: d[k] for k in ("sheet", "number", "event_id", "stratum")},
            "rule_version": roles.RULE_VERSION,
            **rule_answers(links[d["event_id"]], all_roles[d["event_id"]]),
        }
        for d in design
    ]
    classes = len(backfill.read_jsonl(store.root / "wikidata" / "instance_of.jsonl"))
    made = {
        "rule_version": roles.RULE_VERSION,
        "roles_sha256": roles_sha256(),
        "variant": "with_classes" if use_classes else "without_classes",
        "items_with_classes": classes if use_classes else 0,
        "made_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    backfill.write_json(args.out, {**made, "events": key})
    counts = {
        q: {
            "link": sum(1 for k in key if k[q] != "none"),
            "none": sum(1 for k in key if k[q] == "none"),
        }
        for q in ("Q1", "Q2")
    }
    _print({**made, "events": len(key), "answers": counts, "key": str(args.out)})
    return 0


def event_categories(tables_dir: Path, ids: set[str]) -> dict[str, str]:
    import pyarrow.dataset as ds

    table = ds.dataset(str(tables_dir / "events"), format="parquet").to_table(
        columns=["event_id", "category"]
    )
    return {
        e: c
        for e, c in zip(table["event_id"].to_pylist(), table["category"].to_pylist(), strict=True)
        if e in ids
    }


def cmd_review_score(args: argparse.Namespace) -> int:
    """Score the rule's answers against the filled sheets: aggregates only, by default."""
    from newsattention import review, scoring

    design = json.loads(args.design.read_text())["events"]
    key = json.loads(args.key.read_text())
    now = roles_sha256()
    if key["roles_sha256"] != now:
        raise SystemExit(
            f"{args.key} was made with another roles.py (SHA-256 {key['roles_sha256'][:12]}...) "
            f"than the one here ({now[:12]}...). Make the key again with review-key."
        )
    if args.freeze:
        freeze = json.loads(args.freeze.read_text())
        if (freeze["rule_version"], freeze["roles_sha256"]) != (key["rule_version"], now):
            raise SystemExit(
                f"roles.py is not the frozen rule of {args.freeze} (version "
                f"{freeze['rule_version']}, SHA-256 {freeze['roles_sha256'][:12]}...)."
            )
    answers = []
    for path in args.files:
        check = review.check_sheet(path)
        if not check.ok:
            raise SystemExit(f"{path.name} is not complete or has problems: run review-check.")
        answers.extend({"sheet": path.name, **a} for a in check.answers)
    ids = {d["event_id"] for d in design}
    rows = scoring.join(design, key["events"], answers, event_categories(args.tables, ids))
    summary = scoring.summarize(rows, args.reps, args.seed)
    out = {
        **{k: key[k] for k in ("variant", "rule_version", "roles_sha256", "items_with_classes")},
        "key_sha256": file_sha256(args.key),
        "sheets_sha256": {p.name: file_sha256(p) for p in args.files},
        **summary,
    }
    backfill.write_json(args.out, out)
    for q in ("Q1", "Q2"):
        s = summary[q]
        lo, hi = s["interval90"]
        print(
            f"{q}: right {s['right_weighted']:.1%} weighted (90% interval {lo:.1%} to {hi:.1%}; "
            f"{s['right_events']} of {s['events']} events); {s['verdict']}"
        )
    b = summary["both_right"]
    print(f"both: right {b['right_weighted']:.1%} weighted ({b['right_events']} events)")
    print(f"aggregates written to {args.out}")
    if args.differences:
        backfill.write_json(args.differences, scoring.differences(rows))
        print(f"differences by event number written to {args.differences}")
    return 0


def cmd_review_recheck(args: argparse.Namespace) -> int:
    """A blind recheck copy of some sampled events, in a new order, and its key apart."""
    from newsattention import review, tables

    design = json.loads(args.design.read_text())
    sheet = args.out / f"DO-NOT-OPEN-BEFORE-{args.not_before}_recheck-{args.size}.xlsx"
    if sheet.exists() or args.key.exists():
        raise SystemExit(f"{sheet} or {args.key} exists already; a recheck copy is drawn once.")
    alloc = review.recheck_allocation(design["strata"], args.size)
    chosen = review.draw_recheck(design["events"], alloc, args.seed)
    files, _, events = tables.compute_roles(store_of(args), args.tables, use_classes=False)
    links = links_by_event(files)
    check_same_links(chosen, links, sheets_titles(args.sheets))
    sheet_events, key = [], []
    for n, d in enumerate(chosen, 1):
        ev, rows = events[d["event_id"]], links[d["event_id"]]
        titles = [r["page_title"] for r in rows]
        sheet_events.append(
            review.SheetEvent(
                n, d["event_id"], ev["date"].isoformat(), ev["category"], ev["text"], titles
            )
        )
        key.append(
            {
                "number": n,
                "event_id": d["event_id"],
                "stratum": d["stratum"],
                "first_sheet": d["sheet"],
                "first_number": d["number"],
                "links": len(titles),
            }
        )
    review.write_sheet(sheet, sheet_events, review.recheck_guide(args.not_before, args.size))
    backfill.write_json(
        args.key,
        {
            "seed": args.seed,
            "size": args.size,
            "not_before": args.not_before,
            "allocation": alloc,
            "sheet": sheet.name,
            "chosen_without_answers": True,
            "events": key,
        },
    )
    _print({"sheet": str(sheet), "key": str(args.key), "events": len(key), "allocation": alloc})
    return 0


def cmd_review_sheets(args: argparse.Namespace) -> int:
    """Draw the hand-checked sample and write the blind review sheets and the answer key."""
    from newsattention import review, roles, tables

    store = store_of(args)
    files, all_roles, events = tables.compute_roles(store, args.tables)
    links: dict[str, list[dict[str, Any]]] = {}
    for rows in files.values():
        for r in rows:
            links.setdefault(r["event_id"], []).append(r)
    for rows in links.values():
        rows.sort(key=lambda r: r["link_order"])
    found = {
        eid: any(role == "event" for role, _ in rs)
        for eid, rs in all_roles.items()
        if args.through is None or events[eid]["date"] <= args.through
    }
    exclude = []
    if args.exclude and args.exclude.exists():
        exclude = json.loads(args.exclude.read_text())
    out = args.out
    there = sorted(out.glob("sheet-*.xlsx")) if out.exists() else []
    if there:
        raise SystemExit(
            f"{out} already holds {len(there)} review sheet(s) ({there[0].name}, ...). Filled "
            f"answers would be lost: move the folder aside before drawing again."
        )
    draws = review.draw_design(found, args.seed, exclude=exclude)
    ids = [d.event_id for d in draws]
    drawn = {d.event_id: d for d in draws}
    classes = len(backfill.read_jsonl(store.root / "wikidata" / "instance_of.jsonl"))
    out.mkdir(parents=True, exist_ok=True)
    key = []
    design = []
    for k, batch in enumerate(review.split(ids, 50), 1):
        sheet_events = []
        for n, eid in enumerate(batch, 1):
            ev = events[eid]
            rows = links[eid]
            sheet_events.append(
                review.SheetEvent(
                    n,
                    eid,
                    ev["date"].isoformat(),
                    ev["category"],
                    ev["text"],
                    [r["page_title"] for r in rows],
                )
            )
            d = drawn[eid]
            place = {"sheet": f"sheet-{k}.xlsx", "number": n, "event_id": eid}
            design.append(
                {**place, "stratum": d.stratum, "probability": d.probability, "weight": d.weight}
            )
            key.append(
                {
                    **place,
                    "rule_version": roles.RULE_VERSION,
                    "stratum": d.stratum,
                    "stratum_event_found": found[eid],
                    **rule_answers(rows, all_roles[eid]),
                }
            )
        review.write_sheet(out / f"sheet-{k}.xlsx", sheet_events, review.GUIDE)
    strata: dict[str, dict[str, Any]] = {}
    for d in draws:
        strata[d.stratum] = {
            "stratum": d.stratum,
            "year": d.year,
            "event_found": d.found,
            "size": d.stratum_size,
            "drawn": d.stratum_drawn,
            "probability": d.probability,
            "weight": d.weight,
        }
    skip = set(exclude)
    frame_days = sorted(events[e]["date"] for e in found if e not in skip)
    frame = {
        "definition": (
            "events with at least one linked page, through the last day below, minus the "
            "excluded development events; stratum = year and whether the rule found an event page"
        ),
        "events": len(frame_days),
        "first_day": frame_days[0].isoformat(),
        "last_day": frame_days[-1].isoformat(),
        "excluded": len(exclude),
        "excluded_in_frame": len(skip & set(found)),
        "digest_sha256": review.frame_digest(found, exclude),
    }
    common = {
        "seed": args.seed,
        "rule_version": roles.RULE_VERSION,
        "items_with_classes": classes,
    }
    backfill.write_json(args.key, {**common, "events": key})
    backfill.write_json(
        args.design,
        {
            **common,
            "frame": frame,
            "strata": [strata[s] for s in sorted(strata)],
            "events": design,
        },
    )
    (out / "guide.md").write_text("\n\n".join(review.GUIDE) + "\n", encoding="utf-8")
    _print(
        {
            "events": len(ids),
            "sheets": len(review.split(ids, 50)),
            "found": sum(found[e] for e in ids),
            "frame": frame["events"],
            "items_with_classes": classes,
            "key": str(args.key),
            "design": str(args.design),
            "excluded": len(exclude),
        }
    )
    return 0


def cmd_review_check(args: argparse.Namespace) -> int:
    """Read filled review sheets back; report what is missing or invalid (never a title)."""
    from newsattention import review

    status = 0
    answers = []
    for path in args.files:
        check = review.check_sheet(path)
        notes = sum(1 for a in check.answers if a["notes"])
        print(
            f"{path.name}: {check.events} events, {check.complete} answered in full, "
            f"{notes} with a note"
        )
        for problem in check.problems:
            print(f"  {problem}")
        if not check.ok:
            status = 1
        answers.extend({"sheet": path.name, **a} for a in check.answers)
    if args.answers:
        args.answers.parent.mkdir(parents=True, exist_ok=True)
        backfill.write_json(args.answers, answers)
        print(f"answers written to {args.answers}")
    return status


def cmd_api_backfill(args: argparse.Namespace) -> int:
    store = store_of(args)
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")
    if backfill.full_span_end(store) is None:
        if (store.root / "api" / "status.jsonl").exists():
            raise SystemExit(
                f"{store.root / 'api' / 'meta.json'} is missing. Write the --end of the first "
                'api-backfill run there as {"full_span_end": "YYYY-MM-DD"} before going on.'
            )
        backfill.write_full_span_end(store, args.end)
    out = backfill.api_backfill(
        make_client(args), store, plan, SPAN_START, args.end, max_calls=args.max_calls
    )
    _print(out)
    return 0


def cmd_api_check(args: argparse.Namespace) -> int:
    """Check the saved language views against the plan and the status log (no requests)."""
    store = store_of(args)
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")
    out = backfill.check_api(store, plan, SPAN_START, args.end)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2, default=str) + "\n")
    _print({k: v for k, v in out.items() if k != "refetch"} | {"refetch": len(out["refetch"])})
    return 1 if out["problems"] else 0


def cmd_tables(args: argparse.Namespace) -> int:
    from newsattention import tables

    store = store_of(args)
    out = args.out
    summary: dict[str, Any] = {}
    summary.update(tables.build_events(store, out))
    summary.update(tables.build_pages(store, out, SPAN_START, args.end))
    summary.update(tables.build_views_dp(store, out))
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")
    statuses = backfill.read_jsonl(store.root / "api" / "status.jsonl")
    covered = backfill.coverage(plan, statuses, backfill.full_span_end(store), SPAN_START)
    bank = tables.SeriesBank(SPAN_START, args.end)
    bank.load(sorted((store.raw / "api").glob("chunk-*.parquet")), plan, covered)
    summary["page_series_dropped"] = bank.keep_pages(set(backfill.linked_without_item(store)))
    summary.update(tables.write_views_api(bank, out))
    summary.update(tables.write_series(bank, out, args.end))
    summary.update(tables.build_attention(store, out, bank, args.end))
    summary.update(tables.build_roles(store, out))
    tables.json_dump(out / "build_summary.json", summary)
    _print(summary)
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    from newsattention import daily

    out = daily.run_daily(make_client(args), store_of(args), args.today, SPAN_START)
    _print(out)
    return 0


def register(sub: Any) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", type=Path, default=DEFAULT_STORE)
    common.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    common.add_argument("--log", type=Path, default=DEFAULT_LOG, help="the request log (CSV)")
    common.add_argument("--since", help="count logged calls from this UTC time on")
    common.add_argument("--cap-analytics", type=int, default=3000)
    common.add_argument(
        "--cap-mediawiki",
        type=int,
        default=10_000,
        help="cap for every /w/api.php request (Wikipedia and Wikidata)",
    )
    common.add_argument("--cap-action", type=int, help="cap for Wikipedia /w/api.php requests")
    common.add_argument("--cap-wikidata", type=int, help="cap for Wikidata requests")
    common.add_argument(
        "--wait",
        action="store_true",
        help="wait for another newsattention command to finish instead of refusing",
    )
    common.add_argument(
        "--max-bytes", type=int, default=1_000_000_000, help="cap for file downloads (bytes)"
    )
    common.add_argument(
        "--min-interval",
        type=float,
        default=0.35,
        help="seconds between the starts of two requests",
    )
    span = argparse.ArgumentParser(add_help=False)
    span.add_argument("--start", type=date.fromisoformat, default=V1_START)
    span.add_argument("--end", type=date.fromisoformat, default=yesterday())

    p = sub.add_parser("portal-backfill", parents=[common, span], help="read every day page")
    p.set_defaults(func=cmd_portal_backfill)

    p = sub.add_parser("reread", parents=[common], help="re-read days 7 and 30 days after they end")
    p.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    p.set_defaults(func=cmd_reread)

    p = sub.add_parser("reparse", parents=[common], help="parse every day again from raw files")
    p.set_defaults(func=cmd_reparse)

    p = sub.add_parser("parse-report", parents=[common], help="what the parser could not read")
    p.add_argument("--out", type=Path)
    p.set_defaults(func=cmd_parse_report)

    p = sub.add_parser("links", parents=[common], help="resolve every linked title")
    p.set_defaults(func=cmd_links)

    p = sub.add_parser("pages", parents=[common, span], help="creation anchors and the move log")
    p.add_argument("--anchors", type=int, default=200)
    p.add_argument("--check", type=int, default=60, help="random pages to check the estimate on")
    p.add_argument("--seed", type=int, default=20261113)
    p.add_argument("--moves-start", type=date.fromisoformat, default=SPAN_START)
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("dp-download", parents=[common, span], help="download the country files")
    p.set_defaults(func=cmd_dp_download)

    p = sub.add_parser("dp-filter", parents=[common, span], help="keep rows of linked items")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_dp_filter)

    p = sub.add_parser("plan", parents=[common, span], help="plan the language views")
    p.add_argument("--languages", type=int, default=5)
    p.add_argument("--api-interval", type=float, default=0.55)
    p.add_argument("--english-only", action="store_true")
    p.add_argument("--force", action="store_true", help="refused: a plan is only appended to")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("roles", parents=[common], help="give event pages their roles again")
    p.add_argument("--tables", type=Path, default=Path("data/interim/tables"))
    p.set_defaults(func=cmd_roles)

    p = sub.add_parser("review-sheets", parents=[common], help="draw the sample and write sheets")
    p.add_argument("--tables", type=Path, default=Path("data/interim/tables"))
    p.add_argument("--out", type=Path, default=Path("data/interim/sheets"))
    p.add_argument("--key", type=Path, default=Path("data/interim/answer-key/answer_key.json"))
    p.add_argument("--seed", type=int, default=20261114)
    p.add_argument(
        "--design",
        type=Path,
        default=Path("data/interim/answer-key/sample_design.json"),
        help="where to write each drawn event's stratum and probability of being drawn",
    )
    p.add_argument("--through", type=date.fromisoformat, help="last event day in the frame")
    p.add_argument("--exclude", type=Path, help="JSON list of event ids to leave out")
    p.set_defaults(func=cmd_review_sheets)

    p = sub.add_parser("review-check", help="read filled review sheets back and check them")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--answers", type=Path, help="also write the answers (JSON) for scoring")
    p.set_defaults(func=cmd_review_check)

    design = Path("data/interim/answer-key/sample_design.json")
    p = sub.add_parser("review-key", parents=[common], help="the rule's answers for the sample")
    p.add_argument("--tables", type=Path, default=Path("data/interim/tables"))
    p.add_argument("--sheets", type=Path, default=Path("data/interim/sheets"))
    p.add_argument("--design", type=Path, default=design)
    p.add_argument("--out", type=Path, required=True, help="where to write the answer key")
    p.add_argument("--without-classes", action="store_true", help="ignore the Wikidata classes")
    p.set_defaults(func=cmd_review_key)

    p = sub.add_parser("review-score", help="score the rule against the filled sheets")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--design", type=Path, default=design)
    p.add_argument("--tables", type=Path, default=Path("data/interim/tables"))
    p.add_argument("--freeze", type=Path, help="the freeze record the key must match")
    p.add_argument("--out", type=Path, required=True, help="where to write the aggregates")
    p.add_argument(
        "--differences", type=Path, help="also write the differences by event number (no text)"
    )
    p.add_argument("--reps", type=int, default=10_000, help="bootstrap resamples")
    p.add_argument("--seed", type=int, default=20261117)
    p.set_defaults(func=cmd_review_score)

    p = sub.add_parser("review-recheck", parents=[common], help="a blind recheck copy")
    p.add_argument("--tables", type=Path, default=Path("data/interim/tables"))
    p.add_argument("--sheets", type=Path, default=Path("data/interim/sheets"))
    p.add_argument("--design", type=Path, default=design)
    p.add_argument("--out", type=Path, default=Path("data/interim/sheets-recheck"))
    p.add_argument("--key", type=Path, default=Path("data/interim/answer-key/recheck_key.json"))
    p.add_argument("--size", type=int, default=30)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--not-before", required=True, help="the first day of the second pass")
    p.set_defaults(func=cmd_review_recheck)

    p = sub.add_parser(
        "old-titles", parents=[common], help="plan views through the old titles of moved pages"
    )
    p.set_defaults(func=cmd_old_titles)

    p = sub.add_parser("classes", parents=[common], help="Wikidata classes of the linked items")
    p.add_argument("--depth", type=int, default=3, help="tiers of classes to label")
    p.set_defaults(func=cmd_classes)

    p = sub.add_parser("api-backfill", parents=[common, span], help="fetch the language views")
    p.add_argument("--max-calls", type=int, help="stop at the chunk boundary after this many")
    p.set_defaults(func=cmd_api_backfill)

    p = sub.add_parser(
        "api-check", parents=[common, span], help="check the saved language views (no requests)"
    )
    p.add_argument("--out", type=Path, help="write the full report, with the indices, as JSON")
    p.set_defaults(func=cmd_api_check)

    p = sub.add_parser("tables", parents=[common, span], help="build the Parquet tables")
    p.add_argument("--out", type=Path, default=Path("data/interim/tables"))
    p.set_defaults(func=cmd_tables)

    p = sub.add_parser("daily", parents=[common], help="the daily update for yesterday")
    p.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    p.set_defaults(func=cmd_daily)
