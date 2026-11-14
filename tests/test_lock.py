"""One Wikimedia command at a time: the lock file. No network."""

from __future__ import annotations

import threading
import time

import pytest

from newsattention import cli, commands, lock


def test_a_second_command_refuses_with_a_plain_message(private_lock):
    first = lock.CommandLock(private_lock).acquire("api-backfill")
    with pytest.raises(lock.CommandBusy) as err:
        lock.CommandLock(private_lock).acquire("daily")
    message = str(err.value)
    assert "'api-backfill' (process" in message and "--wait" in message
    first.release()
    lock.CommandLock(private_lock).acquire("daily").release()


def test_wait_queues_behind_the_holder(private_lock):
    first = lock.CommandLock(private_lock).acquire("api-backfill")
    lines: list[str] = []
    got: list[float] = []

    def second() -> None:
        lock.CommandLock(private_lock).acquire("daily", wait=True, say=lines.append)
        got.append(time.monotonic())

    thread = threading.Thread(target=second)
    released = time.monotonic()
    thread.start()
    time.sleep(0.2)
    assert not got
    released = time.monotonic()
    first.release()
    thread.join(5)
    assert got and got[0] >= released
    assert lines[0].startswith("lock: waiting for 'api-backfill'")


def test_make_client_takes_the_lock_and_refuses_when_it_is_held(private_lock, tmp_path):
    holder = lock.CommandLock(private_lock).acquire("api-backfill")
    args = cli.build_parser().parse_args(["links", "--log", str(tmp_path / "log.csv")])
    with pytest.raises(SystemExit, match="Only one command may send requests"):
        commands.make_client(args)
    holder.release()
    commands.make_client(args)
    assert "\tlinks\t" in private_lock.read_text()


def test_per_host_caps(tmp_path):
    args = cli.build_parser().parse_args(
        ["links", "--log", str(tmp_path / "log.csv"), "--cap-action", "3", "--cap-wikidata", "2"]
    )
    client = commands.make_client(args)
    assert client.budget.caps["action"] == 3 and client.budget.caps["wikidata"] == 2
