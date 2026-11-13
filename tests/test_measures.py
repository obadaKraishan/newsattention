from __future__ import annotations

from datetime import date, timedelta

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
