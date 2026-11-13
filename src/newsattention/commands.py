"""Backfill, re-read and daily commands for the ``newsattention`` command line."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from newsattention import backfill
from newsattention.client import Budget, UsageLog, WikimediaClient

DEFAULT_STORE = Path("data/interim/store")
DEFAULT_RAW = Path("data/raw")
DEFAULT_LOG = Path("data/interim/logs/usage.csv")
SPAN_START = date(2023, 1, 9)  # 28 days before 2023-02-06
V1_START = date(2023, 2, 6)


def yesterday() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def make_client(args: argparse.Namespace) -> WikimediaClient:
    """A client whose caps count every request in the log since ``--since``."""
    usage = UsageLog(args.log)
    since = args.since or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    caps: dict[str, int] = {"analytics": args.cap_analytics}
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


def cmd_api_backfill(args: argparse.Namespace) -> int:
    store = store_of(args)
    plan = backfill.read_jsonl(store.root / "api" / "plan.jsonl")
    out = backfill.api_backfill(make_client(args), store, plan, SPAN_START, args.end)
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

    p = sub.add_parser("api-backfill", parents=[common, span], help="fetch the language views")
    p.set_defaults(func=cmd_api_backfill)
