"""The rule for each link's role, on invented events, pages and classes."""

from __future__ import annotations

from datetime import date

from newsattention import roles

DAY = date(2031, 3, 4)
CLASSES = {
    "C1": {"label": "mass shooting", "subclass_of": []},
    "C2": {"label": "city in Fakeland", "subclass_of": []},
    "C3": {"label": "made-up process", "subclass_of": ["C4"]},
    "C4": {"label": "armed conflict", "subclass_of": []},
    "C5": {"label": "human", "subclass_of": []},
}


def test_head_words_and_class_kinds():
    assert roles.head_word("city in the United States") == "city"
    assert roles.head_word("Grand Prix") == "prix"
    assert roles.head_word(None) is None
    assert roles.class_kind(["C1"], CLASSES) == ("event", "mass shooting")
    assert roles.class_kind(["C2"], CLASSES) == ("context", "city in Fakeland")
    assert roles.class_kind(["C3"], CLASSES) == ("event", "armed conflict")  # one tier up
    assert roles.class_kind(["C2", "C1"], CLASSES)[0] == "event"  # a happening wins a tie
    assert roles.class_kind([], CLASSES) == (None, None)


def test_years_and_words():
    assert roles.years_in("2031 Fakeland earthquake") == {2031}
    assert roles.years_in("2030–31 Fakeland Cup") == {2030, 2031}
    assert roles.years_in("Route 2031x") == set()
    assert "earthquake" in roles.content_words("An earthquake strikes in March")
    assert "march" not in roles.content_words("An earthquake strikes in March")


def link(order, title, in_text=True, level=None):
    return {"link_order": order, "page_title": title, "in_text": in_text, "story_level": level}


def facts(created, kind=None, into=()):
    return roles.PageFacts(created, tuple(into), kind)


TEXT = "A gunman kills 12 people at a market in Bramble, Fakeland."


def run(links, page_facts, summaries=None):
    summaries = summaries or [None] * len(links)
    sigs = [
        roles.signals(DAY, TEXT, lk, pf, sm)
        for lk, pf, sm in zip(links, page_facts, summaries, strict=True)
    ]
    return roles.assign(links, sigs)


def test_a_new_article_in_the_text_is_the_event_and_the_heading_is_the_story():
    links = [
        link(1, "2031 Bramble market shooting"),
        link(2, "Bramble"),
        link(3, "Fakeland"),
        link(4, "Fakeland insurgency", in_text=False, level=1),
    ]
    got = run(
        links,
        [
            facts(date(2031, 3, 4), "event"),
            facts(date(2005, 1, 1), "context"),
            facts(date(2002, 1, 1)),
            facts(date(2019, 6, 1), "event"),
        ],
        [
            {
                "lift_day0": None,
                "lift_day1": None,
                "baseline": None,
                "peak_views": 9000,
                "peak_day": 1,
            }
        ]
        + [None] * 3,
    )
    assert got == [("event", "high"), ("context", "high"), ("context", "medium"), ("story", "high")]
    assert roles.main_story(links, got) == 4


def test_an_old_event_article_in_the_text_is_a_story_unless_it_names_the_year():
    links = [link(1, "Fakeland insurgency"), link(2, "2031 Fakeland general election")]
    got = run(links, [facts(date(2019, 6, 1), "event"), facts(date(2029, 1, 1), "event")])
    assert got == [("story", "medium"), ("event", "medium")]  # class, year and a shared word


def test_a_new_person_article_is_context_and_a_draft_moved_in_is_new():
    links = [link(1, "John Fakename"), link(2, "Bramble market shooting")]
    got = run(
        links,
        [
            facts(date(2031, 3, 4), "context"),
            facts(date(2030, 1, 1), None, into=[date(2031, 3, 5)]),  # a draft, moved in
        ],
    )
    assert got[0] == ("context", "high") and got[1][0] == "event"


def test_of_two_candidates_the_one_with_more_signals_wins():
    links = [link(1, "Bramble attack"), link(2, "2031 Bramble market shooting")]
    got = run(links, [facts(date(2031, 3, 4)), facts(date(2031, 3, 4), "event")])
    assert [r for r, _ in got] == ["context", "event"]


def test_summary_counts_events_by_what_they_have():
    events = {"2031-03-04-a": {"category": "Law and crime"}, "2031-03-04-b": {"category": "Sports"}}
    st = roles.summarize(
        events,
        {
            "2031-03-04-a": [("event", "high"), ("story", "low")],
            "2031-03-04-b": [("context", "medium")],
        },
    )
    assert st["events_have"] == {"both": 1, "neither": 1}
    assert st["roles"] == {"event": 1, "story": 1, "context": 1}
    assert st["by_category"]["Law and crime"] == {"both": 1}
