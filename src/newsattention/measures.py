"""Attention measures for one event's page.

All measures work on a daily series ``{date: views}``. For Analytics API series, days the API
leaves out are zero (see :mod:`newsattention.pageviews`). For the differentially private
country series a missing day is *not* zero: it means the count was below the release
threshold or the day was not published, so country series get no baseline here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from statistics import median

from newsattention.schema import Attention

BASELINE_DAYS = 28


def baseline(
    series: Mapping[date, int], event_day: date, window: int = BASELINE_DAYS
) -> float | None:
    """The median of the ``window`` days before the event; None unless every day is known."""
    days = [event_day - timedelta(days=k) for k in range(1, window + 1)]
    if any(day not in series for day in days):
        return None
    return float(median(series[day] for day in days))


def lift(views: int, base: float | None) -> float | None:
    """Views over the baseline; None when the baseline is missing or zero."""
    if not base:
        return None
    return views / base


def _after(series: Mapping[date, int], event_day: date, horizon: int | None) -> list[date]:
    last = None if horizon is None else event_day + timedelta(days=horizon)
    return sorted(d for d in series if d >= event_day and (last is None or d <= last))


def peak(
    series: Mapping[date, int], event_day: date, horizon: int | None = None
) -> tuple[date, int] | None:
    """The day with the most views from the event day on (the earliest day on ties)."""
    days = _after(series, event_day, horizon)
    if not days:
        return None
    best = max(days, key=lambda d: (series[d], -d.toordinal()))
    return best, series[best]


def half_life(
    series: Mapping[date, int], event_day: date, horizon: int | None = None
) -> int | None:
    """Days from the peak until views first fall below half the peak.

    None when the series ends before that happens (the half-life is not yet observed) or when
    there are no views at all.
    """
    found = peak(series, event_day, horizon)
    if found is None or found[1] == 0:
        return None
    peak_day, peak_views = found
    for day in _after(series, peak_day, None if horizon is None else horizon):
        if day > peak_day and series[day] < peak_views / 2:
            return (day - peak_day).days
    return None


def breadth(counts: Iterable[tuple[str, int]], threshold: int = 0) -> int:
    """How many distinct keys (countries or languages) have more than ``threshold`` views."""
    return len({key for key, views in counts if views > threshold})


def attention_rows(
    event_id: str,
    event_date: date,
    qid: str,
    project: str,
    series: Mapping[date, int],
    source: str = "api",
    country: str = "",
) -> list[Attention]:
    """One row per day from the event day on, with the baseline and the lift."""
    base = baseline(series, event_date) if source == "api" else None
    rows = []
    for day in _after(series, event_date, None):
        views = series[day]
        rows.append(
            Attention(
                event_id=event_id,
                event_date=event_date,
                qid=qid,
                project=project,
                country=country,
                date=day,
                days_since_event=(day - event_date).days,
                views=views,
                baseline=base,
                lift=lift(views, base),
                source=source,  # type: ignore[arg-type]
            )
        )
    return rows
