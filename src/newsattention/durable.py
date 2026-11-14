"""Writes that reach the disk before the next step relies on them.

A file the operating system has accepted can still sit in memory, or in the drive's own cache,
for some seconds. If an external drive loses its USB connection in that time, the file is lost
although the run has moved on. These helpers flush a file, and the folder that names it, to the
device: on macOS with ``F_FULLFSYNC``, which also empties the drive's cache, and elsewhere with
``fsync``. A run records its progress only after its files are flushed, so a drop either stops
the run before progress moves (a resume fetches again) or leaves the file whole.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import IO, Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None  # type: ignore[assignment]

_FOLDER_SKIP = {errno.EINVAL, errno.ENOTSUP, errno.EBADF, errno.EACCES}


def flush_fd(fd: int) -> None:
    """Flush one open file descriptor to the device."""
    full = getattr(fcntl, "F_FULLFSYNC", None) if fcntl is not None else None
    if full is not None:
        try:
            fcntl.fcntl(fd, full)
            return
        except OSError:
            pass  # a file system without it (some network shares): fall back to fsync
    os.fsync(fd)


def flush_file(fh: IO[Any]) -> None:
    """Flush an open file object: Python's buffer, then the operating system's."""
    fh.flush()
    flush_fd(fh.fileno())


def flush_path(path: Path | str) -> None:
    """Flush a closed file by path."""
    fd = os.open(path, os.O_RDONLY)
    try:
        flush_fd(fd)
    finally:
        os.close(fd)


def flush_folder(path: Path | str) -> None:
    """Flush a folder's entries, so a rename inside it is on the disk.

    Skipped where folders cannot be opened or flushed (Windows, some network shares).
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:  # pragma: no cover - Windows cannot open a folder
        return
    try:
        flush_fd(fd)
    except OSError as exc:
        if exc.errno not in _FOLDER_SKIP:
            raise
    finally:
        os.close(fd)


def publish(tmp: Path, dest: Path, *, replace: bool = False, read_only: bool = False) -> None:
    """Flush ``tmp``, move it to ``dest`` and flush the folder.

    ``replace`` allows an existing ``dest`` (state files); otherwise ``dest`` must not exist
    (raw files are written once). ``read_only`` makes the file read-only after the move.
    """
    if not replace and dest.exists():
        raise FileExistsError(f"{dest} exists. Raw files are written once and never replaced.")
    flush_path(tmp)
    if replace:
        tmp.replace(dest)
    else:
        tmp.rename(dest)
    if read_only:
        dest.chmod(0o444)
    flush_folder(dest.parent)
