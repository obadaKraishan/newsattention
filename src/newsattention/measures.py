"""Attention measures for one event's page.

All measures work on a daily series ``{date: views}``. For Analytics API series, days the API
leaves out are zero (see :mod:`newsattention.pageviews`). For the differentially private
country series a missing day is *not* zero: it means the count was below the release
threshold or the day was not published, so country series get no baseline here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from newsattention.schema import LIFT_FLOOR, Attention

BASELINE_DAYS = 28
#: Days after the event that peak, half-life and excess views look at (day 0 to day 28).
HORIZON = 28
#: Country status thresholds (published baseline days out of 28).
TRACKED_MIN_DAYS = 21
APPEARED_MAX_DAYS = 2


def baseline(
    series: Mapping[date, int], event_day: date, window: int = BASELINE_DAYS
) -> float | None:
    """The median of the ``window`` days before the event; None unless every day is known."""
    days = [event_day - timedelta(days=k) for k in range(1, window + 1)]
    if any(day not in series for day in days):
        return None
    return float(median(series[day] for day in days))


def lift(views: int, base: float | None, floor: float = LIFT_FLOOR) -> float | None:
    """Views over the baseline; None when the baseline is missing or under the floor (10 views)."""
    if base is None or base < floor or base <= 0:
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


@dataclass(frozen=True)
class Summary:
    """The accepted measures for one event page in one language.

    ``excess_7`` and ``excess_28`` sum views minus the baseline over days 0 to 7 and 0 to 28;
    they are None when the baseline is missing or the data end before that day. The peak and
    the half-life look at days 0 to 28. ``half_life_censored`` is True when views had not
    fallen below half the peak by day 28 or by the last day with data.
    """

    baseline: float | None
    views_day0: int | None
    lift_day0: float | None
    lift_day1: float | None
    excess_7: float | None
    excess_28: float | None
    peak_day: int | None
    peak_views: int | None
    half_life_days: int | None
    half_life_censored: bool
    observed_days: int


def summarize(series: Mapping[date, int], event_day: date, last_day: date) -> Summary:
    """Measures for one series; ``last_day`` is the last day whose views are complete."""
    base = baseline(series, event_day)
    end = min(last_day, event_day + timedelta(days=HORIZON))
    days = [event_day + timedelta(days=k) for k in range((end - event_day).days + 1)]
    days = [d for d in days if d in series]
    v0 = series.get(event_day)
    v1 = series.get(event_day + timedelta(days=1))

    def excess(k: int) -> float | None:
        if base is None or last_day < event_day + timedelta(days=k):
            return None
        span = [event_day + timedelta(days=j) for j in range(k + 1)]
        if any(d not in series for d in span):
            return None
        return float(sum(series[d] - base for d in span))

    peak_day = peak_views = half = None
    censored = False
    if days:
        best = max(days, key=lambda d: (series[d], -d.toordinal()))
        peak_day, peak_views = (best - event_day).days, series[best]
        if peak_views > 0:
            later = [d for d in days if d > best and series[d] < peak_views / 2]
            if later:
                half = (later[0] - best).days
            else:
                censored = True
    return Summary(
        baseline=base,
        views_day0=v0,
        lift_day0=None if v0 is None else lift(v0, base),
        lift_day1=None if v1 is None else lift(v1, base),
        excess_7=excess(7),
        excess_28=excess(28),
        peak_day=peak_day,
        peak_views=peak_views,
        half_life_days=half,
        half_life_censored=censored,
        observed_days=len(days),
    )


@dataclass(frozen=True)
class CountryStatus:
    """The conservative country measure for one event page, language and country.

    Built from published rows only: a missing row is never read as zero or filled in.

    - ``tracked``: published on at least 21 of the 28 baseline days; the lift uses the median
      of the published baseline days only.
    - ``appeared``: published on day 0 or day 1 and on at most 2 baseline days. It means the
      count rose above the publication threshold, not that it started from nothing.
    - ``not_published``: no row on day 0 or day 1, and both days have a country file (and not
      tracked).
    - ``unclear``: everything else.
    - ``insufficient_files``: fewer than 21 of the baseline days, or neither day 0 nor day 1,
      have a country file at all (Wikimedia's own missing days or the start of the data); or
      neither day has a row and one of the two has no file, so the missing row may only be a
      missing file. The status cannot be decided.
    """

    status: str
    baseline_published_days: int
    baseline_file_days: int
    baseline_median: float | None
    views_day0: int | None
    views_day1: int | None
    lift_day0: float | None


def country_status(
    published: Mapping[date, int], event_day: date, file_days: set[date] | frozenset[date]
) -> CountryStatus:
    """Status for one country; ``file_days`` are the days that have a country file."""
    window = [event_day - timedelta(days=k) for k in range(1, BASELINE_DAYS + 1)]
    with_file = [d for d in window if d in file_days]
    on = [published[d] for d in window if d in published]
    d0 = published.get(event_day)
    d1 = published.get(event_day + timedelta(days=1))
    day1 = event_day + timedelta(days=1)
    base = float(median(on)) if len(on) >= TRACKED_MIN_DAYS else None
    if len(on) >= TRACKED_MIN_DAYS:
        status = "tracked"
    elif len(with_file) < TRACKED_MIN_DAYS or (
        event_day not in file_days and day1 not in file_days
    ):
        status = "insufficient_files"
    elif d0 is None and d1 is None:
        # A day without a file is unknown, not unpublished.
        both_read = event_day in file_days and day1 in file_days
        status = "not_published" if both_read else "insufficient_files"
    elif len(on) <= APPEARED_MAX_DAYS:
        status = "appeared"
    else:
        status = "unclear"
    return CountryStatus(
        status=status,
        baseline_published_days=len(on),
        baseline_file_days=len(with_file),
        baseline_median=base,
        views_day0=d0,
        views_day1=d1,
        lift_day0=(d0 / base) if (base and d0 is not None) else None,
    )
