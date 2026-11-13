"""Wikimedia's differentially private page views by country, project and page.

One file per day at ``analytics.wikimedia.org/published/datasets/country_project_page/``,
named ``YYYY-MM-DD.tsv``, tab-separated, without a header. The README lists six features
(country, project, page_id, page_title, item_id, gbc); the files read on 2026-11-13 have seven
columns, because the country comes twice, as a name and as a two-letter code:

    country name, country code, project, page_id, page_title, item_id, gbc

``page_title`` uses underscores, ``item_id`` is the Wikidata id (empty when there is none) and
``gbc`` is the noisy count. Both layouts are read. The counts are used exactly as published:
this module never removes noise, fills in rows below the release threshold or estimates
unpublished countries.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from newsattention.client import WikimediaClient

BASE = "https://analytics.wikimedia.org/published/datasets/"
CURRENT = "country_project_page"
HISTORICAL = "country_project_page_historical"
PRE_2017 = "country_project_page_historical_pre_2017"
COLUMNS = ("country_name", "country", "project", "page_id", "page_title", "item_id", "gbc")
README_COLUMNS = ("country", "project", "page_id", "page_title", "item_id", "gbc")

LISTING_RE = re.compile(
    r'href="(\d{4}-\d{2}-\d{2})\.tsv">[^<]*</a>\s*</td>\s*<td[^>]*>\s*'
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*</td>\s*<td[^>]*>\s*([\d.]+[KMG]?)\s*</td>"
)
SIZE_UNITS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}


@dataclass(frozen=True)
class DPRow:
    country: str
    project: str
    page_id: int
    page_title: str
    item_id: str
    views: int
    country_name: str = ""


@dataclass(frozen=True)
class ListingEntry:
    day: date
    modified: str
    size_text: str

    @property
    def approx_bytes(self) -> int:
        match = re.fullmatch(r"([\d.]+)([KMG]?)", self.size_text)
        if not match:
            return 0
        return int(float(match.group(1)) * SIZE_UNITS[match.group(2)])


def file_url(day: date, dataset: str = CURRENT) -> str:
    return f"{BASE}{dataset}/{day.isoformat()}.tsv"


def parse_listing(page: str) -> list[ListingEntry]:
    """The daily files in a dataset's directory listing (Apache's HTML index)."""
    return [
        ListingEntry(date.fromisoformat(day), modified, size)
        for day, modified, size in LISTING_RE.findall(page)
    ]


def _open_text(path: Path) -> io.TextIOWrapper:
    return open(path, encoding="utf-8", newline="")


def iter_rows(
    path: Path | str,
    item_ids: set[str] | None = None,
    projects: set[str] | None = None,
) -> Iterator[DPRow]:
    """Stream one daily file, keeping rows whose ``item_id`` (and ``project``) are wanted.

    Seven-column rows (country name and code) and six-column rows (as in the README) are both
    read; a header line is skipped when there is one. Rows that do not parse are skipped and
    counted in ``skipped`` when a dict is passed. The file itself is never changed.
    """
    yield from _iter_rows(Path(path), item_ids, projects, None)


def count_rows(path: Path | str) -> dict[str, int]:
    """Rows read and rows skipped (wrong number of columns, bad numbers) in one file."""
    tally = {"read": 0, "skipped": 0}
    for _ in _iter_rows(Path(path), None, None, tally):
        tally["read"] += 1
    return tally


def _iter_rows(
    path: Path,
    item_ids: set[str] | None,
    projects: set[str] | None,
    tally: dict[str, int] | None,
) -> Iterator[DPRow]:
    with _open_text(path) as fh:
        reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        for i, row in enumerate(reader):
            if len(row) == len(COLUMNS):
                name, country, project, page_id, title, item_id, gbc = row
            elif len(row) == len(README_COLUMNS):
                name = ""
                country, project, page_id, title, item_id, gbc = row
            else:
                if tally is not None:
                    tally["skipped"] += 1
                continue
            if i == 0 and (country in {"country", "country_code"} or name == "country"):
                continue
            if item_ids is not None and item_id not in item_ids:
                continue
            if projects is not None and project not in projects:
                continue
            try:
                views = int(float(gbc))
                pid = int(page_id)
            except ValueError:
                if tally is not None:
                    tally["skipped"] += 1
                continue
            yield DPRow(country, project, pid, title.replace("_", " "), item_id, views, name)


def fetch_day(
    client: WikimediaClient, day: date, raw_dir: Path, dataset: str = CURRENT
) -> tuple[Path | None, int | None]:
    """Download one daily file into ``raw_dir`` after a HEAD request for its size.

    Returns the path (None for an empty or missing file) and the size the server gave. A file
    that is already on disk is never downloaded again.
    """
    url = file_url(day, dataset)
    dest = Path(raw_dir) / dataset / f"{day.isoformat()}.tsv"
    if dest.exists():
        return dest, dest.stat().st_size
    size = client.head_size(url)
    if size is None:
        # A HEAD answer straight from the backend can lack Content-Length; ask once more
        # (the cache then has it). If it is still unknown, the download checks the byte cap
        # while it streams.
        size = client.head_size(url)
    if size == 0:
        return None, 0
    client.download(url, dest, expected_size=size)
    return dest, size if size is not None else dest.stat().st_size
