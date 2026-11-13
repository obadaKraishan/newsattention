"""One test per schema rule. All events and counts are invented."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from newsattention.schema import (
    Attention,
    Event,
    EventPage,
    Views,
    date_of_portal_page,
    portal_page_for,
)

UTC = timezone.utc


def event(**kw):
    base = dict(
        event_id="2026-11-11-0a1b2c3d",
        date=date(2026, 11, 11),
        category="Sports",
        text="A made-up team wins a made-up cup.",
        portal_page="Portal:Current events/2026 November 11",
        revision_id=100,
        source_domains=["example.com", "news.example.org"],
        story_titles=["Made-up cup"],
        depth=2,
        retrieved_at=datetime(2026, 11, 13, 12, 0, tzinfo=UTC),
    )
    base.update(kw)
    return Event(**base)


def page(**kw):
    base = dict(
        event_id="2026-11-11-0a1b2c3d",
        qid="Q123",
        project="en.wikipedia",
        page_id=42,
        page_title="Made-up cup",
        link_order=1,
        in_text=True,
    )
    base.update(kw)
    return EventPage(**base)


def views(**kw):
    base = dict(
        date=date(2026, 11, 11),
        qid="Q123",
        project="en.wikipedia",
        views=500,
        source="api",
        noisy=False,
    )
    base.update(kw)
    return Views(**base)


def attention(**kw):
    base = dict(
        event_id="2026-11-11-0a1b2c3d",
        event_date=date(2026, 11, 11),
        qid="Q123",
        project="en.wikipedia",
        date=date(2026, 11, 12),
        days_since_event=1,
        views=300,
        baseline=100.0,
        lift=3.0,
        source="api",
    )
    base.update(kw)
    return Attention(**base)


def test_valid_rows():
    assert event().depth == 2
    assert page().role == "unknown"
    assert views().country == ""
    assert attention().lift == 3.0


def test_portal_page_names_round_trip():
    assert portal_page_for(date(2026, 1, 5)) == "Portal:Current events/2026 January 5"
    assert date_of_portal_page("Portal:Current events/2026 January 5") == date(2026, 1, 5)
    with pytest.raises(ValueError, match="not a Current Events"):
        date_of_portal_page("Main Page")
    with pytest.raises(ValueError, match="does not end"):
        date_of_portal_page("Portal:Current events/2026 Jan 5")


def test_models_are_frozen_and_reject_extra_fields():
    with pytest.raises(ValidationError):
        event().text = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        event(color="red")


@pytest.mark.parametrize("bad", ["2026-11-11", "2026-11-11-XYZ12345", "e1", "2026-11-11-0a1b2c3"])
def test_event_id_pattern(bad):
    with pytest.raises(ValidationError, match="must look like"):
        event(event_id=bad)


def test_event_id_with_repeat_suffix_is_valid():
    assert event(event_id="2026-11-11-0a1b2c3d-2").event_id.endswith("-2")


def test_event_id_must_start_with_the_date():
    with pytest.raises(ValidationError, match="does not start with the date"):
        event(event_id="2026-11-10-0a1b2c3d")


def test_event_date_must_match_the_portal_page():
    with pytest.raises(ValidationError, match="does not match the portal page"):
        event(portal_page="Portal:Current events/2026 November 10")


def test_event_portal_page_must_be_a_day_page():
    with pytest.raises(ValidationError, match="portal_page"):
        event(portal_page="Portal:Current events")


@pytest.mark.parametrize("field", ["category", "text"])
def test_event_text_fields_not_blank(field):
    with pytest.raises(ValidationError, match="empty"):
        event(**{field: "  "})
    with pytest.raises(ValidationError, match="spaces at the start"):
        event(**{field: " x"})


def test_revision_id_positive_and_depth_at_least_one():
    with pytest.raises(ValidationError):
        event(revision_id=0)
    with pytest.raises(ValidationError):
        event(depth=0)


@pytest.mark.parametrize("bad", ["Example.com", "example", "exa mple.com", "http://example.com"])
def test_source_domains_are_lowercase_hosts(bad):
    with pytest.raises(ValidationError, match="host name"):
        event(source_domains=[bad])


def test_source_domains_without_www_and_unique():
    with pytest.raises(ValidationError, match="without 'www.'"):
        event(source_domains=["www.example.com"])
    with pytest.raises(ValidationError, match="twice"):
        event(source_domains=["example.com", "example.com"])


def test_retrieved_at_needs_a_time_zone_and_comes_after_the_day():
    with pytest.raises(ValidationError, match="time zone"):
        event(retrieved_at=datetime(2026, 11, 13, 12, 0))
    with pytest.raises(ValidationError, match="before the day"):
        event(retrieved_at=datetime(2026, 11, 10, 12, 0, tzinfo=UTC))


@pytest.mark.parametrize("bad", ["Q0", "q12", "Q12a", "12"])
def test_event_page_qid_pattern(bad):
    with pytest.raises(ValidationError, match="Q42"):
        page(qid=bad)


@pytest.mark.parametrize("bad", ["en.wikipedia.org", "en", "en.wiktionary", "EN.wikipedia"])
def test_event_page_project_pattern(bad):
    with pytest.raises(ValidationError, match="en.wikipedia"):
        page(project=bad)


def test_event_page_title_rules():
    with pytest.raises(ValidationError, match="underscores"):
        page(page_title="Made_up_cup")
    with pytest.raises(ValidationError, match="empty"):
        page(page_title="")


def test_event_page_missing_page_has_no_qid():
    assert page(page_id=None, qid=None).page_id is None
    with pytest.raises(ValidationError, match="does not exist"):
        page(page_id=None)


def test_event_page_link_order_and_role():
    with pytest.raises(ValidationError):
        page(link_order=0)
    assert page(role="event").role == "event"
    with pytest.raises(ValidationError):
        page(role="main")


def test_views_api_rows_are_exact_and_for_all_countries():
    with pytest.raises(ValidationError, match="leave it empty"):
        views(country="DE")
    with pytest.raises(ValidationError, match="exact counts"):
        views(noisy=True)
    with pytest.raises(ValidationError):
        views(views=-1)


def test_views_dp_rows_need_a_country_noisy_and_a_published_count():
    assert views(source="dp", noisy=True, country="DE", views=90).views == 90
    with pytest.raises(ValidationError, match="two-letter country"):
        views(source="dp", noisy=True, country="", views=500)
    with pytest.raises(ValidationError, match="two-letter country"):
        views(source="dp", noisy=True, country="Germany", views=500)
    with pytest.raises(ValidationError, match="noisy: true"):
        views(source="dp", noisy=False, country="DE", views=500)
    with pytest.raises(ValidationError, match="below the lowest published count"):
        views(source="dp", noisy=True, country="DE", views=89)


def test_views_qid_and_project_rules():
    with pytest.raises(ValidationError, match="Q42"):
        views(qid="X1")
    with pytest.raises(ValidationError, match="en.wikipedia"):
        views(project="enwiki")


def test_views_source_values():
    with pytest.raises(ValidationError):
        views(source="dump")


def test_attention_days_since_event_must_match_the_dates():
    with pytest.raises(ValidationError, match="days after"):
        attention(days_since_event=2)


def test_attention_lift_must_equal_views_over_baseline():
    with pytest.raises(ValidationError, match="views / baseline"):
        attention(lift=2.0)


def test_attention_lift_needs_a_baseline_at_the_floor():
    with pytest.raises(ValidationError, match="the floor"):
        attention(baseline=0.0, lift=1.0)
    with pytest.raises(ValidationError, match="the floor"):
        attention(baseline=None, lift=1.0)
    with pytest.raises(ValidationError, match="the floor"):
        attention(baseline=9.5, views=19, lift=2.0)
    assert attention(baseline=9.5, lift=None).lift is None
    assert attention(baseline=0.0, lift=None).lift is None
    assert attention(baseline=None, lift=None).baseline is None
    assert attention(baseline=10.0, views=30, lift=3.0).lift == 3.0


def test_attention_baseline_without_lift_is_an_error():
    with pytest.raises(ValidationError, match="lift is empty"):
        attention(lift=None)


def test_attention_country_rules_and_ids():
    with pytest.raises(ValidationError, match="leave it empty"):
        attention(country="DE")
    with pytest.raises(ValidationError, match="need a country"):
        attention(source="dp", baseline=None, lift=None)
    assert attention(source="dp", country="DE", baseline=None, lift=None).country == "DE"
    with pytest.raises(ValidationError, match="must look like"):
        attention(event_id="x")
    with pytest.raises(ValidationError, match="Q42"):
        attention(qid="x")
    with pytest.raises(ValidationError, match="en.wikipedia"):
        attention(project="x")
    with pytest.raises(ValidationError):
        attention(baseline=-1.0)


def test_event_page_story_level_only_for_story_links():
    assert page(in_text=False, story_level=2).story_level == 2
    with pytest.raises(ValidationError, match="no story_level"):
        page(in_text=True, story_level=1)
    with pytest.raises(ValidationError):
        page(in_text=False, story_level=0)
