"""Polite HTTP access to Wikimedia services.

Every request:
- carries the project's User-Agent, with a contact URL and never an email address;
- waits for the previous request to finish (the client is strictly sequential);
- backs off on HTTP 429 and 5xx, honoring ``Retry-After``;
- sends ``maxlag`` to the MediaWiki Action API and waits when the servers are lagged;
- can keep a minimum interval between requests (the Analytics API answered HTTP 429 at about
  200 requests a minute on 2026-11-13, so the command line spaces requests 0.35 s apart);
- counts against a per-source call cap and, for file downloads, a byte cap;
- adds one line to the usage log: time, method, host, path, status and bytes.

An HTTP 403 means the source has blocked us. The client raises :class:`SourceBlocked` and the
caller stops using that source; it never retries or works around a block.
"""

from __future__ import annotations

import csv
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from newsattention import __version__, durable

CONTACT_URL = "https://github.com/obadaKraishan"
LOG_FIELDS = ["time", "method", "host", "path", "status", "bytes"]
MAXLAG_SECONDS = 5

#: Default caps for one working session. Raise them only with the maintainer's approval.
DEFAULT_CAPS = {"analytics": 3000, "wikidata": 500}
DEFAULT_MAX_BYTES = 1_000_000_000


class SourceBlocked(RuntimeError):
    """The source answered 403, or kept failing after every retry. Stop using it."""

    def __init__(self, host: str, status: int, message: str) -> None:
        super().__init__(message)
        self.host = host
        self.status = status


class CallCapReached(RuntimeError):
    """The next request would go over a call cap or the byte cap."""


def user_agent() -> str:
    """The User-Agent sent with every request."""
    return f"newsattention/{__version__} ({CONTACT_URL}) python-requests/{requests.__version__}"


def family_of(host: str, path: str) -> str:
    """Group a request by the cap it counts against."""
    if host == "wikimedia.org" and path.startswith("/api/rest_v1/metrics/"):
        return "analytics"
    if host == "www.wikidata.org":
        return "wikidata"
    if path.endswith("/w/api.php"):
        return "action"
    if host in {"analytics.wikimedia.org", "dumps.wikimedia.org"}:
        return "files"
    return "web"


def now_utc() -> str:
    """UTC time with milliseconds, so the gaps between requests can be measured."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class UsageLog:
    """Append-only CSV of request metadata. It never holds response bodies."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, method: str, url: str, status: int, nbytes: int, when: str) -> None:
        parts = urlsplit(url)
        new = not self.path.exists() or self.path.stat().st_size == 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if new:
                writer.writerow(LOG_FIELDS)
            writer.writerow([when, method, parts.netloc, parts.path, status, nbytes])
            durable.flush_file(fh)

    def rows(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))


#: Families whose bytes count against the byte cap: file downloads only. API answers are
#: capped by their call counts instead.
BYTE_FAMILIES = frozenset({"files"})


@dataclass
class Budget:
    """Call caps per source family (and per group of families) and a download byte cap.

    ``group_caps`` maps a name to the families it covers and their combined cap, for example
    ``{"mediawiki": (("action", "wikidata"), 10_000)}``: every ``/w/api.php`` request, on
    Wikipedia or on Wikidata, counts against the same 10,000.
    """

    caps: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CAPS))
    max_bytes: int = DEFAULT_MAX_BYTES
    used: dict[str, int] = field(default_factory=dict)
    bytes_used: int = 0
    group_caps: dict[str, tuple[tuple[str, ...], int]] = field(default_factory=dict)

    @classmethod
    def from_log(
        cls,
        rows: Iterable[dict[str, str]],
        since: str,
        caps: dict[str, int] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        group_caps: dict[str, tuple[tuple[str, ...], int]] | None = None,
    ) -> Budget:
        """Start from the calls already logged since ``since`` (an ISO time in UTC)."""
        budget = cls(
            caps=dict(DEFAULT_CAPS if caps is None else caps),
            max_bytes=max_bytes,
            group_caps=dict(group_caps or {}),
        )
        for row in rows:
            if row["time"] < since:
                continue
            budget.record(family_of(row["host"], row["path"]), int(row["bytes"] or 0))
        return budget

    def check_call(self, family: str) -> None:
        cap = self.caps.get(family)
        if cap is not None and self.used.get(family, 0) >= cap:
            raise CallCapReached(
                f"The {family} call cap ({cap:,}) is reached. Stop here, or ask for a higher cap."
            )
        for name, (families, group_cap) in self.group_caps.items():
            if family in families and sum(self.used.get(f, 0) for f in families) >= group_cap:
                raise CallCapReached(
                    f"The {name} call cap ({group_cap:,}, for {', '.join(families)}) is reached. "
                    "Stop here, or ask for a higher cap."
                )

    def check_bytes(self, nbytes: int) -> None:
        if self.bytes_used + nbytes > self.max_bytes:
            raise CallCapReached(
                f"Downloading {nbytes:,} more bytes would go over the cap of "
                f"{self.max_bytes:,} bytes ({self.bytes_used:,} used). Ask before going further."
            )

    def record(self, family: str, nbytes: int) -> None:
        self.used[family] = self.used.get(family, 0) + 1
        if family in BYTE_FAMILIES:
            self.bytes_used += nbytes


class WikimediaClient:
    """A sequential HTTP client for Wikimedia hosts. Pass a fake ``session`` in tests."""

    def __init__(
        self,
        log: UsageLog,
        budget: Budget | None = None,
        session: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
        base_delay: float = 2.0,
        timeout: float = 60.0,
        min_interval: float = 0.0,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], str] = now_utc,
    ) -> None:
        self.log = log
        self.budget = budget or Budget()
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self.clock = clock
        self.min_interval = min_interval
        self.monotonic = monotonic
        self._last_start: float | None = None
        self.last_when = ""
        self.blocked: dict[str, int] = {}

    def _headers(self, encoding: str = "gzip") -> dict[str, str]:
        return {"User-Agent": user_agent(), "Accept-Encoding": encoding}

    def _delay(self, resp: Any, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After") if resp is not None else None
        if retry_after:
            try:
                return max(float(retry_after), 1.0)
            except ValueError:
                pass
        return self.base_delay * (2**attempt)

    def _send(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        stream: bool,
        encoding: str = "gzip",
    ) -> Any:
        host = urlsplit(url).netloc
        if host in self.blocked:
            raise SourceBlocked(
                host, self.blocked[host], f"{host} blocked us earlier in this run; not retrying."
            )
        path = urlsplit(url).path
        family = family_of(host, path)
        last = None
        for attempt in range(self.max_retries + 1):
            self.budget.check_call(family)
            self._pace()
            when = self.clock()
            self.last_when = when
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    headers=self._headers(encoding),
                    timeout=self.timeout,
                    stream=stream,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                # A network failure or a timeout: logged with status 0, then backed off.
                self.log.append(method, url, 0, 0, when)
                self.budget.record(family, 0)
                last = None
                if attempt < self.max_retries:
                    self.sleep(self.base_delay * (2**attempt))
                    continue
                raise SourceBlocked(
                    host, 0, f"{host} kept failing (network) after retries."
                ) from exc
            if not stream:
                nbytes = len(resp.content or b"")
                self.log.append(method, url, resp.status_code, nbytes, when)
                self.budget.record(family, nbytes)
            if resp.status_code == 403:
                if stream:
                    self.log.append(method, url, 403, 0, when)
                    self.budget.record(family, 0)
                self.blocked[host] = 403
                raise SourceBlocked(
                    host, 403, f"{host} answered 403 (blocked). Stop using this source."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if stream:
                    self.log.append(method, url, resp.status_code, 0, when)
                    self.budget.record(family, 0)
                last = resp
                if attempt < self.max_retries:
                    self.sleep(self._delay(resp, attempt))
                    continue
                break
            if path.endswith("/w/api.php") and not stream and _is_maxlag(resp):
                last = resp
                if attempt < self.max_retries:
                    self.sleep(self._delay(resp, attempt))
                    continue
                break
            return resp
        status = last.status_code if last is not None else 0
        raise SourceBlocked(host, status, f"{host} kept failing (HTTP {status}) after retries.")

    def _pace(self) -> None:
        """Keep at least ``min_interval`` seconds between the starts of two requests."""
        now = self.monotonic()
        if self.min_interval and self._last_start is not None:
            wait = self._last_start + self.min_interval - now
            if wait > 0:
                self.sleep(wait)
                # Read the clock again: a sleep can end late, and the next wait counts from
                # when this request really starts.
                now = max(now + wait, self.monotonic())
        self._last_start = now

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self._send("GET", url, params, stream=False)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = self.get(url, params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def action_api(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call the MediaWiki Action API with JSON, formatversion 2 and maxlag."""
        full = {"format": "json", "formatversion": "2", "maxlag": MAXLAG_SECONDS, **params}
        data = self.get_json(url, full)
        if data is None:
            raise RuntimeError(f"{url} answered 404.")
        if "error" in data:
            raise RuntimeError(f"The API answered with an error: {data['error'].get('code')}")
        return data

    def head_size(self, url: str) -> int | None:
        """The file size from a HEAD request, or None when the server does not say.

        The request asks for the uncompressed file, so ``Content-Length`` is its full size.
        """
        resp = self._send("HEAD", url, None, stream=False, encoding="identity")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        length = resp.headers.get("Content-Length")
        return int(length) if length is not None else None

    def download(self, url: str, dest: Path | str, expected_size: int | None = None) -> int:
        """Stream ``url`` to ``dest`` once. Refuses to overwrite: raw files are written once."""
        dest = Path(dest)
        if dest.exists():
            raise FileExistsError(f"{dest} exists. Raw files are written once and never replaced.")
        if expected_size is not None:
            self.budget.check_bytes(expected_size)
        family = family_of(urlsplit(url).netloc, urlsplit(url).path)
        resp = self._send("GET", url, None, stream=True)
        when = self.last_when  # the time the request was sent, after the pacing wait
        if resp.status_code != 200:
            self.log.append("GET", url, resp.status_code, 0, when)
            self.budget.record(family, 0)
            resp.raise_for_status()
            raise RuntimeError(f"{url} answered HTTP {resp.status_code}.")
        tmp = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            with tmp.open("xb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if self.budget.bytes_used + total > self.budget.max_bytes:
                        raise CallCapReached("The byte cap was reached during a download.")
                    fh.write(chunk)
        except BaseException:
            tmp.unlink(missing_ok=True)
            self.log.append("GET", url, resp.status_code, total, when)
            self.budget.record(family, total)
            raise
        durable.publish(tmp, dest, read_only=True)
        self.log.append("GET", url, resp.status_code, total, when)
        self.budget.record(family, total)
        return total


def _is_maxlag(resp: Any) -> bool:
    try:
        data = resp.json()
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("error", {}).get("code") == "maxlag"
