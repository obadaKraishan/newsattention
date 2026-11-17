"""Scoring the rule against hand answers, and the recheck copy. All events are invented."""

from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from newsattention import cli, commands, review, scoring
from newsattention.scoring import NONE, Scored

ROLES3 = [["context", "medium"], ["event", "high"], ["story", "medium"]]


def row(n, stratum, weight, rule, hand, conf=("high", "medium"), roles=ROLES3, notes=""):
    return Scored(
        sheet="sheet-1.xlsx",
        number=n,
        event_id=f"2031-01-{n:02d}-aaaaaaaa",
        stratum=stratum,
        weight=weight,
        category="Sports",
        rule={
            "Q1": rule[0],
            "Q2": rule[1],
            "Q1_confidence": None if rule[0] == NONE else conf[0],
            "Q2_confidence": None if rule[1] == NONE else conf[1],
            "roles": roles,
        },
        hand={"Q1": hand[0], "Q2": hand[1], "notes": notes},
    )


def test_kinds_of_difference():
    assert scoring.kind(2, 2) is None and scoring.kind(NONE, NONE) is None
    assert scoring.kind(2, NONE) == "rule_link_hand_none"
    assert scoring.kind(NONE, 3) == "hand_link_rule_none"
    assert scoring.kind(2, 3) == "different_links"


def test_weighted_share_counts_each_event_for_its_stratum():
    # Stratum A: 2 drawn of 20 (weight 10), both right. Stratum B: 2 drawn of 200 (weight 100),
    # one right. Over the frame of 220: (20 + 100) / 220.
    rows = [
        row(1, "2031-found", 10, (2, 3), (2, 3)),
        row(2, "2031-found", 10, (2, 3), (2, 3)),
        row(3, "2031-not-found", 100, (NONE, 3), (NONE, 3)),
        row(4, "2031-not-found", 100, (NONE, 3), (2, 3)),
    ]
    share = scoring.weighted_share(rows, lambda r: r.right("Q1"))
    assert share == pytest.approx(120 / 220)
    lo, hi = scoring.bootstrap_interval(rows, lambda r: r.right("Q1"), 2000, 7)
    assert lo <= share <= hi
    assert lo == pytest.approx(20 / 220)  # stratum B resampled as none right
    assert hi == pytest.approx(1.0)
    again = scoring.bootstrap_interval(rows, lambda r: r.right("Q1"), 2000, 7)
    assert again == (lo, hi)  # seeded
    assert scoring.bootstrap_interval(rows, lambda r: r.right("Q2"), 500, 1) == (1.0, 1.0)


def test_verdict_against_the_target():
    assert scoring.verdict((0.91, 0.97)).startswith("meets")
    assert scoring.verdict((0.70, 0.85)).startswith("below")
    assert scoring.verdict((0.85, 0.93)).startswith("not settled")


def test_summary_kinds_confidence_and_the_role_of_the_hand_link():
    rows = [
        row(1, "2031-found", 5, (2, 3), (2, 3)),  # both right
        row(2, "2031-found", 5, (2, 3), (NONE, 3)),  # Q1: rule names a link, hand none
        row(3, "2032-not-found", 5, (NONE, NONE), (2, 3), notes="close call"),  # hand only
        row(4, "2032-not-found", 5, (2, NONE), (1, NONE), conf=("low", "low")),  # different
    ]
    s = scoring.summarize(rows, 200, 3)
    q1 = s["Q1"]
    assert q1["right_events"] == 1 and q1["right_weighted"] == 0.25
    assert {k: v["events"] for k, v in q1["differences"].items()} == {
        "rule_link_hand_none": 1,
        "hand_link_rule_none": 1,
        "different_links": 1,
    }
    assert q1["by_confidence"]["high"] == {"events": 2, "right_events": 1, "right_weighted": 0.5}
    assert q1["by_confidence"]["low"]["events"] == 1
    assert q1["by_confidence"][NONE]["events"] == 1
    # The hand's link 2 had the rule's role "event" (event 3); its link 1 was context (event 4).
    assert q1["rule_role_of_hand_link"] == {
        "hand_link_rule_none": {"event": 1},
        "different_links": {"context": 1},
    }
    assert q1["by_found"]["found"]["right_events"] == 1
    assert set(q1["by_year"]) == {"2031", "2032"}
    assert s["Q2"]["right_events"] == 3
    # Event 3: the hand's story link 3 is one of the rule's story pages.
    assert s["Q2"]["hand_link_among_rule_story_pages"]["right_events"] == 4
    assert s["both_right"]["right_events"] == 1
    assert s["notes"] == {"events_with_note": 1, "Q1_right_events": 0, "Q2_right_events": 0}
    assert s["frame_events"] == 20


def test_differences_name_events_by_number_only():
    rows = [
        row(1, "2031-found", 5, (2, 3), (2, 3)),
        row(2, "2031-found", 5, (2, 3), (NONE, 3)),
    ]
    out = scoring.differences(rows)
    assert len(out) == 1 and out[0]["number"] == 2
    assert out[0]["Q1_difference"] == "rule_link_hand_none"
    assert out[0]["Q2_difference"] == "same"
    assert not {"text", "title", "event_id"} & set(out[0])


def test_join_refuses_a_key_or_sheet_for_another_sample():
    design = [{"sheet": "sheet-1.xlsx", "number": 1, "event_id": "e1", "stratum": "2031-found"}]
    design[0]["weight"] = 3.0
    key = [{"sheet": "sheet-1.xlsx", "number": 1, "event_id": "e1", "Q1": 1, "Q2": NONE}]
    answer = [{"sheet": "sheet-1.xlsx", "number": "1", "event_id": "e1", "Q1": 1, "Q2": NONE}]
    rows = scoring.join(design, key, answer, {"e1": "Sports"})
    assert rows[0].right("Q1") and rows[0].category == "Sports"
    moved = [{**answer[0], "number": "2"}]
    with pytest.raises(ValueError, match="filled sheet has it as sheet-1.xlsx event 2"):
        scoring.join(design, key, moved, {})
    with pytest.raises(ValueError, match="no filled sheet holds"):
        scoring.join(design, key, [], {})
    with pytest.raises(ValueError, match="answer key has no entry"):
        scoring.join(design, [], answer, {})
    extra = [*answer, {"sheet": "sheet-1.xlsx", "number": "2", "event_id": "e2"}]
    with pytest.raises(ValueError, match="hold 2 events, the design 1"):
        scoring.join(design, key, extra, {})


STRATA = [
    {"stratum": f"{y}-{f}", "drawn": 18 if (y, f) in {(2025, "found"), (2026, "not-found")} else 19}
    for y in (2023, 2024, 2025, 2026)
    for f in ("found", "not-found")
]


def test_recheck_allocation_is_proportional_to_the_drawn_counts():
    alloc = review.recheck_allocation(STRATA, 30)
    assert sum(alloc.values()) == 30
    assert alloc["2025-found"] == 3 and alloc["2026-not-found"] == 3
    assert all(n == 4 for k, n in alloc.items() if k not in {"2025-found", "2026-not-found"})
    with pytest.raises(ValueError, match="larger than the sample"):
        review.recheck_allocation(STRATA, 200)


def test_recheck_draw_is_seeded_within_strata_and_reordered():
    events = [
        {"event_id": f"{s['stratum'][:4]}-01-{k:02d}-{s['stratum'][5:]}", "stratum": s["stratum"]}
        for s in STRATA
        for k in range(s["drawn"])
    ]
    alloc = review.recheck_allocation(STRATA, 30)
    chosen = review.draw_recheck(events, alloc, 11)
    assert chosen == review.draw_recheck(events, alloc, 11)
    assert chosen != review.draw_recheck(events, alloc, 12)
    counts = {k: sum(1 for e in chosen if e["stratum"] == k) for k in alloc}
    assert counts == alloc
    strata_in_order = [e["stratum"] for e in chosen]
    assert strata_in_order != sorted(strata_in_order)  # a new order, not stratum by stratum
    guide = review.recheck_guide("2031-02-01", 30)
    assert guide[0].startswith("Second pass, on or after 2031-02-01: 30 events")
    assert guide[1:] == review.GUIDE[1:]


def test_rule_answers_and_the_same_links_check():
    rows = [
        {"link_order": 1, "page_title": "Fakeland", "story_level": None},
        {"link_order": 2, "page_title": "2031 Fakeland earthquake", "story_level": None},
        {"link_order": 3, "page_title": "Fakeland crisis", "story_level": 1},
    ]
    assigned = [("context", "medium"), ("event", "high"), ("story", "medium")]
    out = commands.rule_answers(rows, assigned)
    assert (out["Q1"], out["Q2"], out["Q1_confidence"], out["Q2_confidence"]) == (
        2,
        3,
        "high",
        "medium",
    )
    none = commands.rule_answers(rows[:1], assigned[:1])
    assert (none["Q1"], none["Q2"], none["Q1_confidence"]) == ("none", "none", None)
    design = [{"sheet": "sheet-1.xlsx", "number": 4, "event_id": "e1"}]
    titles = [r["page_title"] for r in rows]
    commands.check_same_links(design, {"e1": rows}, {"e1": titles})
    with pytest.raises(SystemExit, match="1 show other links"):
        commands.check_same_links(design, {"e1": rows}, {"e1": titles[:2]})
    with pytest.raises(SystemExit, match="1 sampled events are no longer"):
        commands.check_same_links(design, {}, {"e1": titles})


def test_sheet_links_read_titles_in_link_order(tmp_path):
    events = [
        review.SheetEvent(1, "2031-03-04-aaaaaaaa", "2031-03-04", "Sports", "A wins.", ["A", "B"]),
        review.SheetEvent(2, "2031-03-05-bbbbbbbb", "2031-03-05", "Sports", "C wins.", ["C"]),
    ]
    path = review.write_sheet(tmp_path / "sheet-1.xlsx", events, review.GUIDE)
    assert review.sheet_links(path) == {
        "2031-03-04-aaaaaaaa": ["A", "B"],
        "2031-03-05-bbbbbbbb": ["C"],
    }


def test_review_score_command_end_to_end(tmp_path, capsys):
    from tests.test_review import fill

    events = [
        review.SheetEvent(1, "2031-03-04-aaaaaaaa", "2031-03-04", "Sports", "A wins.", ["A", "B"]),
        review.SheetEvent(2, "2031-03-05-bbbbbbbb", "2031-03-05", "Sports", "C wins.", ["C"]),
    ]
    blank = review.write_sheet(tmp_path / "blank.xlsx", events, review.GUIDE)
    sheet = fill(blank, tmp_path / "sheet-1.xlsx", {"G2": 2, "H2": "none", "G6": "none", "H6": 1})
    design = {
        "events": [
            {"sheet": "sheet-1.xlsx", "number": 1, "event_id": "2031-03-04-aaaaaaaa"},
            {"sheet": "sheet-1.xlsx", "number": 2, "event_id": "2031-03-05-bbbbbbbb"},
        ]
    }
    for d, s in zip(design["events"], ("2031-found", "2031-not-found"), strict=True):
        d |= {"stratum": s, "weight": 10.0}
    key = {
        "rule_version": "9",
        "roles_sha256": commands.roles_sha256(),
        "variant": "without_classes",
        "items_with_classes": 0,
        "events": [
            {**design["events"][0], "Q1": 2, "Q2": "none", "Q1_confidence": "high"},
            {**design["events"][1], "Q1": "none", "Q2": "none"},
        ],
    }
    for k, roles_ in zip(key["events"], ([["context", "low"], ["event", "high"]], [["context", "low"]]), strict=True):  # fmt: skip
        k["roles"] = roles_
    (tmp_path / "design.json").write_text(json.dumps(design))
    (tmp_path / "key.json").write_text(json.dumps(key))
    folder = tmp_path / "tables" / "events"
    folder.mkdir(parents=True)
    pq.write_table(
        pa.table({"event_id": [e.event_id for e in events], "category": ["Sports", "Sports"]}),
        folder / "2031-03.parquet",
    )
    args = ["review-score", str(sheet), "--key", str(tmp_path / "key.json")]
    args += ["--design", str(tmp_path / "design.json"), "--tables", str(tmp_path / "tables")]
    args += ["--out", str(tmp_path / "score.json"), "--reps", "100"]
    assert cli.main([*args, "--differences", str(tmp_path / "diff.json")]) == 0
    printed = capsys.readouterr().out
    assert "Q1: right 100.0% weighted" in printed and "Q2: right 50.0% weighted" in printed
    score = json.loads((tmp_path / "score.json").read_text())
    assert score["Q2"]["differences"]["hand_link_rule_none"]["events"] == 1
    assert score["sheets_sha256"]["sheet-1.xlsx"] == commands.file_sha256(sheet)
    diff = json.loads((tmp_path / "diff.json").read_text())
    assert [(d["number"], d["Q2_difference"]) for d in diff] == [(2, "hand_link_rule_none")]
    # A key made with another roles.py is refused, and so is a freeze of another version.
    (tmp_path / "key2.json").write_text(json.dumps({**key, "roles_sha256": "0" * 64}))
    with pytest.raises(SystemExit, match="another roles.py"):
        cli.main([*args[:3], str(tmp_path / "key2.json"), *args[4:]])
    freeze = {"rule_version": "8", "roles_sha256": commands.roles_sha256()}
    (tmp_path / "freeze.json").write_text(json.dumps(freeze))
    with pytest.raises(SystemExit, match="not the frozen rule"):
        cli.main([*args, "--freeze", str(tmp_path / "freeze.json")])
