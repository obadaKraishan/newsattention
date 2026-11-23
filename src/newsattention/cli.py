"""The ``newsattention`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from newsattention import __version__, dpviews, lock
from newsattention.client import DEFAULT_CAPS, Budget, UsageLog, WikimediaClient
from newsattention.validate import validate_file

DEFAULT_LOG = Path("data/usage_log.csv")
#: Seconds between the starts of two requests: about 170 a minute, under the rate at which the
#: Analytics API began answering HTTP 429 (about 200 a minute, 2026-11-13).
MIN_INTERVAL = 0.35


def _client(log: Path, since: str | None, max_bytes: int, command: str) -> WikimediaClient:
    try:
        lock.hold(command)
    except lock.CommandBusy as exc:
        raise SystemExit(str(exc)) from None
    usage = UsageLog(log)
    start = since or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    budget = Budget.from_log(usage.rows(), start, dict(DEFAULT_CAPS), max_bytes)
    return WikimediaClient(usage, budget, min_interval=MIN_INTERVAL)


def cmd_validate(args: argparse.Namespace) -> int:
    status = 0
    files: list[Path] = []
    for name in args.files:
        path = Path(name)
        files.extend(sorted(path.rglob("*.parquet")) if path.is_dir() else [path])
    for path in files:
        try:
            report = validate_file(Path(path), args.table, args.sample)
        except (OSError, ValueError) as exc:
            print(f"{path}: {exc}")
            status = 1
            continue
        if report.ok:
            extra = (
                f", rules checked on a sample of {report.checked_rows:,}"
                if report.checked_rows < report.rows
                else ""
            )
            print(f"{path}: OK ({report.rows} {report.table} rows{extra})")
            continue
        status = 1
        print(f"{path}: {len(report.errors)} problem(s) in {report.rows} {report.table} rows")
        for err in report.errors[: args.max_errors]:
            print(f"  {err}")
        if len(report.errors) > args.max_errors:
            print(f"  ... and {len(report.errors) - args.max_errors} more")
    return status


def cmd_sample(args: argparse.Namespace) -> int:
    from newsattention.pipeline import EN, Sample, days_between

    client = _client(args.log, args.since, args.max_bytes, "sample")
    sample = Sample(
        client, args.out, args.raw, args.start, args.end, args.complete_until or args.end
    )
    events, links = sample.portal()
    pages = sample.resolve(links)
    if "resolve" in args.stop_after:
        return 0
    qids = {p.qid for p in pages if p.qid}
    dp_days = days_between(args.start, min(args.end, args.dp_until or args.end))
    dp_rows = sample.dp(qids, dp_days)
    if "dp" in args.stop_after:
        return 0
    en_titles = {p.qid: p.page_title for p in pages if p.qid}
    other_order = None
    if args.seed is not None:
        # Other languages go to a random sample of events, one whole event at a time.
        import random

        shuffled = [e.event_id for e in events]
        random.Random(args.seed).shuffle(shuffled)
        by_event: dict[str, list[str]] = {}
        for p in sorted(pages, key=lambda p: p.link_order):
            if p.qid:
                by_event.setdefault(p.event_id, []).append(p.qid)
        other_order = [q for eid in shuffled for q in by_event.get(eid, [])]
    plan = sample.titles(
        Sample.plan_api(en_titles, dp_rows, args.api_budget, other_order=other_order)
    )
    (args.out / "api_plan.json").write_text(
        json.dumps(
            {
                "calls": len(plan),
                "english": sum(1 for p in plan if p["project"] == EN),
                "other": sum(1 for p in plan if p["project"] != EN),
                "items_with_other_languages": len({p["qid"] for p in plan if p["project"] != EN}),
                "seed": args.seed,
            }
        )
    )
    if "plan" in args.stop_after:
        print(f"plan: {len(plan)} calls")
        return 0
    from datetime import timedelta

    first = min(e.date for e in events) - timedelta(days=28)
    api_rows = sample.api(plan, first, args.end)
    sample.attention(events, pages, api_rows)
    return 0


def cmd_sizes(args: argparse.Namespace) -> int:
    client = _client(args.log, args.since, args.max_bytes, "sizes")
    out = {}
    for dataset in (dpviews.CURRENT, dpviews.HISTORICAL, dpviews.PRE_2017):
        page = client.get(f"{dpviews.BASE}{dataset}/").text
        entries = dpviews.parse_listing(page)
        days = {e.day for e in entries}
        span = (max(days) - min(days)).days + 1 if days else 0
        out[dataset] = {
            "files": len(entries),
            "first": min(days).isoformat() if days else None,
            "last": max(days).isoformat() if days else None,
            "days_in_span": span,
            "days_without_file": span - len(days),
            "empty_files": sorted(e.day.isoformat() for e in entries if e.approx_bytes == 0),
            "approx_gb": round(sum(e.approx_bytes for e in entries) / 1e9, 2),
            "median_file_mb": round(
                sorted(e.approx_bytes for e in entries)[len(entries) // 2] / 1e6, 1
            )
            if entries
            else None,
        }
    text = json.dumps(out, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newsattention",
        description="Daily news events linked to how many people read about them on Wikipedia.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    val = sub.add_parser("validate", help="check table files against the schema")
    val.add_argument("files", nargs="+", help=".jsonl, .csv or .parquet files, or folders")
    val.add_argument(
        "--table",
        choices=[
            "events",
            "event_pages",
            "views",
            "attention",
            "attention_summary",
            "country_status",
            "pages",
        ],
    )
    val.add_argument(
        "--sample",
        type=int,
        default=20_000,
        help="rows checked against every rule in large Parquet files",
    )
    val.add_argument("--max-errors", type=int, default=20)
    val.set_defaults(func=cmd_validate)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log", type=Path, default=DEFAULT_LOG, help="the request log (CSV)")
    common.add_argument(
        "--since",
        help="count earlier calls in the log from this UTC time on (e.g. 2026-11-13T14:00:00Z)",
    )
    common.add_argument("--max-bytes", type=int, default=1_000_000_000)

    smp = sub.add_parser("sample", parents=[common], help="build a small linked sample")
    smp.add_argument("--start", type=date.fromisoformat, required=True)
    smp.add_argument("--end", type=date.fromisoformat, required=True)
    smp.add_argument("--complete-until", type=date.fromisoformat)
    smp.add_argument("--dp-until", type=date.fromisoformat)
    smp.add_argument("--out", type=Path, required=True)
    smp.add_argument("--raw", type=Path, default=Path("data/raw"))
    smp.add_argument("--api-budget", type=int, default=2800)
    smp.add_argument(
        "--seed", type=int, help="give other languages to a random sample of events (this seed)"
    )
    smp.add_argument("--stop-after", nargs="*", default=[], choices=["resolve", "dp", "plan"])
    smp.set_defaults(func=cmd_sample)

    siz = sub.add_parser("sizes", parents=[common], help="size of a full backfill of the DP files")
    siz.add_argument("--out", type=Path)
    siz.set_defaults(func=cmd_sizes)

    from newsattention import commands, release

    commands.register(sub)
    release.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
