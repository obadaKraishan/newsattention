from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsattention.cli import main
from newsattention.validate import table_for, validate_file

EVENT = {
    "event_id": "2026-11-11-0a1b2c3d",
    "date": "2026-11-11",
    "category": "Sports",
    "text": "A made-up team wins a made-up cup.",
    "portal_page": "Portal:Current events/2026 November 11",
    "revision_id": 100,
    "source_domains": ["example.com"],
    "story_titles": [],
    "depth": 1,
    "retrieved_at": "2026-11-13T12:00:00Z",
}


def write_jsonl(path: Path, rows: list) -> Path:
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))
    return path


def test_table_for_file_names():
    assert table_for(Path("events.jsonl")) == "events"
    assert table_for(Path("event_pages-2026.csv")) == "event_pages"
    assert table_for(Path("views_api.csv")) == "views"
    assert table_for(Path("attention.jsonl")) == "attention"
    with pytest.raises(ValueError, match="Cannot tell"):
        table_for(Path("other.jsonl"))


def test_valid_jsonl(tmp_path):
    report = validate_file(
        write_jsonl(
            tmp_path / "events.jsonl", [EVENT, "", {**EVENT, "event_id": "2026-11-11-0a1b2c3e"}]
        )
    )
    assert report.ok, report.errors
    assert report.rows == 2


def test_duplicate_keys_are_reported(tmp_path):
    report = validate_file(write_jsonl(tmp_path / "events.jsonl", [EVENT, EVENT]))
    assert not report.ok
    assert "line 2: the same event_id as line 1" in report.errors[0]


def test_bad_json_and_non_objects(tmp_path):
    report = validate_file(write_jsonl(tmp_path / "events.jsonl", ["{bad", "[1, 2]"]))
    assert report.errors[0].startswith("line 1: not valid JSON")
    assert report.errors[1] == "line 2: each line must be one JSON object."


def test_field_errors_name_the_line_and_field(tmp_path):
    report = validate_file(write_jsonl(tmp_path / "events.jsonl", [{**EVENT, "depth": 0}]))
    assert report.errors == ["line 1, depth: Input should be greater than or equal to 1"]


def test_empty_file(tmp_path):
    report = validate_file(write_jsonl(tmp_path / "events.jsonl", []))
    assert report.errors == ["events.jsonl has no rows."]


def test_csv_with_lists_and_empty_cells(tmp_path):
    path = tmp_path / "event_pages.csv"
    path.write_text(
        "event_id,qid,project,page_id,page_title,link_order,in_text,role\n"
        "2026-11-11-0a1b2c3d,Q1,en.wikipedia,5,Made-up cup,1,true,unknown\n"
        "2026-11-11-0a1b2c3d,,en.wikipedia,,Red link,2,false,unknown\n"
    )
    report = validate_file(path)
    assert report.ok, report.errors
    events = tmp_path / "events.csv"
    events.write_text(
        ",".join(EVENT)
        + "\n"
        + ",".join(
            "a.com|b.org" if k == "source_domains" else "" if k == "story_titles" else str(v)
            for k, v in EVENT.items()
        )
        + "\n"
    )
    assert validate_file(events).ok


def test_csv_row_with_too_many_cells(tmp_path):
    path = tmp_path / "views.csv"
    path.write_text(
        "date,qid,project,country,views,source,noisy\n"
        "2026-11-11,Q1,en.wikipedia,,5,api,false,extra\n"
    )
    assert validate_file(path).errors == ["line 2: the row has more cells than the header."]


def test_unknown_table_and_suffix(tmp_path):
    with pytest.raises(ValueError, match="Unknown table"):
        validate_file(write_jsonl(tmp_path / "events.jsonl", [EVENT]), table="people")
    with pytest.raises(ValueError, match="jsonl or .csv"):
        validate_file(write_jsonl(tmp_path / "events.txt", [EVENT]))


def test_cli_validate_ok_and_problems(tmp_path, capsys):
    good = write_jsonl(tmp_path / "events.jsonl", [EVENT])
    assert main(["validate", str(good)]) == 0
    assert "OK (1 events rows)" in capsys.readouterr().out
    rows = [{**EVENT, "event_id": f"2026-11-11-0a1b2c3{i}", "depth": 0} for i in range(3)]
    bad = write_jsonl(tmp_path / "events_bad.jsonl", rows)
    assert main(["validate", str(bad), "--max-errors", "2"]) == 1
    out = capsys.readouterr().out
    assert "3 problem(s) in 3 events rows" in out
    assert "... and 1 more" in out
    assert main(["validate", str(tmp_path / "nothing.jsonl")]) == 1
    assert main(["validate", str(tmp_path / "other.jsonl")]) == 1
