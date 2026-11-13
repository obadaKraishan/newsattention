"""Wikidata, DP-file and Analytics API readers, with fake sessions and invented counts."""

from __future__ import annotations

from datetime import date

import pytest

from newsattention import dpviews, pageviews, wikidata
from tests.conftest import FakeResponse

# --- wikidata ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("site", "project"),
    [
        ("dewiki", "de.wikipedia"),
        ("simplewiki", "simple.wikipedia"),
        ("zh_yuewiki", "zh-yue.wikipedia"),
        ("be_x_oldwiki", "be-tarask.wikipedia"),
        ("bat_smgwiki", "bat-smg.wikipedia"),
        ("commonswiki", None),
        ("dewiktionary", None),
        ("Xwiki", None),
    ],
)
def test_project_for_site(site, project):
    assert wikidata.project_for_site(site) == project


def test_resolve_titles_follows_normalization_and_redirects(make_client):
    def handler(method, url, params, headers):
        assert url == "https://en.wikipedia.org/w/api.php"
        assert params["redirects"] == "1"
        return FakeResponse(
            200,
            {
                "query": {
                    "normalized": [{"from": "fakeland", "to": "Fakeland"}],
                    "redirects": [{"from": "Fakeland", "to": "Republic of Fakeland"}],
                    "pages": [
                        {
                            "pageid": 7,
                            "title": "Republic of Fakeland",
                            "pageprops": {"wikibase_item": "Q77"},
                        },
                        {"pageid": 8, "title": "New page"},
                        {"title": "Red link", "missing": True},
                        {"title": "Bad<title", "invalid": True},
                    ],
                }
            },
        )

    client, session = make_client(handler)
    out = wikidata.resolve_titles(
        client, ["fakeland", "New page", "Red link", "Bad<title", "fakeland"]
    )
    assert len(session.calls) == 1
    assert out["fakeland"] == wikidata.Resolved("fakeland", "Republic of Fakeland", 7, "Q77", True)
    assert out["New page"].qid is None and out["New page"].page_id == 8
    assert out["Red link"].missing
    assert out["Bad<title"].missing


def test_resolve_titles_batches_by_50(make_client):
    client, session = make_client(lambda m, u, p, h: FakeResponse(200, {"query": {"pages": []}}))
    wikidata.resolve_titles(client, [f"T{i}" for i in range(51)])
    assert [len(c[2]["titles"].split("|")) for c in session.calls] == [50, 1]


def test_sitelinks_keeps_wikipedias_only(make_client):
    def handler(method, url, params, headers):
        assert url == wikidata.WIKIDATA_API
        assert params["props"] == "sitelinks"
        return FakeResponse(
            200,
            {
                "entities": {
                    "Q77": {
                        "sitelinks": {
                            "dewiki": {"site": "dewiki", "title": "Fakeland (Staat)"},
                            "commonswiki": {"site": "commonswiki", "title": "Category:Fakeland"},
                            "frwikivoyage": {"site": "frwikivoyage", "title": "Fakeland"},
                        }
                    },
                    "Q99": {"id": "Q99", "missing": ""},
                }
            },
        )

    client, _ = make_client(handler)
    assert wikidata.sitelinks(client, ["Q77", "Q99"]) == {
        "Q77": {"de.wikipedia": "Fakeland (Staat)"}
    }


def test_titles_for_page_ids(make_client):
    def handler(method, url, params, headers):
        assert url == "https://de.wikipedia.org/w/api.php"
        assert params["pageids"] == "5|6"
        return FakeResponse(
            200,
            {
                "query": {
                    "pages": [
                        {"pageid": 5, "title": "Fakeland", "pageprops": {"wikibase_item": "Q77"}},
                        {"pageid": 6, "missing": True},
                    ]
                }
            },
        )

    client, _ = make_client(handler)
    assert wikidata.titles_for_page_ids(client, "de.wikipedia", [5, 6, 5]) == {
        5: ("Fakeland", "Q77")
    }


# --- dpviews ----------------------------------------------------------------------------

LISTING = """<tr><td><a href="2031-01-01.tsv">2031-01-01.tsv</a></td><td align="right">2031-01-02 02:30  </td><td align="right"> 17M</td></tr>
<tr><td><a href="2031-01-02.tsv">2031-01-02.tsv</a></td><td align="right">2031-01-03 02:31  </td><td align="right">  0 </td></tr>
<tr><td><a href="2031-01-03.tsv">2031-01-03.tsv</a></td><td align="right">2031-01-04 02:31  </td><td align="right">2.5K</td></tr>"""


def test_parse_listing_and_sizes():
    entries = dpviews.parse_listing(LISTING)
    assert [e.day for e in entries] == [date(2031, 1, d) for d in (1, 2, 3)]
    assert [e.approx_bytes for e in entries] == [17 * 1024**2, 0, 2560]
    assert entries[0].modified == "2031-01-02 02:30"
    assert dpviews.ListingEntry(date(2031, 1, 1), "", "?").approx_bytes == 0


def test_file_url():
    assert dpviews.file_url(date(2031, 1, 2)) == (
        "https://analytics.wikimedia.org/published/datasets/country_project_page/2031-01-02.tsv"
    )


def test_iter_rows_reads_both_layouts_and_filters(tmp_path):
    path = tmp_path / "2031-01-01.tsv"
    path.write_text(
        "Fakeland\tFL\ten.wikipedia\t7\tRepublic_of_Fakeland\tQ77\t120\n"
        "Fakeland\tFL\tde.wikipedia\t8\tFakeland\tQ77\t95\n"
        "Otherland\tOL\ten.wikipedia\t9\tOther\tQ88\t300\n"
        "OL\ten.wikipedia\t10\tSix_columns\tQ77\t200\n"
        "broken\trow\n"
        "Fakeland\tFL\ten.wikipedia\tx\tBad\tQ77\t100\n",
        encoding="utf-8",
    )
    rows = list(dpviews.iter_rows(path, item_ids={"Q77"}))
    assert [(r.country, r.project, r.views) for r in rows] == [
        ("FL", "en.wikipedia", 120),
        ("FL", "de.wikipedia", 95),
        ("OL", "en.wikipedia", 200),
    ]
    assert rows[0].page_title == "Republic of Fakeland"
    assert rows[0].country_name == "Fakeland"
    assert rows[2].country_name == ""
    only_de = list(dpviews.iter_rows(path, item_ids={"Q77"}, projects={"de.wikipedia"}))
    assert len(only_de) == 1
    assert dpviews.count_rows(path) == {"read": 4, "skipped": 2}


def test_iter_rows_skips_a_header(tmp_path):
    path = tmp_path / "h.tsv"
    path.write_text(
        "country\tproject\tpage_id\tpage_title\titem_id\tgbc\nFL\ten.wikipedia\t1\tA\tQ1\t99\n"
    )
    assert [r.views for r in dpviews.iter_rows(path)] == [99]


def test_fetch_day(make_client, tmp_path):
    heads = {"2031-01-01": [None, "40"], "2031-01-02": ["0"]}

    def handler(method, url, params, headers):
        day = url.rsplit("/", 1)[1][:10]
        if method == "HEAD":
            size = heads[day].pop(0)
            return FakeResponse(200, headers={} if size is None else {"Content-Length": size})
        return FakeResponse(200, content=b"FL\ten.wikipedia\t1\tA\tQ1\t99\n" * 2)

    client, session = make_client(handler)
    path, size = dpviews.fetch_day(client, date(2031, 1, 1), tmp_path)
    assert path == tmp_path / "country_project_page" / "2031-01-01.tsv"
    assert size == 40
    assert [c[0] for c in session.calls] == ["HEAD", "HEAD", "GET"]
    assert dpviews.fetch_day(client, date(2031, 1, 2), tmp_path) == (None, 0)
    calls = len(session.calls)
    assert dpviews.fetch_day(client, date(2031, 1, 1), tmp_path)[0] == path
    assert len(session.calls) == calls


def test_fetch_day_with_unknown_size_still_downloads(make_client, tmp_path):
    def handler(method, url, params, headers):
        if method == "HEAD":
            return FakeResponse(200)
        return FakeResponse(200, content=b"abc")

    client, _ = make_client(handler)
    _path, size = dpviews.fetch_day(client, date(2031, 1, 1), tmp_path)
    assert size == 3


# --- pageviews --------------------------------------------------------------------------


def test_per_article_url_encodes_the_title():
    url = pageviews.per_article_url(
        "en.wikipedia", "AC/DC & Fakeland?", date(2031, 1, 1), date(2031, 1, 31)
    )
    assert url == (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
        "all-access/user/AC%2FDC_%26_Fakeland%3F/daily/2031010100/2031013100"
    )


def test_daily_views_fills_zero_days_until_complete(make_client):
    body = {
        "items": [
            {"timestamp": "2031010100", "views": 10},
            {"timestamp": "2031010300", "views": 30},
        ]
    }
    client, _ = make_client(lambda m, u, p, h: FakeResponse(200, body))
    out = pageviews.daily_views(
        client,
        "en.wikipedia",
        "Fakeland",
        date(2031, 1, 1),
        date(2031, 1, 5),
        complete_until=date(2031, 1, 4),
    )
    assert out == {
        date(2031, 1, 1): 10,
        date(2031, 1, 2): 0,
        date(2031, 1, 3): 30,
        date(2031, 1, 4): 0,
    }


def test_daily_views_404_means_no_views(make_client):
    client, _ = make_client(lambda m, u, p, h: FakeResponse(404, {}))
    out = pageviews.daily_views(client, "en.wikipedia", "Quiet", date(2031, 1, 1), date(2031, 1, 2))
    assert out == {date(2031, 1, 1): 0, date(2031, 1, 2): 0}
