from __future__ import annotations

from datetime import date, timedelta

import pytest

from newsattention import measures

EVENT = date(2031, 3, 1)


def series(before: int, after: list[int]) -> dict[date, int]:
    out = {EVENT - timedelta(days=k): before for k in range(1, 29)}
    out.update({EVENT + timedelta(days=k): v for k, v in enumerate(after)})
    return out


def test_baseline_is_the_median_of_the_28_days_before():
    s = series(100, [500])
    s[EVENT - timedelta(days=1)] = 10_000
    assert measures.baseline(s, EVENT) == 100.0


def test_baseline_needs_every_day():
    s = series(100, [500])
    del s[EVENT - timedelta(days=28)]
    assert measures.baseline(s, EVENT) is None


def test_lift():
    assert measures.lift(500, 100.0) == 5.0
    assert measures.lift(500, 0.0) is None
    assert measures.lift(500, None) is None


def test_peak_takes_the_earliest_of_ties_and_honors_the_horizon():
    s = series(100, [300, 900, 900, 50, 2000])
    assert measures.peak(s, EVENT) == (EVENT + timedelta(days=4), 2000)
    assert measures.peak(s, EVENT, horizon=3) == (EVENT + timedelta(days=1), 900)
    assert measures.peak({}, EVENT) is None


def test_half_life():
    s = series(100, [1000, 800, 600, 400, 300])
    assert measures.half_life(s, EVENT) == 3
    assert measures.half_life(series(100, [1000, 900]), EVENT) is None
    assert measures.half_life(series(0, [0, 0]), EVENT) is None
    assert measures.half_life({}, EVENT) is None
    assert measures.half_life(s, EVENT, horizon=2) is None


def test_breadth():
    counts = [("DE", 120), ("DE", 300), ("FR", 95), ("IT", 0)]
    assert measures.breadth(counts) == 2
    assert measures.breadth(counts, threshold=100) == 1


def test_attention_rows():
    rows = measures.attention_rows(
        "2031-03-01-0a1b2c3d", EVENT, "Q1", "en.wikipedia", series(100, [500, 200])
    )
    assert [(r.days_since_event, r.views, r.lift) for r in rows] == [(0, 500, 5.0), (1, 200, 2.0)]
    assert rows[0].baseline == 100.0


def test_attention_rows_without_baseline():
    rows = measures.attention_rows("2031-03-01-0a1b2c3d", EVENT, "Q1", "en.wikipedia", {EVENT: 5})
    assert rows[0].baseline is None and rows[0].lift is None
    dp = measures.attention_rows(
        "2031-03-01-0a1b2c3d",
        EVENT,
        "Q1",
        "en.wikipedia",
        series(100, [500]),
        source="dp",
        country="DE",
    )
    assert dp[0].baseline is None and dp[0].country == "DE"


def test_lift_floor():
    assert measures.lift(50, 10.0) == 5.0
    assert measures.lift(50, 9.5) is None
    assert measures.lift(50, 9.5, floor=1) == pytest.approx(50 / 9.5)


def test_summarize_full_window():
    s = series(100, [1000, 800, 600, 400, 300] + [100] * 30)
    out = measures.summarize(s, EVENT, EVENT + timedelta(days=40))
    assert out.baseline == 100.0 and out.views_day0 == 1000
    assert out.lift_day0 == 10.0 and out.lift_day1 == 8.0
    assert out.excess_7 == (900 + 700 + 500 + 300 + 200 + 0 + 0 + 0)
    assert out.excess_28 == out.excess_7
    assert (out.peak_day, out.peak_views) == (0, 1000)
    assert out.half_life_days == 3 and not out.half_life_censored
    assert out.observed_days == 29


def test_summarize_censored_and_short_data():
    s = series(100, [1000, 900, 800])
    out = measures.summarize(s, EVENT, EVENT + timedelta(days=2))
    assert out.excess_7 is None and out.excess_28 is None
    assert out.half_life_days is None and out.half_life_censored
    assert out.observed_days == 3
    flat = measures.summarize(series(0, [0, 0]), EVENT, EVENT + timedelta(days=1))
    assert flat.baseline == 0.0 and flat.lift_day0 is None and not flat.half_life_censored
    nobase = measures.summarize({EVENT: 5}, EVENT, EVENT)
    assert nobase.baseline is None and nobase.excess_7 is None and nobase.lift_day1 is None
    empty = measures.summarize({}, EVENT, EVENT)
    assert empty.peak_day is None and empty.observed_days == 0
    gap = series(100, [500] * 10)
    del gap[EVENT + timedelta(days=3)]
    assert measures.summarize(gap, EVENT, EVENT + timedelta(days=9)).excess_7 is None


def test_summarize_peak_within_horizon_only():
    s = series(100, [200] * 29 + [5000])
    out = measures.summarize(s, EVENT, EVENT + timedelta(days=40))
    assert out.peak_views == 200 and out.peak_day == 0


FILES = frozenset(EVENT + timedelta(days=k) for k in range(-40, 10))


def published(baseline_days, day0=None, day1=None):
    out = {EVENT - timedelta(days=k): 200 for k in baseline_days}
    if day0 is not None:
        out[EVENT] = day0
    if day1 is not None:
        out[EVENT + timedelta(days=1)] = day1
    return out


def test_country_status_tracked_uses_published_days_only():
    st = measures.country_status(published(range(1, 22), day0=800), EVENT, FILES)
    assert st.status == "tracked"
    assert st.baseline_published_days == 21 and st.baseline_median == 200.0
    assert st.lift_day0 == 4.0
    missing0 = measures.country_status(published(range(1, 29)), EVENT, FILES)
    assert missing0.status == "tracked" and missing0.lift_day0 is None


def test_country_status_appeared_not_published_unclear():
    assert measures.country_status(published([], day1=300), EVENT, FILES).status == "appeared"
    assert measures.country_status(published([3, 9], day0=300), EVENT, FILES).status == "appeared"
    assert (
        measures.country_status(published([3, 9, 12], day0=300), EVENT, FILES).status == "unclear"
    )
    assert (
        measures.country_status(published(range(1, 21), day0=300), EVENT, FILES).status == "unclear"
    )
    nope = measures.country_status(published(range(1, 10)), EVENT, FILES)
    assert nope.status == "not_published" and nope.lift_day0 is None


def test_country_status_insufficient_files():
    few = frozenset(EVENT + timedelta(days=k) for k in range(-5, 3))
    assert (
        measures.country_status(published([], day0=300), EVENT, few).status == "insufficient_files"
    )
    no_event_files = FILES - {EVENT, EVENT + timedelta(days=1)}
    st = measures.country_status(published([1, 2]), EVENT, no_event_files)
    assert st.status == "insufficient_files" and st.baseline_file_days == 28


def test_country_status_a_missing_file_is_not_a_missing_row():
    # Day 0 has no row and day 1 has no file: unknown, not unpublished (and the mirror case).
    no_day1 = FILES - {EVENT + timedelta(days=1)}
    st = measures.country_status(published(range(1, 10)), EVENT, no_day1)
    assert st.status == "insufficient_files"
    no_day0 = FILES - {EVENT}
    assert measures.country_status(published(range(1, 10)), EVENT, no_day0).status == (
        "insufficient_files"
    )
    # A row on the day that has a file still decides it.
    assert measures.country_status(published([], day0=300), EVENT, no_day1).status == "appeared"
