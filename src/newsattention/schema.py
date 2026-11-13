"""The four NewsAttention tables, as frozen pydantic models.

- :class:`Event`: one news event from a Current Events Portal day page.
- :class:`EventPage`: one article an event links to, with its Wikidata id.
- :class:`Views`: daily page views of one article, for all countries (Analytics API) or for
  one country (the differentially private files).
- :class:`Attention`: derived, one row per event, page, country and day: the views, the
  baseline before the event, the lift over it and the days since the event.

Every model rejects unknown fields. The checks that need more than one row (unique keys)
live in :mod:`newsattention.validate`.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

PORTAL_PREFIX = "Portal:Current events/"
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

#: The smallest count in the differentially private files. The README releases rows "with >90
#: pageviews" for lower-risk countries; the threshold is applied before rounding, so published
#: counts start at 90 (checked in the 2026-10-16 and 2026-11-12 files).
DP_MIN_RELEASED = 90

EVENT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{8}(-\d+)?$")
QID_RE = re.compile(r"^Q[1-9]\d*$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]*\.wikipedia$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def portal_page_for(day: date) -> str:
    """The portal page name for a day, e.g. ``Portal:Current events/2026 November 11``."""
    return f"{PORTAL_PREFIX}{day.year} {MONTHS[day.month - 1]} {day.day}"


def date_of_portal_page(title: str) -> date:
    """The day a portal page covers. Raises ValueError for any other page name."""
    if not title.startswith(PORTAL_PREFIX):
        raise ValueError(f"{title!r} is not a Current Events Portal day page.")
    parts = title[len(PORTAL_PREFIX) :].split(" ")
    if len(parts) != 3 or parts[1] not in MONTHS:
        raise ValueError(f"{title!r} does not end in '<year> <Month> <day>'.")
    return date(int(parts[0]), MONTHS.index(parts[1]) + 1, int(parts[2]))


def check_event_id(value: str) -> str:
    if not EVENT_ID_RE.match(value):
        raise ValueError(
            f"event_id {value!r} must look like 2026-11-11-0a1b2c3d (a date, a dash and "
            "8 hex digits, with an optional -2, -3 ... for repeats)."
        )
    return value


def check_qid(value: str) -> str:
    if not QID_RE.match(value):
        raise ValueError(f"qid {value!r} must look like Q42.")
    return value


def check_project(value: str) -> str:
    if not PROJECT_RE.match(value):
        raise ValueError(f"project {value!r} must look like en.wikipedia.")
    return value


def _nonblank(value: str, name: str) -> str:
    if not value.strip():
        raise ValueError(f"{name} is empty.")
    if value != value.strip():
        raise ValueError(f"{name} has spaces at the start or end.")
    return value


class Event(_Frozen):
    """One event listed on a Current Events Portal day page."""

    event_id: str = Field(description="<date>-<8 hex>, unique within the dataset")
    date: date
    category: str = Field(description="The portal heading the event is listed under")
    text: str = Field(description="The event's text, as plain text")
    portal_page: str
    revision_id: int = Field(gt=0, description="The portal page revision that was read")
    source_domains: list[str] = Field(description="Domains of the news sources the event cites")
    story_titles: list[str] = Field(
        default_factory=list,
        description="Articles linked from the story headings above the event, nearest first",
    )
    depth: int = Field(ge=1, description="Bullet depth on the page (1 is top level)")
    retrieved_at: datetime

    @field_validator("category", "text")
    @classmethod
    def _text_fields(cls, value: str, info: ValidationInfo) -> str:
        return _nonblank(value, info.field_name or "field")

    @field_validator("event_id")
    @classmethod
    def _event_id(cls, value: str) -> str:
        return check_event_id(value)

    @field_validator("source_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        for domain in value:
            if not DOMAIN_RE.match(domain):
                raise ValueError(
                    f"source domain {domain!r} is not a lowercase host name such as reuters.com."
                )
            if domain.startswith("www."):
                raise ValueError(f"source domain {domain!r} should be written without 'www.'.")
        if len(set(value)) != len(value):
            raise ValueError("source_domains lists a domain twice.")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at needs a time zone (write it in UTC, ending in Z).")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Event:
        try:
            page_day = date_of_portal_page(self.portal_page)
        except ValueError as exc:
            raise ValueError(f"portal_page: {exc}") from None
        if page_day != self.date:
            raise ValueError(
                f"date {self.date} does not match the portal page {self.portal_page!r}."
            )
        if not self.event_id.startswith(self.date.isoformat()):
            raise ValueError(f"event_id {self.event_id!r} does not start with the date.")
        if self.retrieved_at.date() < self.date:
            raise ValueError("retrieved_at is before the day the event is listed under.")
        return self


class EventPage(_Frozen):
    """One article an event links to."""

    event_id: str
    qid: str | None = Field(description="Wikidata id; empty when the article has none")
    project: str = Field(description="e.g. en.wikipedia")
    page_id: int | None = Field(gt=0, description="Empty when the linked article does not exist")
    page_title: str = Field(description="The canonical title, after redirects")
    link_order: int = Field(ge=1, description="1 for the first link, in reading order")
    in_text: bool = Field(description="True for links in the event's text, False for story links")
    role: Literal["unknown", "event", "context"] = "unknown"

    @field_validator("event_id")
    @classmethod
    def _event_id(cls, value: str) -> str:
        return check_event_id(value)

    @field_validator("qid")
    @classmethod
    def _qid(cls, value: str | None) -> str | None:
        return None if value is None else check_qid(value)

    @field_validator("project")
    @classmethod
    def _project(cls, value: str) -> str:
        return check_project(value)

    @field_validator("page_title")
    @classmethod
    def _title(cls, value: str) -> str:
        _nonblank(value, "page_title")
        if "_" in value:
            raise ValueError(f"page_title {value!r} should use spaces, not underscores.")
        return value

    @model_validator(mode="after")
    def _missing_page(self) -> EventPage:
        if self.page_id is None and self.qid is not None:
            raise ValueError("A link to a page that does not exist cannot have a qid.")
        return self


class Views(_Frozen):
    """Daily views of one article: all countries (``api``) or one country (``dp``)."""

    date: date
    qid: str
    project: str
    country: str = Field(default="", description="Two-letter code; empty for all countries")
    views: int = Field(ge=0)
    source: Literal["dp", "api"]
    noisy: bool

    @field_validator("qid")
    @classmethod
    def _qid(cls, value: str) -> str:
        return check_qid(value)

    @field_validator("project")
    @classmethod
    def _project(cls, value: str) -> str:
        return check_project(value)

    @model_validator(mode="after")
    def _source_rules(self) -> Views:
        if self.source == "dp":
            if not COUNTRY_RE.match(self.country):
                raise ValueError(
                    "Rows from the differentially private files need a two-letter country."
                )
            if not self.noisy:
                raise ValueError("Rows from the differentially private files are noisy: true.")
            if self.views < DP_MIN_RELEASED:
                raise ValueError(
                    f"A differentially private count of {self.views} is below the lowest "
                    f"published count ({DP_MIN_RELEASED}), so it cannot be a published row."
                )
        else:
            if self.country:
                raise ValueError("Rows from the Analytics API cover all countries: leave it empty.")
            if self.noisy:
                raise ValueError("Rows from the Analytics API are exact counts: noisy is false.")
        return self


class Attention(_Frozen):
    """Derived: views of one event's page on one day, against the page's baseline."""

    event_id: str
    event_date: date
    qid: str
    project: str
    country: str = ""
    date: date
    days_since_event: int
    views: int = Field(ge=0)
    baseline: float | None = Field(
        ge=0, description="Median daily views over the 28 days before the event"
    )
    lift: float | None = Field(ge=0, description="views / baseline; empty when baseline is 0")
    source: Literal["dp", "api"]

    @field_validator("event_id")
    @classmethod
    def _event_id(cls, value: str) -> str:
        return check_event_id(value)

    @field_validator("qid")
    @classmethod
    def _qid(cls, value: str) -> str:
        return check_qid(value)

    @field_validator("project")
    @classmethod
    def _project(cls, value: str) -> str:
        return check_project(value)

    @model_validator(mode="after")
    def _consistent(self) -> Attention:
        if (self.date - self.event_date).days != self.days_since_event:
            raise ValueError(
                f"days_since_event is {self.days_since_event}, but {self.date} is "
                f"{(self.date - self.event_date).days} days after {self.event_date}."
            )
        if self.source == "api" and self.country:
            raise ValueError("Rows from the Analytics API cover all countries: leave it empty.")
        if self.source == "dp" and not COUNTRY_RE.match(self.country):
            raise ValueError("Rows from the differentially private files need a country.")
        if self.lift is not None:
            if not self.baseline:
                raise ValueError("lift needs a baseline above zero.")
            expected = self.views / self.baseline
            if not math.isclose(self.lift, expected, rel_tol=1e-6, abs_tol=1e-9):
                raise ValueError(f"lift is {self.lift}, but views / baseline is {expected:.6g}.")
        elif self.baseline:
            raise ValueError("lift is empty although the baseline is above zero.")
        return self


TABLES: dict[str, type[_Frozen]] = {
    "events": Event,
    "event_pages": EventPage,
    "views": Views,
    "attention": Attention,
}

#: The columns that must be unique together in each table.
KEYS: dict[str, tuple[str, ...]] = {
    "events": ("event_id",),
    "event_pages": ("event_id", "link_order"),
    "views": ("date", "qid", "project", "country", "source"),
    "attention": ("event_id", "qid", "project", "country", "date", "source"),
}

#: List fields, written with "|" between items in CSV files.
LIST_FIELDS = {"source_domains", "story_titles"}
