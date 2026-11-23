"""The release pack, its check, the removal list, the Kaggle folder and the page checks.

Every event, title and count here is invented; nothing touches the network.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from newsattention import cli, cover, hfpage, release, tables
from tests.test_hfpage import FakeSession

E1, E2 = "2026-10-01-0123abcd", "2026-10-02-89abcdef"
TEXT1 = "An invented storm reaches the coast of Fakeland and closes three of its ports."
TEXT2 = "Voters in the invented republic of Nowhere choose a new council for the first time."
OCT1, OCT2 = date(2026, 10, 1), date(2026, 10, 2)


def write(path: Path, rows: dict, schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(rows, schema=schema), path)


def make_tables(root: Path) -> Path:
    t = root / "tables"
    when = datetime(2026, 10, 3, tzinfo=timezone.utc)
    write(
        t / "events" / "2026-10.parquet",
        {
            "event_id": [E1, E2],
            "date": [OCT1, OCT2],
            "category": ["Disasters and accidents", "Politics and elections"],
            "text": [TEXT1, TEXT2],
            "portal_page": [
                "Portal:Current events/2026 October 1",
                "Portal:Current events/2026 October 2",
            ],
            "revision_id": [101, 102],
            "source_domains": [["example.com"], ["example.org"]],
            "story_titles": [["Invented storm season"], []],
            "depth": [0, 0],
            "retrieved_at": [when, when],
        },
        tables.EVENTS_SCHEMA,
    )
    write(
        t / "event_pages" / "2026-10.parquet",
        {
            "event_id": [E1, E1, E2],
            "qid": ["Q1", None, "Q2"],
            "project": ["en.wikipedia"] * 3,
            "page_id": [11, 99, 12],
            "page_title": ["Fakeland", "Invented storm of 2026", "Nowhere"],
            "link_order": [1, 2, 1],
            "in_text": [True, True, False],
            "story_level": [None, None, 1],
            "role": ["context", "event", "story"],
            "role_confidence": ["medium", "high", "low"],
        },
        tables.EVENT_PAGES_SCHEMA,
    )
    write(
        t / "pages.parquet",
        {
            "page_id": [11, 12, 99],
            "qid": ["Q1", "Q2", None],
            "title": ["Fakeland", "Nowhere", "Invented storm of 2026"],
            "created_estimate": [date(2004, 1, 1), date(2010, 1, 1), OCT1],
            "created_estimate_inside_anchors": [True, True, True],
            "moves_in_span": [1, 0, 0],
            "old_titles": [["Fake Land"], [], []],
            "move_dates": [[date(2025, 1, 1)], [], []],
        },
        tables.PAGES_SCHEMA,
    )
    n = 3
    write(
        t / "views_api" / "2026-10.parquet",
        {
            "date": [OCT1, OCT2, OCT1],
            "qid": ["Q1", "Q2", None],
            "project": ["en.wikipedia", "en.wikipedia", "en.wikipedia"],
            "country": [""] * n,
            "views": [500, 300, 40],
            "source": ["api"] * n,
            "noisy": [False] * n,
            "joined": [True, False, False],
            "page_id": [None, None, 99],
        },
        tables.VIEWS_SCHEMA,
    )
    write(
        t / "series.parquet",
        {
            "qid": ["Q1", "Q2", None, "Q1"],
            "page_id": [None, None, 99, None],
            "project": ["en.wikipedia", "en.wikipedia", "en.wikipedia", "fr.wikipedia"],
            "first_day": [date(2026, 9, 3)] * 4,
            "last_day": [OCT2] * 4,
            "joined": [True, False, False, False],
        },
        tables.SERIES_SCHEMA,
    )
    write(
        t / "views_dp" / "2026-10.parquet",
        {
            "date": [OCT1, OCT1],
            "qid": ["Q1", "Q2"],
            "project": ["en.wikipedia", "fr.wikipedia"],
            "country": ["FR", "BE"],
            "views": [120, 95],
            "source": ["dp", "dp"],
            "noisy": [True, True],
            "joined": [False, False],
            "page_id": [11, 512],
        },
        tables.VIEWS_SCHEMA,
    )
    write(
        t / "attention" / "2026-10.parquet",
        {
            "event_id": [E1, E2],
            "event_date": [OCT1, OCT2],
            "qid": ["Q1", "Q2"],
            "page_id": [None, None],
            "project": ["en.wikipedia"] * 2,
            "country": [""] * 2,
            "date": [OCT1, OCT2],
            "days_since_event": [0, 0],
            "views": [500, 300],
            "baseline": [50.0, 30.0],
            "lift": [10.0, 10.0],
            "source": ["api"] * 2,
        },
        tables.ATTENTION_SCHEMA,
    )
    summary = {name: [None, None] for name in tables.SUMMARY_SCHEMA.names}
    summary.update(
        {
            "event_id": [E1, E2],
            "event_date": [OCT1, OCT2],
            "qid": ["Q1", "Q2"],
            "project": ["en.wikipedia"] * 2,
            "baseline": [50.0, 30.0],
            "views_day0": [500, 300],
            "peak_day": [0, 0],
            "peak_views": [500, 300],
            "half_life_censored": [False, False],
            "observed_days": [2, 1],
            "joined": [True, False],
            "countries_day0": [1, 0],
            "languages_lift2": [1, 1],
        }
    )
    write(t / "attention_summary" / "2026-10.parquet", summary, tables.SUMMARY_SCHEMA)
    write(
        t / "country_status" / "2026-10.parquet",
        {
            "event_id": [E1, E2],
            "event_date": [OCT1, OCT2],
            "qid": ["Q1", "Q2"],
            "project": ["en.wikipedia", "fr.wikipedia"],
            "country": ["FR", "BE"],
            "country_status": ["appeared", "not_published"],
            "baseline_published_days": [0, 0],
            "baseline_file_days": [28, 28],
            "baseline_median": [None, None],
            "views_day0": [120, None],
            "views_day1": [None, None],
            "lift_day0": [None, None],
            "older_method_days": [0, 0],
        },
        tables.COUNTRY_SCHEMA,
    )
    return t


def make_store(root: Path) -> tuple[Path, Path]:
    store = root / "store"
    (store / "portal").mkdir(parents=True)
    (store / "portal" / "revisions.jsonl").write_text(
        json.dumps({"day": "2026-10-01", "read_at": "2026-10-03T10:00:00Z"})
        + "\n"
        + json.dumps({"day": "2026-10-02", "read_at": "2026-11-01T10:00:00Z"})
        + "\n"
    )
    log = root / "usage.csv"
    log.write_text(
        "time,method,host,path,status,bytes\n"
        "2026-10-03T10:00:01Z,GET,en.wikipedia.org,/w/api.php,200,10\n"
        "2026-10-03T10:01:00Z,GET,wikimedia.org,"
        "/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/X/daily/a/b,200,9\n"
        "2026-10-04T10:00:00Z,GET,analytics.wikimedia.org,"
        "/published/datasets/country_project_page/2026-10-01.tsv,200,99\n"
        "2026-10-05T10:00:00Z,GET,analytics.wikimedia.org,"
        "/published/datasets/country_project_page/,200,99\n"
        "2026-10-06T10:00:00Z,GET,wikimedia.org,/api/rest_v1/metrics/pageviews/per-article/x,429,0\n"
    )
    return store, log


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    t = make_tables(tmp_path)
    store, log = make_store(tmp_path)
    out = tmp_path / "pack"
    release.build_pack(
        t,
        out,
        "0.1.0",
        store_root=store,
        logs=[log, tmp_path / "missing.csv"],
        code_commit="abc",
        built_at=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
    )
    return out


def manifest_of(pack: Path) -> dict:
    return json.loads((pack / "manifest.json").read_text())


def rewrite(pack: Path, rel: str, table: pa.Table, update_manifest: bool = True) -> None:
    pq.write_table(table, pack / rel)
    if update_manifest:
        m = manifest_of(pack)
        for f in m["files"]:
            if f["path"] == rel:
                f["bytes"] = (pack / rel).stat().st_size
                f["sha256"] = release.sha256(pack / rel)
                f["rows"] = table.num_rows
        (pack / "manifest.json").write_text(json.dumps(m))


def test_the_pack_passes_its_check_and_leaves_the_roles_out(pack: Path):
    assert release.check_pack(pack) == []
    m = manifest_of(pack)
    assert sorted(m["tables"]) == sorted(release.SPECS)
    names = pq.read_schema(pack / "event_pages" / "2026-10.parquet").names
    assert "role" not in names and "role_confidence" not in names
    assert {"in_text", "story_level"} <= set(names)
    assert m["tables"]["events"]["license"] == release.CC_BY_SA
    assert m["tables"]["views_dp"]["license"] == release.CC0
    assert m["left_out"]["columns"] == {"event_pages": ["role", "role_confidence"]}
    assert m["sources"]["portal"] == {"first": "2026-10-03", "last": "2026-11-01"}
    assert m["sources"]["analytics_api"] == {"first": "2026-10-03", "last": "2026-10-03"}
    assert m["sources"]["country_files"] == {"first": "2026-10-04", "last": "2026-10-04"}
    assert m["facts"]["items"] == 2 and m["facts"]["articles_without_item"] == 1
    assert m["facts"]["country_status"] == {"appeared": 1, "not_published": 1}
    assert (pack / "pages" / "pages.parquet").exists()
    meta = pq.read_schema(pack / "events" / "2026-10.parquet").metadata
    assert meta[b"newsattention.credit"].decode() == release.CREDIT
    card = (pack / "README.md").read_text()
    assert card.startswith("---\nlicense:\n- cc0-1.0\n- cc-by-sa-4.0\n")
    assert "version = {0.1.0}" in card and "{{" not in card
    assert "## Roles: left out of this release" in card
    assert hfpage.raw_tags(card) == [] and hfpage.raw_tags((pack / "LICENSES.md").read_text()) == []


def test_a_pack_is_written_once(pack: Path, tmp_path: Path):
    with pytest.raises(FileExistsError, match="move it aside"):
        release.build_pack(tmp_path / "tables", pack, "0.1.0")


def test_missing_tables_are_named(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="events"):
        release.build_pack(tmp_path / "nothing", tmp_path / "out", "0.1.0")


def test_check_fails_on_a_role_column(pack: Path):
    rel = "event_pages/2026-10.parquet"
    t = pq.read_table(pack / rel)
    t = t.append_column("role", pa.array(["event"] * t.num_rows))
    rewrite(pack, rel, t)
    assert any("'role'" in p and "do not ship" in p for p in release.check_pack(pack))


def test_check_fails_on_a_file_outside_the_manifest(pack: Path):
    (pack / "views_api" / "notes.txt").write_text("x")
    assert any("notes.txt: not in the manifest" in p for p in release.check_pack(pack))
    (pack / "views_api" / "notes.txt").unlink()
    (pack / "views_api" / "2026-10.parquet").write_bytes(b"changed")
    assert any("differs from the manifest" in p for p in release.check_pack(pack))


def test_check_fails_on_a_table_without_its_license(pack: Path):
    rel = "series/series.parquet"
    rewrite(pack, rel, pq.read_table(pack / rel).replace_schema_metadata(None))
    assert any("names no license" in p for p in release.check_pack(pack))
    m = manifest_of(pack)
    del m["tables"]["pages"]["license"]
    (pack / "manifest.json").write_text(json.dumps(m))
    assert any("pages has no license" in p for p in release.check_pack(pack))


def test_check_fails_on_event_text_in_a_cc0_table(pack: Path):
    rel = "event_pages/2026-10.parquet"
    t = pq.read_table(pack / rel)
    titles = t["page_title"].to_pylist()
    titles[0] = TEXT1
    i = t.schema.get_field_index("page_title")
    rewrite(pack, rel, t.set_column(i, t.schema.field(i), pa.array(titles)))
    assert any("holds an event's text" in p for p in release.check_pack(pack))
    titles[0] = "word " * 60
    t = pq.read_table(pack / rel)
    rewrite(pack, rel, t.set_column(i, t.schema.field(i), pa.array(titles)))
    assert any("never event text" in p for p in release.check_pack(pack))


def test_check_fails_on_a_country_row_written_as_zero(pack: Path):
    rel = "views_dp/2026-10.parquet"
    t = pq.read_table(pack / rel)
    i = t.schema.get_field_index("views")
    rewrite(pack, rel, t.set_column(i, t.schema.field(i), pa.array([0, 95])))
    assert any("below 90" in p for p in release.check_pack(pack))
    rel = "country_status/2026-10.parquet"
    t = pq.read_table(pack / rel)
    i = t.schema.get_field_index("views_day1")
    rewrite(pack, rel, t.set_column(i, t.schema.field(i), pa.array([0, None])))
    assert any("views_day1 below 90" in p for p in release.check_pack(pack))


def test_check_fails_on_a_raw_tag_and_wrong_configurations(pack: Path):
    card = (pack / "README.md").read_text()
    card = card.replace("- config_name: pages\n", "- config_name: pagez\n")
    (pack / "README.md").write_text(card + "\nWrite to <name> here.\n")
    problems = release.check_pack(pack)
    assert any("'<name>'" in p for p in problems)
    assert any("the configurations are" in p for p in problems)
    (pack / "README.md").write_text("no metadata")
    assert any("no metadata block" in p for p in release.check_pack(pack))


def test_check_without_a_manifest(tmp_path: Path):
    assert "no manifest.json" in release.check_pack(tmp_path)[0]


def test_removals_leave_the_rows_out_of_the_pack(tmp_path: Path):
    t = make_tables(tmp_path)
    removals = tmp_path / "removals.csv"
    removals.write_text(
        "kind,id,received,issue,reason\n"
        f"event,{E2},2026-11-20,7,privacy\n"
        "page,99,2026-11-21,,error\n"
    )
    out = tmp_path / "pack"
    m = release.build_pack(t, out, "0.1.0", removals=removals)
    assert m["removals"]["entries"] == 2
    assert m["tables"]["events"]["rows"] == 1
    assert m["removals"]["rows_left_out"]["event_pages"] == 2  # the event's link and the page
    assert m["tables"]["pages"]["rows"] == 2
    assert release.check_pack(out, removals) == []
    # A pack built before an entry was added fails the check once the entry is there.
    removals.write_text(removals.read_text() + "item,Q1,2026-11-22,,other\n")
    assert any("removal list names are still in it" in p for p in release.check_pack(out, removals))


def test_the_tracked_removal_list_is_empty_and_valid():
    path = Path(__file__).parent.parent / "data" / "removals.csv"
    assert release.read_removals(path) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("kind,id\n", "the header must be"),
        ("kind,id,received,issue,reason\nevent,nope,2026-11-20,,privacy\n", "line 2, field id"),
        ("kind,id,received,issue,reason\nitem,42,2026-11-20,,privacy\n", "Wikidata id"),
        ("kind,id,received,issue,reason\npage,Q1,2026-11-20,,privacy\n", "whole number"),
        ("kind,id,received,issue,reason\nevent,x,2026-11-20,,because\n", "field"),
        ("kind,id,received,issue,reason\nperson,x,2026-11-20,,privacy\n", "field kind"),
    ],
)
def test_the_removal_list_is_read_strictly(tmp_path: Path, content: str, message: str):
    path = tmp_path / "removals.csv"
    path.write_text(content)
    with pytest.raises(release.RemovalListError, match=message):
        release.read_removals(path)


def test_size_category_and_fill():
    assert release.size_category(999) == "n<1K"
    assert release.size_category(242_000_000) == "100M<n<1B"
    assert release.size_category(10**11) == "n>10B"
    assert release.fill("a {{x}} b", {"x": 1}) == "a 1 b"
    with pytest.raises(KeyError, match="y"):
        release.fill("{{y}}", {})


def test_the_kaggle_folder_mirrors_the_pack(pack: Path, tmp_path: Path):
    out = tmp_path / "kaggle"
    km = release.build_kaggle(pack, out)
    assert release.check_kaggle(out, pack) == []
    assert {f["path"] for f in km["files"]} == {f"{n}.parquet" for n in release.SPECS}
    meta = json.loads((out / "dataset-metadata.json").read_text())
    assert len(meta["title"]) <= 50 and meta["licenses"] == [{"name": "CC-BY-SA-4.0"}]
    assert meta["isPrivate"] is True and meta["expectedUpdateFrequency"] == "not specified"
    assert "## How to cite" in meta["description"]
    assert cover.png_size(out / release.KAGGLE_COVER) == (560, 280)
    with pytest.raises(FileExistsError):
        release.build_kaggle(pack, out)
    (out / "stray.csv").write_text("x")
    meta["keywords"] = ["news", "made-up-tag"]
    meta["title"] = "x" * 51
    (out / "dataset-metadata.json").write_text(json.dumps(meta))
    problems = release.check_kaggle(out, pack)
    assert any("stray.csv" in p for p in problems)
    assert any("made-up-tag" in p for p in problems)
    assert any("Kaggle title: 51" in p for p in problems)


def test_kaggle_metadata_problems():
    meta = {
        "title": "NewsAttention",
        "subtitle": "short",
        "keywords": [],
        "licenses": [{"name": "CC0-1.0"}],
        "expectedUpdateFrequency": "weekly",
        "description": "no heading",
    }
    problems = release.kaggle_metadata_problems(meta)
    assert len(problems) == 4
    assert release.check_kaggle(Path("/nonexistent"), Path("/nonexistent"))[0].endswith(
        "release kaggle`."
    )


def test_the_cover_is_drawn_by_this_code(tmp_path: Path):
    assert cover.render() == cover.TRACKED.read_bytes()
    assert cover.png_size(cover.write_png(tmp_path / "c.png")) == (cover.WIDTH, cover.HEIGHT)
    (tmp_path / "x.png").write_bytes(b"not a png at all, not at all")
    with pytest.raises(ValueError, match="not a PNG"):
        cover.png_size(tmp_path / "x.png")


def test_the_command_line_builds_and_checks(tmp_path: Path, capsys):
    t = make_tables(tmp_path)
    store, log = make_store(tmp_path)
    removals = tmp_path / "removals.csv"
    removals.write_text("kind,id,received,issue,reason\n")
    out, kout = tmp_path / "pack", tmp_path / "kaggle"
    args = ["release", "build", "--version", "0.1.0", "--tables", str(t), "--out", str(out)]
    args += ["--removals", str(removals), "--store", str(store), "--log", str(log)]
    assert cli.main(args) == 0
    assert cli.main(["release", "kaggle", "--pack", str(out), "--out", str(kout)]) == 0
    check = ["release", "check", "--pack", str(out), "--kaggle", str(kout)]
    assert cli.main([*check, "--removals", str(removals)]) == 0
    (out / "extra.txt").write_text("x")
    assert cli.main([*check, "--removals", str(removals)]) == 1
    assert "PROBLEM: extra.txt" in capsys.readouterr().out


def test_page_commands(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(hfpage, "visibility", lambda d: ("not public", 401))
    assert cli.main(["page", "visibility", "--expect", "not-public"]) == 0
    assert cli.main(["page", "visibility", "--expect", "public"]) == 1

    def fail(d):
        raise hfpage.PageCheckError("no answer")

    monkeypatch.setattr(hfpage, "visibility", fail)
    assert cli.main(["page", "visibility", "--expect", "public"]) == 2
    card = tmp_path / "README.md"
    card.write_text("# Title\n## Part\n")
    pages = iter([FakeSession(200, None, "<h1>Title</h1><h2>Part</h2>"), FakeSession(403)])
    real = hfpage.signed_out_get
    monkeypatch.setattr(hfpage, "signed_out_get", lambda url: real(url, next(pages)))
    assert cli.main(["page", "headings", "--card", str(card)]) == 0
    assert cli.main(["page", "headings", "--card", str(card)]) == 2
    monkeypatch.setattr(hfpage, "signed_out_get", fail)
    assert cli.main(["page", "headings", "--card", str(card)]) == 2
    assert "CANNOT TELL" in capsys.readouterr().out


def test_the_issue_forms_name_their_labels_and_the_answer_time():
    forms = Path(__file__).parent.parent / ".github" / "ISSUE_TEMPLATE"
    for name, label in (("correction.yml", "correction"), ("removal.yml", "removal")):
        text = (forms / name).read_text()
        assert f'labels: ["{label}"]' in text
        assert "within 14 days" in text and "docs/corrections.md" in text
    doc = (Path(__file__).parent.parent / "docs" / "corrections.md").read_text()
    assert ",".join(release.REMOVAL_FIELDS) == "kind,id,received,issue,reason"
    assert all(f"`{field}`" in doc for field in release.REMOVAL_FIELDS)


def test_the_zenodo_record_is_for_the_code_and_documents_only():
    meta = json.loads((Path(__file__).parent.parent / ".zenodo.json").read_text())
    assert meta["upload_type"] == "software" and meta["license"] == "Apache-2.0"
    assert "code and documents only, no data table" in meta["description"]
    assert {r["identifier"] for r in meta["related_identifiers"]} == {
        f"https://huggingface.co/datasets/{release.DATASET}",
        f"https://www.kaggle.com/datasets/{release.KAGGLE_ID}",
    }
