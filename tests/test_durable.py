"""Flushed writes: the order of flush and move, and the fallbacks. No network."""

from __future__ import annotations

import errno

import pytest

from newsattention import durable


def test_publish_flushes_the_file_before_the_move_and_the_folder_after(tmp_path, monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(durable, "flush_path", lambda p: events.append(f"file {p.name}"))
    monkeypatch.setattr(durable, "flush_folder", lambda p: events.append(f"folder {p.name}"))
    tmp, dest = tmp_path / "a.parquet.part", tmp_path / "a.parquet"
    tmp.write_bytes(b"data")
    durable.publish(tmp, dest, read_only=True)
    assert events == ["file a.parquet.part", f"folder {tmp_path.name}"]
    assert dest.read_bytes() == b"data" and not tmp.exists()
    assert not dest.stat().st_mode & 0o222


def test_publish_refuses_to_replace_a_raw_file_but_replaces_state(tmp_path):
    dest = tmp_path / "progress.json"
    dest.write_text("old")
    tmp = tmp_path / "progress.json.part"
    tmp.write_text("new")
    with pytest.raises(FileExistsError, match="written once"):
        durable.publish(tmp, dest)
    assert dest.read_text() == "old"
    durable.publish(tmp, dest, replace=True)
    assert dest.read_text() == "new"


def test_flush_helpers_run_on_real_files(tmp_path):
    path = tmp_path / "log.csv"
    with path.open("w") as fh:
        fh.write("time\n")
        durable.flush_file(fh)
    durable.flush_path(path)
    durable.flush_folder(tmp_path)
    assert path.read_text() == "time\n"


class FakeFcntl:
    F_FULLFSYNC = 51

    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.calls = 0

    def fcntl(self, fd: int, op: int) -> int:
        self.calls += 1
        if self.fail:
            raise OSError(errno.ENOTSUP, "not supported")
        return 0


def test_flush_fd_uses_full_fsync_and_falls_back_to_fsync(monkeypatch):
    synced: list[int] = []
    monkeypatch.setattr(durable.os, "fsync", synced.append)
    ok = FakeFcntl(fail=False)
    monkeypatch.setattr(durable, "fcntl", ok)
    durable.flush_fd(7)
    assert ok.calls == 1 and synced == []
    failing = FakeFcntl(fail=True)
    monkeypatch.setattr(durable, "fcntl", failing)
    durable.flush_fd(7)
    assert failing.calls == 1 and synced == [7]
    monkeypatch.setattr(durable, "fcntl", None)
    durable.flush_fd(8)
    assert synced == [7, 8]


def test_flush_folder_skips_file_systems_without_folder_flush(tmp_path, monkeypatch):
    def unsupported(fd: int) -> None:
        raise OSError(errno.EINVAL, "invalid")

    monkeypatch.setattr(durable, "flush_fd", unsupported)
    durable.flush_folder(tmp_path)

    def broken(fd: int) -> None:
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(durable, "flush_fd", broken)
    with pytest.raises(OSError, match="input/output"):
        durable.flush_folder(tmp_path)
