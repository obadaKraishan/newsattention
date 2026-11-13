"""Per-article daily page views from the Wikimedia Analytics API.

``GET https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/{access}/
{agent}/{article}/daily/{start}/{end}`` returns exact counts, one item per day with views.
Days with no views are left out of the answer, so :func:`daily_views` fills them in with zero
up to the last day that is known to be complete. A page with no views at all in the range
answers 404.

NewsAttention asks for ``all-access`` and the ``user`` agent (people, not bots or crawlers).
Every call goes through :class:`~newsattention.client.WikimediaClient`, so it is logged and
counts against the Analytics call cap.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from newsattention.client import WikimediaClient

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
ACCESS = "all-access"
AGENT = "user"


def per_article_url(
    project: str,
    title: str,
    start: date,
    end: date,
    access: str = ACCESS,
    agent: str = AGENT,
) -> str:
    """The request URL. The title is URL-encoded with spaces as underscores, slashes encoded."""
    article = quote(title.replace(" ", "_"), safe="")
    return (
        f"{API}/per-article/{project}/{access}/{agent}/{article}/daily/"
        f"{start:%Y%m%d}00/{end:%Y%m%d}00"
    )


def daily_views(
    client: WikimediaClient,
    project: str,
    title: str,
    start: date,
    end: date,
    complete_until: date | None = None,
) -> dict[date, int]:
    """Views per day from ``start`` to ``end``, with zeros for days the API leaves out.

    Zeros are filled in only up to ``complete_until`` (default ``end``), the last day whose
    data is known to be complete; later days without an item are left out.
    """
    data = client.get_json(per_article_url(project, title, start, end))
    found: dict[date, int] = {}
    for item in (data or {}).get("items", []):
        stamp = item["timestamp"]
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        found[day] = int(item["views"])
    last = min(end, complete_until or end)
    day = start
    while day <= last:
        found.setdefault(day, 0)
        day += timedelta(days=1)
    return dict(sorted(found.items()))
