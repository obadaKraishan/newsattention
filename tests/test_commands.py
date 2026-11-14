"""The backfill commands end to end through the command line, on a fake server."""

from __future__ import annotations

import json
from datetime import date

from newsattention import cli, commands
from tests.test_daily import handler


def summary(text: str):
    """The JSON summary a command prints after its progress lines."""
    start = 0 if text.startswith("{") else text.rindex("\n{\n") + 1
    return json.loads(text[start:])


def run(make_client, monkeypatch, tmp_path, *argv):
    client, session = make_client(handler)
    monkeypatch.setattr(commands, "make_client", lambda args: client)
    base = ["--store", str(tmp_path / "store"), "--raw", str(tmp_path / "raw")]
    return cli.main([argv[0], *base, *argv[1:]]), session


def test_backfill_commands_in_order(make_client, monkeypatch, tmp_path, capsys):
    span = ["--start", "2025-03-18", "--end", "2025-03-19"]
    assert run(make_client, monkeypatch, tmp_path, "portal-backfill", *span)[0] == 0
    assert summary(capsys.readouterr().out)["read"] == 2
    assert run(make_client, monkeypatch, tmp_path, "reread", "--today", "2025-03-20")[0] == 0
    capsys.readouterr()
    assert run(make_client, monkeypatch, tmp_path, "reparse")[0] == 0
    assert summary(capsys.readouterr().out) == {"days": 2, "events": 2}
    out = tmp_path / "parse.json"
    assert run(make_client, monkeypatch, tmp_path, "parse-report", "--out", str(out))[0] == 0
    assert json.loads(out.read_text())["2025-03"]["events"] == 2
    capsys.readouterr()
    assert run(make_client, monkeypatch, tmp_path, "links")[0] == 0
    assert summary(capsys.readouterr().out)["titles"] == 2


def test_dp_plan_api_and_tables(make_client, monkeypatch, tmp_path, capsys):
    span = ["--start", "2025-03-19", "--end", "2025-03-19"]
    run(make_client, monkeypatch, tmp_path, "portal-backfill", *span)
    run(make_client, monkeypatch, tmp_path, "links")
    capsys.readouterr()
    assert run(make_client, monkeypatch, tmp_path, "dp-download", *span)[0] == 0
    assert summary(capsys.readouterr().out)["downloaded"] == 1
    assert run(make_client, monkeypatch, tmp_path, "dp-filter", *span)[0] == 0
    assert summary(capsys.readouterr().out)["rows"] == 2
    assert run(make_client, monkeypatch, tmp_path, "plan", *span, "--english-only")[0] == 0
    assert summary(capsys.readouterr().out)["calls"] == 1
    assert run(make_client, monkeypatch, tmp_path, "plan", *span)[0] == 0
    planned = summary(capsys.readouterr().out)
    assert planned["calls"] == 2 and planned["appended_now"] == 1
    assert run(make_client, monkeypatch, tmp_path, "api-backfill", *span)[0] == 0
    assert summary(capsys.readouterr().out)["calls"] == 2
    report = tmp_path / "api_check.json"
    assert run(make_client, monkeypatch, tmp_path, "api-check", *span, "--out", str(report))[0] == 0
    checked = summary(capsys.readouterr().out)
    assert checked["problems"] == [] and checked["refetch"] == 0
    assert json.loads(report.read_text())["status_lines"] == 2
    (tmp_path / "store" / "api" / "status.jsonl").write_text("")
    assert run(make_client, monkeypatch, tmp_path, "api-check", *span)[0] == 1
    assert summary(capsys.readouterr().out)["refetch"] == 2


def test_plan_refuses_force(make_client, monkeypatch, tmp_path, capsys):
    span = ["--start", "2025-03-19", "--end", "2025-03-19"]
    run(make_client, monkeypatch, tmp_path, "portal-backfill", *span)
    run(make_client, monkeypatch, tmp_path, "links")
    run(make_client, monkeypatch, tmp_path, "plan", *span, "--english-only")
    try:
        run(make_client, monkeypatch, tmp_path, "plan", *span, "--force")
    except SystemExit as exc:
        assert "only ever appended" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("plan --force should refuse")


def test_daily_command(make_client, monkeypatch, tmp_path, capsys):
    assert run(make_client, monkeypatch, tmp_path, "daily", "--today", "2025-03-20")[0] == 0
    assert summary(capsys.readouterr().out)["day"] == "2025-03-19"


def test_make_client_counts_the_log(tmp_path):
    log = tmp_path / "log.csv"
    log.write_text(
        "time,method,host,path,status,bytes\n"
        "2026-01-01T00:00:00.000Z,GET,en.wikipedia.org,/w/api.php,200,5\n"
        "2026-01-01T00:00:01.000Z,GET,www.wikidata.org,/w/api.php,200,5\n"
    )
    args = cli.build_parser().parse_args(
        ["links", "--log", str(log), "--since", "2025-12-31T00:00:00Z", "--cap-mediawiki", "2"]
    )
    client = commands.make_client(args)
    assert client.budget.used == {"action": 1, "wikidata": 1}
    assert client.min_interval == 0.35
    assert commands.yesterday() < date.today() or commands.yesterday() <= date.today()
