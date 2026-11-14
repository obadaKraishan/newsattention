"""One Wikimedia command at a time on this machine, whatever the host.

Wikimedia's hosts appear to share one rate limit per client: during the backfill, three
commands that each spoke to a different host drew HTTP 429 from two of them at the same
moments. So every command that sends requests takes this lock first and keeps it until it
exits. A second command refuses with a plain message, or, with ``--wait``, waits its turn.

The lock is an advisory ``flock`` on a small file, so the operating system releases it when
the process ends, even after a crash. The file also names the command that holds the lock.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no flock; the lock is then a no-op
    fcntl = None  # type: ignore[assignment]

ENV_PATH = "NEWSATTENTION_LOCK"


def default_path() -> Path:
    """The lock file: ``$NEWSATTENTION_LOCK``, or one file in the user's temporary folder."""
    env = os.environ.get(ENV_PATH)
    return Path(env) if env else Path(tempfile.gettempdir()) / "newsattention-wikimedia.lock"


class CommandBusy(RuntimeError):
    """Another newsattention command holds the Wikimedia lock."""


class CommandLock:
    """Hold the Wikimedia lock for the life of this object (or of the process)."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        self._fh: IO[Any] | None = None

    def holder(self) -> str:
        """Who holds the lock, as written in the file (``pid``, command, start time)."""
        try:
            text = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        parts = text.split("\t")
        if len(parts) != 3:
            return ""
        pid, command, since = parts
        return f"'{command}' (process {pid}, since {since})"

    def acquire(
        self, command: str, wait: bool = False, say: Callable[[str], None] = print
    ) -> CommandLock:
        """Take the lock, or raise :class:`CommandBusy`; with ``wait``, block until it is free."""
        if fcntl is None:  # pragma: no cover
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = self.holder() or "another newsattention command"
            if not wait:
                fh.close()
                raise CommandBusy(
                    f"{holder} is using Wikimedia. Only one command may send requests at a "
                    f"time. Wait for it to finish, or add --wait to queue behind it "
                    f"(lock file: {self.path})."
                ) from None
            say(f"lock: waiting for {holder} to finish")
            started = time.monotonic()
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            say(f"lock: taken after {time.monotonic() - started:.0f} s")
        fh.seek(0)
        fh.truncate()
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fh.write(f"{os.getpid()}\t{command}\t{since}\n")
        fh.flush()
        self._fh = fh
        return self

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()  # closing the file releases the flock
            self._fh = None

    def __enter__(self) -> CommandLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


#: The lock this process holds, kept open until the process exits.
_HELD: list[CommandLock] = []


def hold(command: str, wait: bool = False, path: Path | str | None = None) -> CommandLock:
    """Take the lock for the rest of this process (once; later calls return the same lock)."""
    if _HELD:
        return _HELD[0]
    lock = CommandLock(path).acquire(command, wait=wait)
    _HELD.append(lock)
    return lock


def release_held() -> None:
    """Release the process-wide lock (for tests)."""
    while _HELD:
        _HELD.pop().release()
