"""Check a table file against the schema: ``newsattention validate FILE``.

A file is JSON Lines (``.jsonl``) or CSV (``.csv``; list fields are written with ``|`` between
items and empty cells mean "no value"). The table is taken from ``--table`` or from the file
name: ``events``, ``event_pages``, ``views`` or ``attention`` at the start of the name.
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
NULLABLE = {"qid", "page_id", "baseline", "lift"}


@dataclass
class Report:
    path: Path
    table: str
    rows: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def table_for(path: Path) -> str:
    """Guess the table from the file name (longest match first)."""
    name = path.name.lower()
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


def validate_file(path: Path | str, table: str | None = None) -> Report:
    """Check every row of ``path``, then the table's unique key."""
    path = Path(path)
    table = table or table_for(path)
    if table not in TABLES:
        raise ValueError(f"Unknown table {table!r}. Use one of: {', '.join(TABLES)}.")
    model = TABLES[table]
    report = Report(path=path, table=table)
    if path.suffix == ".csv":
        rows: Iterator[tuple[int, Any]] = _csv_rows(path)
    elif path.suffix == ".jsonl":
        rows = _jsonl_rows(path)
    else:
        raise ValueError(f"{path.name}: use a .jsonl or .csv file.")
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
    if report.rows == 0:
        report.errors.append(f"{path.name} has no rows.")
    return report
