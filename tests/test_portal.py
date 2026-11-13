"""Portal parser tests. Every page, event and link here is invented."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from newsattention.portal import (
    PortalPage,
    build_events,
    domain_of,
    event_id_for,
    fetch_pages,
    normalize_title,
    parse_wikitext,
    render_text,
)
from tests.conftest import FakeResponse

MODERN = """{{Current events|year=2031|month=3|day=4|top=yes}}
<!-- All news items below this line -->
'''Armed conflicts and attacks'''
*[[Imaginary war (2030–present)|Imaginary war]]
**[[Siege of Nowhere]], [[Battle of Elsewhere]]
***Forces of [[Fakeland]] capture the [[Nowhere]] bridge. [https://www.example.com/a (Example)] [https://news.example.org/b (''Example News'')]
**A [[ceasefire]] is agreed in [[Fakeland]]. [https://web.archive.org/web/20310304000000/https://archived.example.net/c (Archived)]
'''Sports'''
* [[Fakeland national team]] wins the {{nowrap|[[Made-up Cup]]}} final.<ref>ignored</ref> [//m.example.com/d (Example)]
<!-- All news items above this line -->
"""

OLD = """<!-- All news items below this line -->{{Current events|year=2031|month=01|day=1|content=

;Science and technology
* A [[made-up comet]] is seen over [[Fakeland]].
* [[File:Comet.jpg]] [[fr:Comète]] [[:Category:Comets]] [[Wikipedia:About]] An
  ordinary line.

<!-- All news items above this line -->}}"""


def test_normalize_title():
    assert normalize_title("made_up cup") == "Made up cup"
    assert normalize_title(" Fakeland#History ") == "Fakeland"
    assert normalize_title("Q&amp;A") == "Q&A"
    assert normalize_title(":Fakeland") == "Fakeland"
    assert normalize_title("2031 war: aftermath") == "2031 war: aftermath"
    for skipped in ("File:X.jpg", "Category:X", ":Category:X", "fr:Paris", "wikt:word", "#x", ""):
        assert normalize_title(skipped) is None


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://www.example.com/a", "example.com"),
        ("https://news.example.org/b", "news.example.org"),
        ("//m.example.com/d", "example.com"),
        ("https://amp.example.co.uk/x", "example.co.uk"),
        (
            "https://web.archive.org/web/2031/https://www.archived.example.net/c",
            "archived.example.net",
        ),
        ("https://web.archive.org/web/2031/archived.example.net/c", "archived.example.net"),
        ("https://web.archive.org/web/2031/", "web.archive.org"),
        ("https://www.com/", "www.com"),
        ("https://192.168.0.1/x", None),
        ("http://[bad", None),
    ],
)
def test_domain_of(url, domain):
    assert domain_of(url) == domain


def test_render_text_handles_links_sources_and_templates():
    raw = (
        "The {{ship|HMS|Imaginary||2}} reaches [[Fakeland|the island]] , {{convert|5|km}} away "
        "{{flagicon|Fakeland}}{{lang|xx|Hello}} {{cn}} '''now'''&nbsp;. [https://example.com (X)]"
    )
    assert render_text(raw) == "The HMS Imaginary reaches the island, 5 km away Hello now."
    assert (
        render_text("{{lang-xx|Word}} {{ill|Fake page|de}} {{unknown|a|b=c}}") == "Word Fake page a"
    )
    assert render_text("<small>tiny</small> {{lang}}") == "tiny"


def test_parse_modern_layout():
    events = parse_wikitext(MODERN)
    assert [e.category for e in events] == [
        "Armed conflicts and attacks",
        "Armed conflicts and attacks",
        "Sports",
    ]
    first, second, third = events
    assert first.text == "Forces of Fakeland capture the Nowhere bridge."
    assert first.depth == 3
    assert first.links == ("Fakeland", "Nowhere")
    assert first.story_links == (
        "Siege of Nowhere",
        "Battle of Elsewhere",
        "Imaginary war (2030–present)",
    )
    assert first.source_domains == ("example.com", "news.example.org")
    assert second.story_links == ("Imaginary war (2030–present)",)
    assert second.links == ("Ceasefire", "Fakeland")
    assert second.source_domains == ("archived.example.net",)
    assert third.text == "Fakeland national team wins the Made-up Cup final."
    assert third.links == ("Fakeland national team", "Made-up Cup")
    assert third.source_domains == ("example.com",)
    assert third.story_links == ()


def test_parse_old_layout_and_non_article_links():
    events = parse_wikitext(OLD)
    assert [e.category for e in events] == ["Science and technology"] * 2
    assert events[0].text == "A made-up comet is seen over Fakeland."
    assert events[0].source_urls == ()
    assert events[1].links == ()


def test_uncategorized_and_header_without_children():
    events = parse_wikitext("*[[Euro]] notes appear.\n*[[Lonely link]]\n")
    assert [e.category for e in events] == ["Uncategorized", "Uncategorized"]
    assert events[1].text == "Lonely link"


def test_a_bullet_with_a_source_and_children_is_an_event():
    text = "'''Sports'''\n*A [[race]] is run. [https://example.com/r (X)]\n**Reactions follow. [https://example.com/s (X)]\n"
    events = parse_wikitext(text)
    assert len(events) == 2
    assert events[1].story_links == ()


def test_heading_variants_and_empty_bullets():
    text = "== Law and crime ==\n*\n*A [[trial]] opens.\n'''  '''\n;Politics and elections\n*An [[election]].\n"
    events = parse_wikitext(text)
    assert [e.category for e in events] == ["Law and crime", "Politics and elections"]


def test_event_ids_are_stable_and_repeats_get_a_suffix():
    page = PortalPage(
        "Portal:Current events/2031 March 4",
        date(2031, 3, 4),
        1,
        77,
        "2031-03-05T00:00:00Z",
        "'''Sports'''\n*A [[race]]. [https://example.com/r (X)]\n*Another [[race]]. [https://example.com/r (X)]\n",
    )
    events, links = build_events(page, datetime(2031, 3, 6, tzinfo=timezone.utc))
    assert events[0].event_id == event_id_for(date(2031, 3, 4), parse_wikitext(page.wikitext)[0])
    assert events[1].event_id == events[0].event_id + "-2"
    assert events[0].revision_id == 77
    assert [link.title for link in links] == ["Race", "Race"]


def test_build_events_orders_text_links_before_story_links():
    page = PortalPage("Portal:Current events/2031 March 4", date(2031, 3, 4), 1, 77, None, MODERN)
    events, links = build_events(page, datetime(2031, 3, 6, tzinfo=timezone.utc))
    first = [link for link in links if link.event_id == events[0].event_id]
    assert [(link.title, link.link_order, link.in_text) for link in first] == [
        ("Fakeland", 1, True),
        ("Nowhere", 2, True),
        ("Siege of Nowhere", 3, False),
        ("Battle of Elsewhere", 4, False),
        ("Imaginary war (2030–present)", 5, False),
    ]
    assert events[0].story_titles == [
        "Siege of Nowhere",
        "Battle of Elsewhere",
        "Imaginary war (2030–present)",
    ]


def test_story_link_that_is_also_a_text_link_appears_once():
    text = "*[[Fakeland]]\n**[[Fakeland]] votes. [https://example.com (X)]\n"
    page = PortalPage("Portal:Current events/2031 March 4", date(2031, 3, 4), 1, 7, None, text)
    _, links = build_events(page, datetime(2031, 3, 6, tzinfo=timezone.utc))
    assert [(link.title, link.in_text) for link in links] == [("Fakeland", True)]


def test_missing_page_has_no_events():
    page = PortalPage(
        "Portal:Current events/2031 March 4", date(2031, 3, 4), None, None, None, None
    )
    assert page.missing
    assert build_events(page, datetime(2031, 3, 6, tzinfo=timezone.utc)) == ([], [])


def test_fetch_pages_batches_and_marks_missing_days(make_client):
    def handler(method, url, params, headers):
        titles = params["titles"].split("|")
        pages = [
            {"title": t, "missing": True}
            if t.endswith(" 2")
            else {
                "title": t,
                "pageid": 9,
                "revisions": [
                    {
                        "revid": 5,
                        "timestamp": "2031-03-02T00:00:00Z",
                        "slots": {"main": {"content": "*x"}},
                    }
                ],
            }
            for t in titles
        ]
        return FakeResponse(200, {"query": {"pages": pages}})

    client, session = make_client(handler)
    pages = fetch_pages(client, [date(2031, 3, d) for d in (1, 2, 3)], batch=2)
    assert len(session.calls) == 2
    assert session.calls[0][2]["rvprop"] == "ids|timestamp|content"
    assert [p.missing for p in pages] == [False, True, False]
    assert pages[0].revision_id == 5
    assert pages[0].wikitext == "*x"


def test_story_levels_count_headings_up():
    events = parse_wikitext(MODERN)
    assert events[0].story_levels == (1, 1, 2)
    assert events[1].story_levels == (1,)
    page = PortalPage("Portal:Current events/2031 March 4", date(2031, 3, 4), 1, 77, None, MODERN)
    _, links = build_events(page, datetime(2031, 3, 6, tzinfo=timezone.utc))
    assert [link.story_level for link in links[:5]] == [None, None, 1, 1, 2]


def test_parse_stats_count_what_was_not_read():
    from newsattention.portal import ParseStats

    text = MODERN + (
        "'''Other news'''\n*A [[thing]] {{mystery template|x}} happens.\n"
        "#numbered line\nloose text\n{{Some template}}\n<div>\n[[Category:X]]\n*\n__NOTOC__\n"
    )
    stats = ParseStats()
    events = parse_wikitext(text, stats)
    assert stats.layout == "current"
    assert stats.events == len(events) == 4
    assert stats.story_headings == 2
    assert stats.other_headings == {"Other news": 1}
    assert stats.unknown_templates == {"mystery template": 1}
    assert stats.stray_lines == {
        "numbered list": 1,
        "text": 1,
        "template": 1,
        "html": 1,
        "category or file": 1,
    }
    assert stats.empty_bullets == 1
    assert stats.events_without_sources == 1
    old = ParseStats()
    parse_wikitext(OLD, old)
    assert old.layout == "content"
    assert old.events_without_sources == 2
    none = ParseStats()
    parse_wikitext("*[[Euro]] notes appear.\n", none)
    assert none.layout == "none"
    assert none.uncategorized_events == 1
    assert none.events_without_links == 0
