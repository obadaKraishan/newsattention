"""Review sheets on invented events: writing, reading back filled copies, the check command."""

from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

from newsattention import cli, review

EVENTS = [
    review.SheetEvent(1, "2031-03-04-aaaaaaaa", "2031-03-04", "Disasters and accidents",
                      "A magnitude 6.8 earthquake strikes the coast of Fakeland.",
                      ["Fakeland", "2031 Fakeland earthquake", "Earthquake"]),
    review.SheetEvent(2, "2031-03-05-bbbbbbbb", "2031-03-05", "Armed conflicts and attacks",
                      "Otherland's army retakes Bramble.",
                      ["Fakeland–Otherland war", "Siege of Bramble (2031)"]),
]  # fmt: skip


def sheet_xml(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read("xl/worksheets/sheet2.xml").decode()


def fill(path, out, answers, shared=False):
    """A copy of the sheet with answers typed into G and H, as a spreadsheet program saves them."""
    xml = sheet_xml(path)
    strings: list[str] = []
    for ref, value in answers.items():
        if isinstance(value, int):
            cell = f'<c r="{ref}"><v>{value}</v></c>'
        elif shared:
            strings.append(value)
            cell = f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
        else:
            cell = f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
        xml = re.sub(rf'<c r="{ref}"[^>]*/>', cell, xml)
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            zout.writestr(item, xml if item == "xl/worksheets/sheet2.xml" else data)
        if shared:
            si = "".join(f"<si><t>{s}</t></si>" for s in strings)
            zout.writestr(
                "xl/sharedStrings.xml",
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"{si}</sst>",
            )
    return out


def test_the_sheet_is_valid_xml_with_dropdowns_links_and_no_rule_output(tmp_path):
    path = review.write_sheet(tmp_path / "sheet.xlsx", EVENTS, review.GUIDE)
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith((".xml", ".rels")):
                ET.fromstring(zf.read(name))  # every part parses
        rels = zf.read("xl/worksheets/_rels/sheet2.xml.rels").decode()
    xml = sheet_xml(path)
    assert xml.count("<dataValidation ") == 4
    assert '<formula1>"none,1,2,3"</formula1>' in xml and '<formula1>"none,1,2"</formula1>' in xml
    assert "https://en.wikipedia.org/wiki/2031_Fakeland_earthquake" in rels
    assert "https://en.wikipedia.org/wiki/Siege_of_Bramble_(2031)" in rels
    for word in ("event", "story", "context", "lift", "views", "confidence"):
        assert f">{word}<" not in xml  # nothing the rule chose, no page views


def test_a_blank_sheet_reports_every_missing_answer(tmp_path):
    path = review.write_sheet(tmp_path / "sheet.xlsx", EVENTS, review.GUIDE)
    check = review.check_sheet(path)
    assert check.events == 2 and check.complete == 0 and not check.ok
    assert check.problems[0] == "event 1: Q1 is not answered"


def test_filled_sheets_read_back_in_both_string_forms(tmp_path):
    path = review.write_sheet(tmp_path / "sheet.xlsx", EVENTS, review.GUIDE)
    answers = {"G2": 2, "H2": "none", "G7": "None", "H7": 1}
    for shared in (False, True):
        check = review.check_sheet(fill(path, tmp_path / f"filled{shared}.xlsx", answers, shared))
        assert check.ok, check.problems
        assert [(a["Q1"], a["Q2"]) for a in check.answers] == [(2, "none"), ("none", 1)]
        assert check.answers[1]["event_id"] == "2031-03-05-bbbbbbbb"


def test_invalid_answers_are_named_by_event_number_only(tmp_path, capsys):
    path = review.write_sheet(tmp_path / "sheet.xlsx", EVENTS, review.GUIDE)
    bad = fill(path, tmp_path / "bad.xlsx", {"G2": 4, "H2": "maybe", "G7": 1, "H7": 1})
    assert cli.main(["review-check", str(bad), "--answers", str(tmp_path / "a.json")]) == 1
    out = capsys.readouterr().out
    assert "event 1: Q1 must be none or a link number from 1 to 3" in out
    assert "event 1: Q2 must be none" in out
    assert "event 2: Q1 and Q2 name the same link" in out
    for title in ("Fakeland", "Bramble", "earthquake"):
        assert title not in out
    assert (tmp_path / "a.json").exists()


def test_the_sample_is_seeded_spread_and_half_found():
    found = {f"{y}-01-{d:02d}-{k:08x}": k % 3 == 0 for y in (2023, 2024, 2025, 2026)
             for d in range(1, 29) for k in range(4)}  # fmt: skip
    ids = review.draw_sample(found, seed=7)
    assert len(ids) == 150 and len(set(ids)) == 150
    assert ids == review.draw_sample(found, seed=7) and ids != review.draw_sample(found, seed=8)
    by_year = {y: sum(e.startswith(str(y)) for e in ids) for y in (2023, 2024, 2025, 2026)}
    assert by_year == {2023: 38, 2024: 38, 2025: 37, 2026: 37}
    assert sum(found[e] for e in ids) == 75
    assert [len(b) for b in review.split(ids)] == [50, 50, 50]
    skip = ids[:10]
    assert not set(skip) & set(review.draw_sample(found, seed=7, exclude=skip))


def test_too_few_events_for_a_stratum_is_a_plain_error():
    import pytest

    with pytest.raises(ValueError, match="2023: too few events"):
        review.draw_sample({"2023-01-01-aaaaaaaa": True}, seed=1)


def test_each_draw_records_its_stratum_and_its_chance_of_being_drawn():
    found = {f"{y}-0{m}-{d:02d}-{k:08x}": (d + k) % 4 == 0 for y in (2023, 2024, 2025, 2026)
             for m in (1, 2) for d in range(1, 29) for k in range(3)}  # fmt: skip
    skip = sorted(found)[:5]
    draws = review.draw_design(found, seed=11, exclude=skip)
    assert [d.event_id for d in draws] == review.draw_sample(found, seed=11, exclude=skip)
    for d in draws:
        members = [e for e in found if e.startswith(f"{d.year}-") and found[e] == d.found]
        members = [e for e in members if e not in skip]
        assert d.stratum == f"{d.year}-{'found' if d.found else 'not-found'}"
        assert d.stratum_size == len(members) and d.probability == d.stratum_drawn / len(members)
        assert found[d.event_id] == d.found and d.event_id not in skip
    by_stratum: dict[str, float] = {}
    for d in draws:
        by_stratum[d.stratum] = by_stratum.get(d.stratum, 0) + d.weight
    sizes = {d.stratum: d.stratum_size for d in draws}
    assert len(by_stratum) == 8
    assert all(abs(by_stratum[s] - sizes[s]) < 1e-9 for s in sizes)  # weights add up to the frame
    assert sum(d.stratum_drawn for d in {d.stratum: d for d in draws}.values()) == 150


def test_the_frame_digest_checks_a_redraw():
    found = {"2025-01-01-aaaaaaaa": True, "2025-01-02-bbbbbbbb": False}
    digest = review.frame_digest(found)
    assert digest == review.frame_digest(dict(reversed(found.items())))
    assert digest != review.frame_digest({**found, "2025-01-02-bbbbbbbb": True})
    assert review.frame_digest(found, exclude=["2025-01-02-bbbbbbbb"]) == review.frame_digest(
        {"2025-01-01-aaaaaaaa": True}
    )
