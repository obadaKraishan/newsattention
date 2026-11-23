"""The release pack: a version's files, built from the local tables, and its own check.

A pack holds the nine tables as Parquet files (the large ones one file per month), a
``manifest.json`` (every file's rows, bytes and SHA-256, each table's license and the date
each source was read), a ``LICENSES.md`` (which license applies to which table and column) and
the dataset card ``README.md``.

The build leaves out the columns that do not ship (the roles, ``role`` and
``role_confidence``: see :data:`LEFT_OUT`) and every row the removal list names
(:func:`read_removals`). It never fills in, estimates or edits a value: each kept row is the
local table's row.

:func:`check_pack` reads the pack's own folder and fails, loudly, on a ``role`` or
``role_confidence`` column, a file that is not in the manifest (or differs from it), a table
without its license, event text in a CC0 table, a country row written as a zero (or below the
smallest published count), a row the removal list names, and a card or ``LICENSES.md`` with a
raw HTML tag or the wrong configurations.

:func:`build_kaggle` writes the Kaggle mirror's folder from a pack: the same tables, one file
each (the Kaggle command line uploads the files of one folder, not subfolders), with
``dataset-metadata.json`` and a cover drawn by code.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from newsattention import __version__, hfpage, tables
from newsattention.schema import DP_MIN_RELEASED, EVENT_ID_RE, QID_RE

CC0 = "CC0-1.0"
CC_BY_SA = "CC-BY-SA-4.0"
LICENSE_NAMES = {
    CC0: "CC0 1.0 Universal (public domain dedication)",
    CC_BY_SA: "Creative Commons Attribution-ShareAlike 4.0 International",
}
LICENSE_URLS = {
    CC0: "https://creativecommons.org/publicdomain/zero/1.0/",
    CC_BY_SA: "https://creativecommons.org/licenses/by-sa/4.0/",
}
#: The Hub's identifiers of the two licenses (the card's ``license`` list).
HUB_LICENSES = {CC0: "cc0-1.0", CC_BY_SA: "cc-by-sa-4.0"}
CREDIT = (
    "Event text from Wikipedia's Current Events Portal, by Wikipedia contributors, CC BY-SA 4.0 "
    "(https://creativecommons.org/licenses/by-sa/4.0/). Changed: wiki markup removed and the "
    "text split into one row per event."
)
DATASET = "obadakr/newsattention"
REPO_URL = "https://github.com/obadaKraishan/newsattention"


@dataclass(frozen=True)
class TableSpec:
    """A released table: its source schema, its files, what a row is, and its license."""

    name: str
    schema: pa.Schema
    monthly: bool
    row: str
    license: str


#: The released tables, in the card's order.
TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "events",
        tables.EVENTS_SCHEMA,
        True,
        "event on a portal day page: its date, category and text, the portal page and the "
        "revision read, the story headings above it and the news sites it cites",
        CC_BY_SA,
    ),
    TableSpec(
        "event_pages",
        tables.EVENT_PAGES_SCHEMA,
        True,
        "event and linked English article: the article's Wikidata item, page id and title, "
        "the link's order, whether the event's own text links it, and the story heading level",
        CC0,
    ),
    TableSpec(
        "pages",
        tables.PAGES_SCHEMA,
        False,
        "linked English article: its estimated creation date and its moves inside the span, "
        "with the old titles and the move dates",
        CC0,
    ),
    TableSpec(
        "views_api",
        tables.VIEWS_SCHEMA,
        True,
        "item (or article with no item), language edition and day: exact daily views; inside "
        "a series' fetched days, a day without a row had no views",
        CC0,
    ),
    TableSpec(
        "series",
        tables.SERIES_SCHEMA,
        False,
        "item (or article with no item) and language edition: the first and last day "
        "fetched, and whether older titles of a moved page are joined in",
        CC0,
    ),
    TableSpec(
        "views_dp",
        tables.VIEWS_SCHEMA,
        True,
        "item, language edition, country and day: Wikimedia's published, privacy-protected "
        "count; a missing row is not a zero",
        CC0,
    ),
    TableSpec(
        "attention",
        tables.ATTENTION_SCHEMA,
        True,
        "event, item, language edition and day 0 to 28: the views, the baseline and the lift",
        CC0,
    ),
    TableSpec(
        "attention_summary",
        tables.SUMMARY_SCHEMA,
        True,
        "event, item and language edition: the measures (baseline, lift, excess views, peak, "
        "half-life, breadth)",
        CC0,
    ),
    TableSpec(
        "country_status",
        tables.COUNTRY_SCHEMA,
        True,
        "event, item, language edition and country: the country status and, for tracked "
        "countries, the baseline and the lift",
        CC0,
    ),
)
SPECS = {t.name: t for t in TABLES}
#: Columns of the local tables that do not ship, and why.
LEFT_OUT: dict[str, tuple[str, ...]] = {"event_pages": ("role", "role_confidence")}
FORBIDDEN_COLUMNS = ("role", "role_confidence")
#: Columns that hold the portal's own words; a CC0 table never has one.
EVENT_TEXT_COLUMNS = ("text", "category", "story_titles", "source_domains")
#: The longest title MediaWiki allows is 255 bytes; any longer string in a CC0 table is text.
MAX_CC0_STRING = 255
#: Files of a pack besides the tables.
PACK_FILES = ("README.md", "LICENSES.md", "manifest.json")
#: Size categories of the Hub's card metadata, by total rows.
SIZE_CATEGORIES = (
    (1_000, "n<1K"),
    (10_000, "1K<n<10K"),
    (100_000, "10K<n<100K"),
    (1_000_000, "100K<n<1M"),
    (10_000_000, "1M<n<10M"),
    (100_000_000, "10M<n<100M"),
    (1_000_000_000, "100M<n<1B"),
    (10_000_000_000, "1B<n<10B"),
)
DEFAULT_CONFIG = "events"


def release_schema(spec: TableSpec) -> pa.Schema:
    """The table's released columns: its source schema without the columns left out."""
    drop = set(LEFT_OUT.get(spec.name, ()))
    return pa.schema([f for f in spec.schema if f.name not in drop])


def size_category(rows: int) -> str:
    for limit, name in SIZE_CATEGORIES:
        if rows < limit:
            return name
    return "n>10B"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --- the removal list -------------------------------------------------------------------------

REMOVAL_FIELDS = ("kind", "id", "received", "issue", "reason")


class Removal(BaseModel):
    """One entry of the removal list: rows the build leaves out of every release from now on.

    - ``event``: an event id; the event and its links, views of it and measures go.
    - ``item``: a Wikidata id; every row of the item goes (links, pages, views, measures).
    - ``page``: an English page id; every row of the article goes. Give its item as well when
      the article has one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["event", "item", "page"]
    id: str
    received: date
    issue: int | None = Field(default=None, ge=1)
    reason: Literal["privacy", "copyright", "error", "other"]

    @field_validator("id")
    @classmethod
    def _id(cls, value: str, info: Any) -> str:
        kind = info.data.get("kind")
        if kind == "event" and not EVENT_ID_RE.match(value):
            raise ValueError("an event id looks like 2026-11-01-0123abcd")
        if kind == "item" and not QID_RE.match(value):
            raise ValueError("a Wikidata id looks like Q42")
        if kind == "page" and not value.isdigit():
            raise ValueError("a page id is a whole number")
        return value


class RemovalListError(ValueError):
    """The removal list cannot be read; the message names the file, line and field."""


def read_removals(path: Path | str | None) -> list[Removal]:
    """The removal list (CSV with the header ``kind,id,received,issue,reason``)."""
    if path is None:
        return []
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != REMOVAL_FIELDS:
            raise RemovalListError(
                f"{path} line 1: the header must be {','.join(REMOVAL_FIELDS)}; "
                f"it is {','.join(reader.fieldnames or [])!r}."
            )
        out = []
        for n, row in enumerate(reader, 2):
            clean = {k: (v.strip() if v else None) for k, v in row.items()}
            if not clean["issue"]:
                clean["issue"] = None
            try:
                out.append(Removal(**clean))
            except ValidationError as exc:
                err = exc.errors()[0]
                field = ".".join(str(p) for p in err["loc"]) or "row"
                raise RemovalListError(
                    f"{path} line {n}, field {field}: {err['msg']}. Fix the entry and build again."
                ) from exc
    return out


def removal_sets(removals: Iterable[Removal]) -> dict[str, set[Any]]:
    sets: dict[str, set[Any]] = {"event": set(), "item": set(), "page": set()}
    for r in removals:
        sets[r.kind].add(int(r.id) if r.kind == "page" else r.id)
    return sets


#: Which column of which table each kind of removal reads.
REMOVAL_COLUMNS = {
    "event": "event_id",
    "item": "qid",
    "page": "page_id",
}


def apply_removals(table: pa.Table, sets: Mapping[str, set[Any]]) -> pa.Table:
    """The table without the rows the removal list names (by the columns it has)."""
    mask = None
    for kind, column in REMOVAL_COLUMNS.items():
        values = sets.get(kind)
        if not values or column not in table.column_names:
            continue
        typ = table.schema.field(column).type
        hit = pc.is_in(table[column], value_set=pa.array(sorted(values), type=typ))
        hit = pc.fill_null(hit, False)
        mask = hit if mask is None else pc.or_(mask, hit)
    if mask is None:
        return table
    return table.filter(pc.invert(mask))


# --- source dates -----------------------------------------------------------------------------


def _span(values: Iterable[str]) -> dict[str, str] | None:
    days = sorted(v[:10] for v in values if v)
    return {"first": days[0], "last": days[-1]} if days else None


def source_dates(store_root: Path, logs: Iterable[Path]) -> dict[str, dict[str, str] | None]:
    """The first and last day each source was read, from the store and the request logs."""
    portal: list[str] = []
    for line in (store_root / "portal" / "revisions.jsonl").read_text().splitlines():
        if line.strip():
            portal.append(json.loads(line)["read_at"])
    analytics: list[str] = []
    country: list[str] = []
    action: list[str] = []
    for log in logs:
        if not log.exists():
            continue
        with log.open(newline="") as f:
            for row in csv.DictReader(f):
                if row["status"] != "200":
                    continue
                host, path = row["host"], row["path"]
                if host == "wikimedia.org" and "/metrics/pageviews/per-article/" in path:
                    analytics.append(row["time"])
                elif host == "analytics.wikimedia.org" and "country_project_page/" in path:
                    if path.rstrip("/").endswith(("tsv", "bz2", "gz")):
                        country.append(row["time"])
                elif host.endswith(".wikipedia.org") and path == "/w/api.php":
                    action.append(row["time"])
    return {
        "portal": _span(portal),
        "mediawiki_api": _span(action),
        "analytics_api": _span(analytics),
        "country_files": _span(country),
    }


# --- the build --------------------------------------------------------------------------------


def _files_of(tables_dir: Path, spec: TableSpec) -> list[Path]:
    if spec.monthly:
        files = sorted((tables_dir / spec.name).glob("*.parquet"))
    else:
        files = [tables_dir / f"{spec.name}.parquet"]
    missing = [f for f in files if not f.exists()]
    if missing or not files:
        raise FileNotFoundError(
            f"{tables_dir}: no files for the table {spec.name!r}; build the tables first "
            "(newsattention tables)."
        )
    return files


def _metadata(spec: TableSpec, version: str) -> dict[bytes, bytes]:
    meta = {
        b"newsattention.table": spec.name.encode(),
        b"newsattention.license": spec.license.encode(),
        b"newsattention.version": version.encode(),
    }
    if spec.license == CC_BY_SA:
        meta[b"newsattention.credit"] = CREDIT.encode()
    return meta


def _pack_path(spec: TableSpec, source: Path) -> str:
    return f"{spec.name}/{source.stem if spec.monthly else spec.name}.parquet"


def build_pack(
    tables_dir: Path | str,
    out_dir: Path | str,
    version: str,
    *,
    removals: Path | str | None = None,
    store_root: Path | str | None = None,
    logs: Iterable[Path | str] = (),
    code_commit: str | None = None,
    built_at: datetime | None = None,
) -> dict[str, Any]:
    """Write the pack into ``out_dir`` (which must not exist yet) and return its manifest."""
    tables_dir, out_dir = Path(tables_dir), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(
            f"{out_dir} already holds files; move it aside (a pack is written once) and build "
            "again."
        )
    entries = read_removals(removals)
    sets = removal_sets(entries)
    built = (built_at or datetime.now(timezone.utc)).replace(microsecond=0)
    files: list[dict[str, Any]] = []
    removed: Counter[str] = Counter()
    for spec in TABLES:
        schema = release_schema(spec).with_metadata(_metadata(spec, version))
        for source in _files_of(tables_dir, spec):
            table = pq.read_table(source)
            missing = [n for n in schema.names if n not in table.column_names]
            if missing:
                raise ValueError(
                    f"{source}: the columns {missing} are missing; rebuild the tables with this "
                    "version of the code."
                )
            before = table.num_rows
            table = apply_removals(table.select(schema.names), sets).cast(schema)
            removed[spec.name] += before - table.num_rows
            rel = _pack_path(spec, source)
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, target, compression="zstd")
            files.append(
                {
                    "path": rel,
                    "table": spec.name,
                    "rows": table.num_rows,
                    "bytes": target.stat().st_size,
                    "sha256": sha256(target),
                    "license": spec.license,
                }
            )
    facts = pack_facts(out_dir, files)
    manifest = {
        "name": "newsattention",
        "dataset": DATASET,
        "version": version,
        "built_at": built.isoformat().replace("+00:00", "Z"),
        "code": {"version": __version__, "commit": code_commit, "repository": REPO_URL},
        "span": {
            "first_event_day": facts["first_event_day"],
            "last_event_day": facts["last_event_day"],
            "views_from": facts["views_from"],
            "views_to": facts["views_to"],
        },
        "sources": source_dates(Path(store_root), [Path(p) for p in logs])
        if store_root is not None
        else {},
        "tables": {
            spec.name: {
                "license": spec.license,
                "row": spec.row,
                "files": sum(1 for f in files if f["table"] == spec.name),
                "rows": sum(f["rows"] for f in files if f["table"] == spec.name),
                "bytes": sum(f["bytes"] for f in files if f["table"] == spec.name),
                "columns": release_schema(spec).names,
            }
            for spec in TABLES
        },
        "left_out": {
            "columns": {k: list(v) for k, v in LEFT_OUT.items()},
            "why": (
                "The roles (which linked article is the event's own article, which the larger "
                "story) come from a rule that scored below its target on a hand-checked "
                "sample; they stay out until a later rule passes."
            ),
        },
        "removals": {"entries": len(entries), "rows_left_out": dict(removed)},
        "facts": facts,
        "rows": sum(f["rows"] for f in files),
        "bytes": sum(f["bytes"] for f in files),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out_dir / "LICENSES.md").write_text(licenses_text(manifest))
    (out_dir / "README.md").write_text(card(manifest))
    return manifest


def _distinct(paths: Iterable[Path], column: str) -> set[Any]:
    out: set[Any] = set()
    for p in paths:
        col = pq.read_table(p, columns=[column])[column]
        out.update(v for v in pc.unique(col).to_pylist() if v not in (None, ""))
    return out


def pack_facts(pack: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the card, read from the pack's own files."""

    def paths(name: str) -> list[Path]:
        return [pack / f["path"] for f in files if f["table"] == name]

    def date_range(name: str, column: str) -> tuple[str, str]:
        lo, hi = None, None
        for p in paths(name):
            col = pq.read_table(p, columns=[column])[column]
            if len(col) == 0:
                continue
            mm = pc.min_max(col).as_py()
            lo = mm["min"] if lo is None else min(lo, mm["min"])
            hi = mm["max"] if hi is None else max(hi, mm["max"])
        return (lo.isoformat() if lo else "", hi.isoformat() if hi else "")

    first_day, last_day = date_range("events", "date")
    views_from, views_to = date_range("views_api", "date")
    status: Counter[str] = Counter()
    for p in paths("country_status"):
        col = pq.read_table(p, columns=["country_status"])["country_status"]
        for v, n in zip(*pc.value_counts(col).flatten(), strict=True):
            status[v.as_py()] += n.as_py()
    ep = pa.concat_tables(
        pq.read_table(p, columns=["qid", "page_id"]) for p in paths("event_pages")
    )
    no_item = pc.and_(pc.is_null(ep["qid"]), pc.is_valid(ep["page_id"]))
    pages = pq.read_table(paths("pages")[0], columns=["moves_in_span"])
    return {
        "first_event_day": first_day,
        "last_event_day": last_day,
        "views_from": views_from,
        "views_to": views_to,
        "events": sum(f["rows"] for f in files if f["table"] == "events"),
        "event_days": len(_distinct(paths("events"), "date")),
        "items": len({q for q in ep["qid"].to_pylist() if q}),
        "articles_without_item": len(set(pc.filter(ep["page_id"], no_item).to_pylist())),
        "moved_pages": int(pc.sum(pc.greater(pages["moves_in_span"], 0)).as_py() or 0),
        "languages": len(_distinct(paths("series"), "project")),
        "countries": len(_distinct(paths("views_dp"), "country")),
        "country_status": dict(sorted(status.items())),
    }


# --- the card and LICENSES.md -----------------------------------------------------------------

_SLOT = re.compile(r"\{\{([a-z_]+)\}\}")


def fill(template: str, values: Mapping[str, Any]) -> str:
    """Replace every ``{{name}}``; a name without a value is an error, never left in."""
    missing = sorted({m.group(1) for m in _SLOT.finditer(template)} - set(values))
    if missing:
        raise KeyError(f"the template needs values for {missing}")
    return _SLOT.sub(lambda m: str(values[m.group(1)]), template)


def _template(name: str) -> str:
    return resources.files("newsattention").joinpath(name).read_text(encoding="utf-8")


def _mb(n: int) -> str:
    return f"{n / 1e6:,.1f} MB"


def front_matter(manifest: Mapping[str, Any]) -> str:
    lines = [
        "---",
        "license:",
        f"- {HUB_LICENSES[CC0]}",
        f"- {HUB_LICENSES[CC_BY_SA]}",
        "pretty_name: NewsAttention",
        "language:",
        "- en",
        "tags:",
        "- news",
        "- wikipedia",
        "- pageviews",
        "- public-attention",
        "- journalism",
        "- communication",
        "- differential-privacy",
        "- time-series",
        "size_categories:",
        f"- {size_category(int(manifest['rows']))}",
        "configs:",
    ]
    for spec in TABLES:
        lines.append(f"- config_name: {spec.name}")
        if spec.name == DEFAULT_CONFIG:
            lines.append("  default: true")
        lines += ["  data_files:", "  - split: train", f"    path: {spec.name}/*.parquet"]
    lines.append("---")
    return "\n".join(lines) + "\n"


def tables_markdown(manifest: Mapping[str, Any]) -> str:
    rows = [
        "| Table | One row per | Rows | Files | Size | License |",
        "|---|---|---:|---:|---:|---|",
    ]
    for spec in TABLES:
        t = manifest["tables"][spec.name]
        rows.append(
            f"| `{spec.name}` | {spec.row} | {t['rows']:,} | {t['files']} | {_mb(t['bytes'])} "
            f"| {LICENSE_NAMES[spec.license].split(' (')[0]} |"
        )
    rows.append(
        f"| **all** | | **{manifest['rows']:,}** | **{len(manifest['files'])}** | "
        f"**{_mb(manifest['bytes'])}** | |"
    )
    return "\n".join(rows)


def _read(manifest: Mapping[str, Any], source: str) -> str:
    s = (manifest.get("sources") or {}).get(source)
    if not s:
        return "dates not recorded"
    return s["first"] if s["first"] == s["last"] else f"{s['first']} to {s['last']}"


def card_values(manifest: Mapping[str, Any]) -> dict[str, Any]:
    f = manifest["facts"]
    status = f["country_status"]
    total_status = sum(status.values()) or 1
    return {
        "version": manifest["version"],
        "built": manifest["built_at"][:10],
        "first_day": f["first_event_day"],
        "last_day": f["last_event_day"],
        "views_from": f["views_from"],
        "views_to": f["views_to"],
        "events": f"{f['events']:,}",
        "event_days": f"{f['event_days']:,}",
        "items": f"{f['items']:,}",
        "articles_without_item": f"{f['articles_without_item']:,}",
        "moved_pages": f"{f['moved_pages']:,}",
        "languages": f"{f['languages']:,}",
        "countries": f"{f['countries']:,}",
        "status_shares": ", ".join(
            f"`{k}` {100 * v / total_status:.1f}%"
            for k, v in sorted(status.items(), key=lambda kv: -kv[1])
        ),
        "tables_table": tables_markdown(manifest),
        "read_portal": _read(manifest, "portal"),
        "read_mediawiki": _read(manifest, "mediawiki_api"),
        "read_analytics": _read(manifest, "analytics_api"),
        "read_country": _read(manifest, "country_files"),
        "credit": CREDIT,
        "dataset": DATASET,
        "repo": REPO_URL,
        "removal_entries": manifest["removals"]["entries"],
    }


def card(manifest: Mapping[str, Any]) -> str:
    """The dataset card: the Hub's metadata, then the card text with the pack's numbers."""
    return front_matter(manifest) + fill(_template("dataset_card.md"), card_values(manifest))


def licenses_text(manifest: Mapping[str, Any]) -> str:
    """LICENSES.md: which license applies to which table and column."""
    rows = ["| Table | Columns | License |", "|---|---|---|"]
    for spec in TABLES:
        cols = ", ".join(f"`{c}`" for c in manifest["tables"][spec.name]["columns"])
        rows.append(f"| `{spec.name}` | {cols} | {LICENSE_NAMES[spec.license]} |")
    values = card_values(manifest) | {"licenses_table": "\n".join(rows)}
    return fill(_template("licenses_pack.md"), values)


# --- the check --------------------------------------------------------------------------------


def _string_columns(table: pa.Table) -> Iterable[tuple[str, pa.ChunkedArray]]:
    for field in table.schema:
        col = table[field.name]
        if pa.types.is_string(field.type) or pa.types.is_large_string(field.type):
            yield field.name, col
        elif pa.types.is_list(field.type) and pa.types.is_string(field.type.value_type):
            yield field.name, pc.list_flatten(col)


def card_metadata_problems(text: str) -> list[str]:
    """The card's front matter must name both licenses and every table, in order."""
    problems = []
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return ["README.md: no metadata block at the top (--- ... ---)"]
    meta = m.group(1)
    for lic in HUB_LICENSES.values():
        if f"- {lic}" not in meta:
            problems.append(f"README.md: the metadata does not list the license {lic}")
    names = re.findall(r"^- config_name: (\S+)$", meta, re.M)
    want = [t.name for t in TABLES]
    if names != want:
        problems.append(f"README.md: the configurations are {names}; the tables are {want}")
    for spec in TABLES:
        if f"path: {spec.name}/*.parquet" not in meta:
            problems.append(f"README.md: the configuration {spec.name} does not read its files")
    return problems


def check_pack(pack_dir: Path | str, removals: Path | str | None = None) -> list[str]:
    """Every problem of the pack in ``pack_dir``; an empty list means it may be uploaded."""
    pack = Path(pack_dir)
    problems: list[str] = []
    mpath = pack / "manifest.json"
    if not mpath.exists():
        return [f"{pack}: no manifest.json; build the pack with `newsattention release build`."]
    manifest = json.loads(mpath.read_text())
    listed = {f["path"]: f for f in manifest.get("files", [])}

    # Files: every file listed, nothing else, and each as the manifest says.
    on_disk = sorted(p.relative_to(pack).as_posix() for p in pack.rglob("*") if p.is_file())
    for rel in on_disk:
        if rel not in listed and rel not in PACK_FILES:
            problems.append(f"{rel}: not in the manifest; a pack holds only listed files.")
    for name in PACK_FILES:
        if not (pack / name).exists():
            problems.append(f"{name}: missing from the pack.")
    differs: set[str] = set()
    for rel, entry in listed.items():
        path = pack / rel
        if not path.exists():
            problems.append(f"{rel}: listed in the manifest but missing.")
            continue
        if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            problems.append(f"{rel}: its size or SHA-256 differs from the manifest.")
            differs.add(rel)

    # Tables and licenses. The events' text first, so the CC0 tables can be checked against it.
    sets = removal_sets(read_removals(removals))
    texts: set[str] = set()
    for rel, entry in listed.items():
        if entry.get("table") == "events" and (pack / rel).exists() and rel not in differs:
            col = pq.read_table(pack / rel, columns=["text"])["text"]
            texts.update(t for t in col.to_pylist() if t)
    text_set = pa.array(sorted(texts), type=pa.string())
    for rel, entry in sorted(listed.items()):
        path = pack / rel
        if not path.exists() or rel in differs:
            continue  # already reported; a changed file may not even be Parquet
        spec = SPECS.get(entry.get("table", ""))
        if spec is None:
            problems.append(f"{rel}: the table {entry.get('table')!r} is not a released table.")
            continue
        pf = pq.ParquetFile(path)
        meta = pf.schema_arrow.metadata or {}
        names = pf.schema_arrow.names
        for col in FORBIDDEN_COLUMNS:
            if col in names:
                problems.append(f"{rel}: has the column {col!r}; the roles do not ship.")
        if names != release_schema(spec).names:
            problems.append(f"{rel}: the columns {names} are not the release's columns.")
        lic = meta.get(b"newsattention.license", b"").decode()
        if not lic:
            problems.append(f"{rel}: the file names no license (newsattention.license).")
        elif lic != spec.license or entry.get("license") != spec.license:
            problems.append(f"{rel}: license {lic!r}; the table {spec.name} is {spec.license}.")
        if pf.metadata.num_rows != entry["rows"]:
            problems.append(
                f"{rel}: {pf.metadata.num_rows} rows, the manifest says {entry['rows']}."
            )
        if spec.name == "events" and meta.get(b"newsattention.credit", b"").decode() != CREDIT:
            problems.append(f"{rel}: the event text's credit line is missing or changed.")
        table = pf.read()
        if spec.license == CC0:
            problems += _cc0_problems(rel, table, text_set)
        problems += _zero_problems(rel, spec.name, table)
        left = table.num_rows - apply_removals(table, sets).num_rows
        if left:
            problems.append(f"{rel}: {left} rows the removal list names are still in it.")
    for spec in TABLES:
        t = manifest.get("tables", {}).get(spec.name, {})
        if t.get("license") != spec.license:
            problems.append(f"manifest.json: the table {spec.name} has no license or another.")
    for spec in TABLES:
        if not any(f["table"] == spec.name for f in listed.values()):
            problems.append(f"manifest.json: no file of the table {spec.name}.")

    # The card and LICENSES.md.
    for name in ("README.md", "LICENSES.md"):
        path = pack / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            problems += hfpage.tag_problems(name, text)
            if "{{" in text:
                problems.append(f"{name}: a template slot was left unfilled.")
    if (pack / "README.md").exists():
        problems += card_metadata_problems((pack / "README.md").read_text(encoding="utf-8"))
    if (pack / "LICENSES.md").exists():
        lic_text = (pack / "LICENSES.md").read_text(encoding="utf-8")
        for spec in TABLES:
            if f"| `{spec.name}` |" not in lic_text:
                problems.append(f"LICENSES.md: the table {spec.name} has no license line.")
    return problems


def _cc0_problems(rel: str, table: pa.Table, texts: pa.Array) -> list[str]:
    out = []
    for col in EVENT_TEXT_COLUMNS:
        if col in table.column_names:
            out.append(f"{rel}: a CC0 table has the event-text column {col!r}.")
    for name, col in _string_columns(table):
        if len(col) == 0:
            continue
        longest = pc.max(pc.utf8_length(col)).as_py() or 0
        if longest > MAX_CC0_STRING:
            out.append(
                f"{rel}: column {name!r} holds a string of {longest} characters; a CC0 table "
                "holds ids and titles only, never event text."
            )
        if len(texts):
            hit = pc.is_in(pc.unique(col), value_set=texts)
            if pc.any(hit).as_py():
                out.append(f"{rel}: column {name!r} holds an event's text; it is CC BY-SA 4.0.")
    return out


def _zero_problems(rel: str, name: str, table: pa.Table) -> list[str]:
    """A country row is a published count: never zero, never below the smallest published."""
    out = []
    if name == "views_dp":
        views = table["views"]
        if views.null_count:
            out.append(f"{rel}: {views.null_count} country rows have no count.")
        low = pc.sum(pc.less(views, DP_MIN_RELEASED)).as_py() or 0
        if low:
            out.append(
                f"{rel}: {low} country rows are below {DP_MIN_RELEASED} (a zero or a filled "
                "row); Wikimedia publishes no such count."
            )
        if not pc.all(table["noisy"]).as_py() or set(pc.unique(table["source"]).to_pylist()) - {
            "dp"
        }:
            out.append(f"{rel}: a country row is not marked as Wikimedia's noisy count.")
    if name == "country_status":
        for col in ("views_day0", "views_day1", "baseline_median"):
            low = pc.sum(pc.less(table[col], DP_MIN_RELEASED)).as_py() or 0
            if low:
                out.append(
                    f"{rel}: {low} rows have {col} below {DP_MIN_RELEASED}; a day without a "
                    "published row is empty, never a zero."
                )
    if name == "attention":
        dp = pc.equal(table["source"], "dp")
        if pc.any(dp).as_py():
            out.append(f"{rel}: country rows in attention; country counts live in views_dp.")
    return out


# --- the Kaggle mirror ------------------------------------------------------------------------

KAGGLE_ID = "obadakraishan/newsattention"
KAGGLE_TITLE = "NewsAttention: News Events and Wikipedia Views"
KAGGLE_SUBTITLE = "Daily news events linked to Wikipedia page views by language and by country"
KAGGLE_TITLE_LIMITS = (6, 50)
KAGGLE_SUBTITLE_LIMITS = (20, 80)
#: Kaggle takes one license for a dataset. The event text is CC BY-SA 4.0 and CC0 material can
#: be shared under it, so CC BY-SA 4.0 is the one license that is true of every file; the CC0
#: tables stay CC0 (LICENSES.md, in the mirror too, says so per table).
KAGGLE_LICENSE = "CC-BY-SA-4.0"
#: Tags Kaggle is known to accept. An unknown tag makes Kaggle refuse
#: the whole metadata update, so a tag is added here only once Kaggle has shown it accepts it.
KAGGLE_KEYWORDS = ("news",)
KAGGLE_UPDATE_FREQUENCY = "not specified"
KAGGLE_COVER = "dataset-cover-image.png"
KAGGLE_SOURCES = (
    "- **Events:** English Wikipedia's Current Events Portal "
    "(https://en.wikipedia.org/wiki/Portal:Current_events), day pages read through the "
    "MediaWiki Action API with the revision read; CC BY-SA 4.0, by Wikipedia contributors.\n"
    "- **Language views:** the Wikimedia Analytics API, per-article daily page views "
    "(https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/); CC0 1.0.\n"
    "- **Country views:** Wikimedia's differentially private daily page views by country "
    "(https://analytics.wikimedia.org/published/datasets/country_project_page/), used as "
    "published; CC0 1.0.\n"
    "- **Articles:** page ids, redirects, Wikidata ids, creation estimates and the move log "
    "through the MediaWiki Action API of English Wikipedia."
)


def kaggle_files_markdown(files: list[dict[str, Any]]) -> str:
    rows = ["| File | One row per | Rows | Size | License |", "|---|---|---:|---:|---|"]
    for f in files:
        spec = SPECS[f["table"]]
        rows.append(
            f"| `{f['path']}` | {spec.row} | {f['rows']:,} | {_mb(f['bytes'])} "
            f"| {LICENSE_NAMES[spec.license].split(' (')[0]} |"
        )
    return "\n".join(rows)


def kaggle_description(manifest: Mapping[str, Any], files: list[dict[str, Any]]) -> str:
    values = card_values(manifest) | {"tables_table": kaggle_files_markdown(files)}
    return fill(_template("kaggle_description.md"), values)


def build_kaggle(pack_dir: Path | str, out_dir: Path | str) -> dict[str, Any]:
    """The Kaggle folder: one Parquet file per table, LICENSES.md, a manifest, the metadata."""
    from newsattention import cover

    pack, out = Path(pack_dir), Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} already holds files; move it aside and build again.")
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((pack / "manifest.json").read_text())
    files = []
    for spec in TABLES:
        parts = [pack / f["path"] for f in manifest["files"] if f["table"] == spec.name]
        target = out / f"{spec.name}.parquet"
        schema = pq.read_schema(parts[0])
        rows = 0
        with pq.ParquetWriter(target, schema, compression="zstd") as writer:
            for p in parts:
                t = pq.read_table(p)
                writer.write_table(t)
                rows += t.num_rows
        files.append(
            {
                "path": target.name,
                "table": spec.name,
                "rows": rows,
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
                "license": spec.license,
            }
        )
    shutil.copyfile(pack / "LICENSES.md", out / "LICENSES.md")
    kaggle_manifest = {
        **{k: v for k, v in manifest.items() if k != "files"},
        "mirror_of": {"dataset": DATASET, "manifest_sha256": sha256(pack / "manifest.json")},
        "files": files,
        "bytes": sum(f["bytes"] for f in files),
    }
    (out / "manifest.json").write_text(json.dumps(kaggle_manifest, indent=2) + "\n")
    cover.write_png(out / KAGGLE_COVER)
    resources_ = [
        {"path": f["path"], "description": f"One row per {SPECS[f['table']].row}."} for f in files
    ] + [
        {"path": "LICENSES.md", "description": "Which license applies to which table and column."},
        {
            "path": "manifest.json",
            "description": "Every file with its rows, size and SHA-256, and when each source "
            "was read.",
        },
    ]
    meta = {
        "title": KAGGLE_TITLE,
        "id": KAGGLE_ID,
        "subtitle": KAGGLE_SUBTITLE,
        "description": kaggle_description(manifest, files),
        "isPrivate": True,
        "licenses": [{"name": KAGGLE_LICENSE}],
        "keywords": list(KAGGLE_KEYWORDS),
        "expectedUpdateFrequency": KAGGLE_UPDATE_FREQUENCY,
        "userSpecifiedSources": KAGGLE_SOURCES,
        "resources": resources_,
    }
    (out / "dataset-metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    return kaggle_manifest


def kaggle_metadata_problems(meta: Mapping[str, Any]) -> list[str]:
    out = []
    lo, hi = KAGGLE_TITLE_LIMITS
    if not lo <= len(meta.get("title", "")) <= hi:
        out.append(f"Kaggle title: {len(meta.get('title', ''))} characters, not {lo} to {hi}.")
    lo, hi = KAGGLE_SUBTITLE_LIMITS
    if not lo <= len(meta.get("subtitle", "")) <= hi:
        out.append(
            f"Kaggle subtitle: {len(meta.get('subtitle', ''))} characters, not {lo} to {hi}."
        )
    unknown = [k for k in meta.get("keywords", []) if k not in KAGGLE_KEYWORDS]
    if unknown:
        out.append(f"Kaggle keywords {unknown} are not on the accepted list; Kaggle would refuse.")
    if [x.get("name") for x in meta.get("licenses", [])] != [KAGGLE_LICENSE]:
        out.append(f"Kaggle takes one license: {KAGGLE_LICENSE}.")
    if meta.get("expectedUpdateFrequency") != KAGGLE_UPDATE_FREQUENCY:
        out.append("Kaggle update frequency: 'not specified' until the automatic update runs.")
    desc = meta.get("description", "")
    if "## How to cite" not in desc:
        out.append("Kaggle description: no 'How to cite' heading.")
    out += hfpage.tag_problems("Kaggle description", desc)
    return out


def check_kaggle(kaggle_dir: Path | str, pack_dir: Path | str) -> list[str]:
    """The Kaggle folder against its pack: the same tables and rows, the metadata, the cover."""
    from newsattention import cover

    k, pack = Path(kaggle_dir), Path(pack_dir)
    out: list[str] = []
    mpath, meta_path = k / "manifest.json", k / "dataset-metadata.json"
    if not mpath.exists() or not meta_path.exists():
        return [
            f"{k}: no manifest.json or dataset-metadata.json; run `newsattention release kaggle`."
        ]
    km = json.loads(mpath.read_text())
    pm = json.loads((pack / "manifest.json").read_text())
    if km.get("mirror_of", {}).get("manifest_sha256") != sha256(pack / "manifest.json"):
        out.append("Kaggle folder: built from another pack (the manifest's hash differs).")
    allowed = {f["path"] for f in km["files"]} | {
        "LICENSES.md",
        "manifest.json",
        "dataset-metadata.json",
        KAGGLE_COVER,
    }
    for p in sorted(k.iterdir()):
        if p.name not in allowed:
            out.append(f"Kaggle folder: {p.name} is not in its manifest.")
        if p.is_dir():
            out.append(f"Kaggle folder: {p.name} is a folder; the Kaggle CLI skips folders.")
    for f in km["files"]:
        path = k / f["path"]
        if not path.exists() or sha256(path) != f["sha256"]:
            out.append(f"Kaggle folder: {f['path']} is missing or differs from its manifest.")
            continue
        names = pq.read_schema(path).names
        for col in FORBIDDEN_COLUMNS:
            if col in names:
                out.append(f"Kaggle folder: {f['path']} has the column {col!r}.")
        want = pm["tables"][f["table"]]["rows"]
        if f["rows"] != want:
            out.append(f"Kaggle folder: {f['path']} has {f['rows']:,} rows, the pack {want:,}.")
    if {f["table"] for f in km["files"]} != set(SPECS):
        out.append("Kaggle folder: not every table is in it.")
    if (k / "LICENSES.md").read_bytes() != (pack / "LICENSES.md").read_bytes():
        out.append("Kaggle folder: LICENSES.md differs from the pack's.")
    out += kaggle_metadata_problems(json.loads(meta_path.read_text()))
    cov = k / KAGGLE_COVER
    if not cov.exists():
        out.append("Kaggle folder: no cover image.")
    elif cover.png_size(cov) != (cover.WIDTH, cover.HEIGHT):
        out.append(f"Kaggle folder: the cover is {cover.png_size(cov)}, not 560 by 280.")
    return out


# --- the command line -------------------------------------------------------------------------


def git_head() -> str | None:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def cmd_build(args: Any) -> int:
    manifest = build_pack(
        args.tables,
        args.out,
        args.version,
        removals=args.removals,
        store_root=args.store,
        logs=args.log or [],
        code_commit=git_head(),
    )
    print(
        f"pack {manifest['version']}: {len(manifest['files'])} files, {manifest['rows']:,} rows, "
        f"{_mb(manifest['bytes'])}; removal entries {manifest['removals']['entries']}"
    )
    for name, t in manifest["tables"].items():
        print(f"  {name:<18} {t['files']:>3} files {t['rows']:>13,} rows {_mb(t['bytes']):>10}")
    problems = check_pack(args.out, args.removals)
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


def cmd_check(args: Any) -> int:
    problems = check_pack(args.pack, args.removals)
    if args.kaggle:
        problems += check_kaggle(args.kaggle, args.pack)
    m = json.loads((Path(args.pack) / "manifest.json").read_text())
    print(
        f"pack {m['version']}: {len(m['files'])} files, {m['rows']:,} rows, {_mb(m['bytes'])}; "
        + ("no problem" if not problems else f"{len(problems)} problem(s)")
    )
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


def cmd_kaggle(args: Any) -> int:
    km = build_kaggle(args.pack, args.out)
    print(f"Kaggle folder: {len(km['files'])} tables, {_mb(km['bytes'])}")
    problems = check_kaggle(args.out, args.pack)
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


def cmd_page(args: Any) -> int:
    if args.page_command == "visibility":
        try:
            state, status = hfpage.visibility(args.dataset)
        except hfpage.PageCheckError as exc:
            print(f"CANNOT TELL: {exc}")
            return 2
        print(f"{args.dataset}: {state} (HTTP {status}, asked signed out)")
        return 0 if state == args.expect.replace("-", " ") else 1
    card_text = Path(args.card).read_text(encoding="utf-8")
    try:
        r = hfpage.signed_out_get(args.url)
    except hfpage.PageCheckError as exc:
        print(f"CANNOT TELL: {exc}")
        return 2
    if r.status_code != 200:
        print(f"CANNOT TELL: {args.url} answered HTTP {r.status_code} signed out.")
        return 2
    problems = hfpage.heading_problems(card_text, r.text)
    print(
        f"{len(hfpage.card_headings(card_text))} card headings; "
        + ("all shown, in order" if not problems else f"{len(problems)} problem(s)")
    )
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


def register(sub: Any) -> None:
    rel = sub.add_parser("release", help="build and check a release pack (nothing is uploaded)")
    rsub = rel.add_subparsers(dest="release_command", required=True)
    b = rsub.add_parser("build", help="write a pack from the tables")
    b.add_argument("--version", required=True)
    b.add_argument("--tables", type=Path, default=Path("data/interim/tables"))
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--removals", type=Path, default=Path("data/removals.csv"))
    b.add_argument("--store", type=Path, default=Path("data/interim/store"))
    b.add_argument("--log", type=Path, action="append", help="request logs (for the read dates)")
    b.set_defaults(func=cmd_build)
    c = rsub.add_parser("check", help="check a pack (and its Kaggle folder)")
    c.add_argument("--pack", type=Path, required=True)
    c.add_argument("--kaggle", type=Path)
    c.add_argument("--removals", type=Path, default=Path("data/removals.csv"))
    c.set_defaults(func=cmd_check)
    k = rsub.add_parser("kaggle", help="write the Kaggle mirror's folder from a pack")
    k.add_argument("--pack", type=Path, required=True)
    k.add_argument("--out", type=Path, required=True)
    k.set_defaults(func=cmd_kaggle)

    page = sub.add_parser("page", help="signed-out checks of the Hugging Face page")
    psub = page.add_subparsers(dest="page_command", required=True)
    v = psub.add_parser("visibility", help="is the dataset public? (no credentials sent)")
    v.add_argument("--dataset", default=DATASET)
    v.add_argument("--expect", choices=["public", "not-public"], required=True)
    v.set_defaults(func=cmd_page)
    h = psub.add_parser("headings", help="does the rendered page show every card heading?")
    h.add_argument("--card", type=Path, required=True)
    h.add_argument("--url", default=f"https://huggingface.co/datasets/{DATASET}")
    h.set_defaults(func=cmd_page)
