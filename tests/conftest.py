"""Shared fakes. Tests never touch the network: HTTP goes to a FakeSession."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import pytest
import requests

from newsattention.client import Budget, UsageLog, WikimediaClient


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        body: Any = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        url: str = "",
    ) -> None:
        self.status_code = status
        self.headers = headers or {}
        self.url = url
        if content is not None:
            self.content = content
        elif body is None:
            self.content = b""
        else:
            self.content = json.dumps(body).encode()

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.content)

    def iter_content(self, chunk_size: int = 1) -> Any:
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self  # type: ignore[assignment]
            raise err


Handler = Callable[[str, str, dict[str, Any], dict[str, str]], FakeResponse]


class FakeSession:
    """Answers each request with ``handler(method, url, params, headers)``."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        stream: bool = False,
    ) -> FakeResponse:
        params = dict(params or {})
        headers = dict(headers or {})
        self.calls.append((method, url, params, headers))
        resp = self.handler(method, url, params, headers)
        if not resp.url:
            resp.url = url + (("?" + urlencode(params)) if params else "")
        return resp


@pytest.fixture
def make_client(tmp_path: Any) -> Callable[..., tuple[WikimediaClient, FakeSession]]:
    def make(handler: Handler, budget: Budget | None = None, **kwargs: Any) -> Any:
        session = FakeSession(handler)
        sleeps: list[float] = []
        client = WikimediaClient(
            UsageLog(tmp_path / "usage_log.csv"),
            budget=budget,
            session=session,
            sleep=sleeps.append,
            clock=lambda: "2026-11-13T15:00:00Z",
            **kwargs,
        )
        client.sleeps = sleeps  # type: ignore[attr-defined]
        return client, session

    return make
