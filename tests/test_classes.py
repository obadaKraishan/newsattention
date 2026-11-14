"""Wikidata classes on an invented Wikidata: ranks, merged items, tiers, resuming. No network."""

from __future__ import annotations

from newsattention import backfill, wikidata
from newsattention.backfill import Store
from newsattention.client import Budget
from tests.conftest import FakeResponse


def claim(value: str, rank: str = "normal") -> dict:
    return {"rank": rank, "mainsnak": {"datavalue": {"value": {"id": value}}}}


ENTITIES = {
    # Q1: a preferred value wins over normal ones; deprecated values never count.
    "Q1": {"id": "Q1", "claims": {"P31": [claim("Q10"), claim("Q11", "preferred")]}},
    "Q2": {"id": "Q2", "claims": {"P31": [claim("Q10"), claim("Q12", "deprecated")]}},
    "Q3": {"id": "Q30", "claims": {"P31": [claim("Q10")]}},  # merged into Q30
    "Q4": {"id": "Q4", "missing": ""},
    "Q10": {"id": "Q10", "labels": {"en": {"value": "made-up event"}},
            "claims": {"P279": [claim("Q20")]}},
    "Q11": {"id": "Q11", "labels": {}, "claims": {}},
    "Q20": {"id": "Q20", "labels": {"en": {"value": "occurrence"}}, "claims": {}},
}  # fmt: skip


def handler(method, url, params, headers):
    assert url == wikidata.WIKIDATA_API and params["action"] == "wbgetentities"
    assert params["maxlag"] == 5
    ids = params["ids"].split("|")
    assert len(ids) <= 50
    return FakeResponse(200, {"entities": {i: ENTITIES[i] for i in ids}})


def test_classes_take_truthy_values_and_label_two_tiers(make_client, tmp_path):
    store = Store(tmp_path / "store", tmp_path / "raw")
    client, session = make_client(handler)
    out = backfill.fetch_classes(client, store, ["Q1", "Q2", "Q3", "Q4"], say=lambda m: None)
    assert out["items_fetched"] == 4 and out["stopped"] is None
    items, classes = backfill.load_classes(store)
    assert items == {"Q1": ["Q11"], "Q2": ["Q10"], "Q3": ["Q10"], "Q4": []}
    assert classes["Q10"]["label"] == "made-up event" and classes["Q10"]["subclass_of"] == ["Q20"]
    assert classes["Q20"]["level"] == 1 and classes["Q11"]["label"] is None
    calls = len(session.calls)
    again = backfill.fetch_classes(client, store, ["Q1", "Q2", "Q3", "Q4"], say=lambda m: None)
    assert again["items_wanted"] == 0 and len(session.calls) == calls  # resumed: no requests


def test_classes_stop_when_wikidata_stays_lagged(make_client, tmp_path):
    store = Store(tmp_path / "store", tmp_path / "raw")
    lagged = FakeResponse(200, {"error": {"code": "maxlag"}}, headers={"Retry-After": "5"})
    client, _ = make_client(lambda m, u, p, h: lagged, max_retries=1)
    lines: list[str] = []
    out = backfill.fetch_classes(client, store, ["Q1"], say=lines.append)
    assert out["stopped"] and out["items_fetched"] == 0
    assert "run the command again later" in lines[0]
    assert client.sleeps == [5.0]  # it waited as asked, once, and did not push


def test_classes_respect_the_wikidata_cap(make_client, tmp_path):
    store = Store(tmp_path / "store", tmp_path / "raw")
    client, _ = make_client(handler, budget=Budget(caps={"wikidata": 0}))
    out = backfill.fetch_classes(client, store, ["Q1"], say=lambda m: None)
    assert "wikidata call cap" in out["stopped"]
