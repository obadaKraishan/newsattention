"""Check a table file against the schema: ``newsattention validate FILE``.

A file is JSON Lines (``.jsonl``), CSV (``.csv``; list fields are written with ``|`` between
items and empty cells mean "no value") or Parquet (``.parquet``). The table is taken from
``--table``, from the start of the file name, or (for Parquet files named by month) from the
folder name.

JSON Lines and CSV files are checked row by row. A Parquet file is checked in three ways: its
columns must be the model's fields; the table's unique key and the required (non-empty)
fields are checked on every row; and every rule of the model is checked on every row of
files up to ``sample`` rows, or on a random sample of ``sample`` rows of larger files.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from newsattention.schema import KEYS, LIST_FIELDS, TABLES

#: Columns that are optional numbers or ids: an empty CSV cell means "no value".
NULLABLE = {"qid", "page_id", "baseline", "lift", "story_level"}


@dataclass
class Report:
    path: Path
    table: str
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    checked_rows: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def table_for(path: Path) -> str:
    """Guess the table from the file name, or from the folder of a month file (longest first)."""
    names = [path.name.lower()]
    if path.suffix == ".parquet":
        names.append(path.parent.name.lower())
    for name in names:
        for table in sorted(TABLES, key=len, reverse=True):
            if name.startswith(table):
                return table
    raise ValueError(
        f"Cannot tell which table {path.name} holds. Name it events*, event_pages*, views* or "
        "attention*, or pass --table."
    )


def _csv_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for line, row in enumerate(reader, start=2):
            clean: dict[str, Any] = {}
            for key, value in row.items():
                if key is None:
                    clean["_extra_columns"] = value
                elif key in LIST_FIELDS:
                    clean[key] = [part for part in (value or "").split("|") if part]
                elif key in NULLABLE and value == "":
                    clean[key] = None
                else:
                    clean[key] = value
            yield line, clean


def _jsonl_rows(path: Path) -> Iterator[tuple[int, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line, text in enumerate(fh, start=1):
            if not text.strip():
                continue
            try:
                yield line, json.loads(text)
            except json.JSONDecodeError as exc:
                yield line, exc


def _describe(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        where = ".".join(str(part) for part in err["loc"]) or "row"
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{where}: {msg}")
    return out


def validate_file(
    path: Path | str, table: str | None = None, sample: int = 20_000, seed: int = 0
) -> Report:
    """Check every row of ``path``, then the table's unique key."""
    path = Path(path)
    table = table or table_for(path)
    if table not in TABLES:
        raise ValueError(f"Unknown table {table!r}. Use one of: {', '.join(TABLES)}.")
    model = TABLES[table]
    report = Report(path=path, table=table)
    if path.suffix == ".parquet":
        return _validate_parquet(path, table, report, sample, seed)
    if path.suffix == ".csv":
        rows: Iterator[tuple[int, Any]] = _csv_rows(path)
    elif path.suffix == ".jsonl":
        rows = _jsonl_rows(path)
    else:
        raise ValueError(f"{path.name}: use a .jsonl, .csv or .parquet file.")
    seen: dict[tuple[Any, ...], int] = {}
    for line, data in rows:
        report.rows += 1
        if isinstance(data, Exception):
            report.errors.append(f"line {line}: not valid JSON ({data.msg}).")
            continue
        if not isinstance(data, dict):
            report.errors.append(f"line {line}: each line must be one JSON object.")
            continue
        if "_extra_columns" in data:
            report.errors.append(f"line {line}: the row has more cells than the header.")
            continue
        try:
            item = model.model_validate(data)
        except ValidationError as exc:
            report.errors.extend(f"line {line}, {msg}" for msg in _describe(exc))
            continue
        key = tuple(getattr(item, col) for col in KEYS[table])
        if key in seen:
            cols = ", ".join(KEYS[table])
            report.errors.append(
                f"line {line}: the same {cols} as line {seen[key]} ({key!r}); each must be unique."
            )
        else:
            seen[key] = line
    report.checked_rows = report.rows
    if report.rows == 0:
        report.errors.append(f"{path.name} has no rows.")
    return report


def _required(model: Any) -> list[str]:
    return [
        name
        for name, f in model.model_fields.items()
        if f.is_required() and "None" not in str(f.annotation)
    ]


def _validate_parquet(path: Path, table: str, report: Report, sample: int, seed: int) -> Report:
    import random

    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    model = TABLES[table]
    data = pq.read_table(path)
    report.rows = data.num_rows
    fields = list(model.model_fields)
    missing = [f for f in fields if f not in data.column_names]
    extra = [c for c in data.column_names if c not in fields]
    if missing or extra:
        report.errors.append(
            f"{path.name}: columns differ from the {table} table "
            f"(missing: {', '.join(missing) or 'none'}; extra: {', '.join(extra) or 'none'})."
        )
        return report
    if report.rows == 0:
        report.errors.append(f"{path.name} has no rows.")
        return report
    for name in _required(model):
        nulls = data[name].null_count
        if nulls:
            report.errors.append(f"{path.name}, {name}: {nulls} empty values in a required field.")
    keys = list(KEYS[table])
    counts = data.group_by(keys).aggregate([([], "count_all")])
    dups = counts.filter(pc.greater(counts["count_all"], 1))
    if dups.num_rows:
        first = {k: dups[k][0].as_py() for k in keys}
        report.errors.append(
            f"{path.name}: {dups.num_rows} {', '.join(keys)} values appear more than once "
            f"(first: {first}); each must be unique."
        )
    if report.rows <= sample:
        idx = list(range(report.rows))
    else:
        idx = sorted(random.Random(seed).sample(range(report.rows), sample))
    rows = data.take(idx).to_pylist()
    for i, row in zip(idx, rows, strict=True):
        try:
            model.model_validate(row)
        except ValidationError as exc:
            report.errors.extend(f"row {i + 1}, {msg}" for msg in _describe(exc))
    report.checked_rows = len(idx)
    return report
