"""Article titles to Wikidata ids, and Wikidata ids to the titles in other languages.

Two steps, both in batches of 50:

1. :func:`resolve_titles` asks the wiki's own Action API for each title's canonical form
   (after normalization and redirects), its page id and its Wikidata id (``wikibase_item``).
   This is a call to the Wikipedia API, not to Wikidata.
2. :func:`sitelinks` asks Wikidata's ``wbgetentities`` for the Wikipedia titles of each item
   in every language.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from newsattention.client import WikimediaClient

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
BATCH = 50

#: Wikidata site ids that end in "wiki" but are not language editions of Wikipedia.
NOT_WIKIPEDIA = {
    "commonswiki", "foundationwiki", "incubatorwiki", "mediawikiwiki", "metawiki",
    "outreachwiki", "sourceswiki", "specieswiki", "testwiki", "test2wiki", "wikidatawiki",
    "wikifunctionswiki", "wikimaniawiki", "wikimaniateamwiki", "testwikidatawiki",
}  # fmt: skip

#: Site ids whose Wikipedia domain is not the site id with "_" turned into "-".
SITE_DOMAIN_EXCEPTIONS = {
    "be_x_oldwiki": "be-tarask",
    "zh_min_nanwiki": "zh-min-nan",
    "zh_classicalwiki": "zh-classical",
    "zh_yuewiki": "zh-yue",
    "roa_rupwiki": "roa-rup",
    "map_bmswiki": "map-bms",
    "nds_nlwiki": "nds-nl",
    "fiu_vrowiki": "fiu-vro",
    "bat_smgwiki": "bat-smg",
    "cbk_zamwiki": "cbk-zam",
    "roa_tarawiki": "roa-tara",
}


@dataclass(frozen=True)
class Resolved:
    """What a linked title points to."""

    linked_title: str
    title: str
    page_id: int | None
    qid: str | None
    redirected: bool

    @property
    def missing(self) -> bool:
        return self.page_id is None


def project_for_site(site: str) -> str | None:
    """``dewiki`` -> ``de.wikipedia``; None for sites that are not Wikipedias."""
    if not site.endswith("wiki") or site in NOT_WIKIPEDIA:
        return None
    if site in SITE_DOMAIN_EXCEPTIONS:
        return f"{SITE_DOMAIN_EXCEPTIONS[site]}.wikipedia"
    code = site[: -len("wiki")]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", code):
        return None
    return f"{code.replace('_', '-')}.wikipedia"


def api_for_project(project: str) -> str:
    """``en.wikipedia`` -> ``https://en.wikipedia.org/w/api.php``."""
    return f"https://{project}.org/w/api.php"


def _batches(items: list[str], size: int = BATCH) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def resolve_titles(
    client: WikimediaClient, titles: Iterable[str], project: str = "en.wikipedia"
) -> dict[str, Resolved]:
    """Canonical title, page id and Wikidata id for each linked title."""
    unique = list(dict.fromkeys(titles))
    out: dict[str, Resolved] = {}
    for chunk in _batches(unique):
        data = client.action_api(
            api_for_project(project),
            {
                "action": "query",
                "titles": "|".join(chunk),
                "redirects": "1",
                "prop": "pageprops",
                "ppprop": "wikibase_item",
            },
        )
        query = data.get("query", {})
        normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
        redirects = {r["from"]: r["to"] for r in query.get("redirects", [])}
        pages = {p["title"]: p for p in query.get("pages", [])}
        for linked in chunk:
            title = normalized.get(linked, linked)
            redirected = False
            hops = 0
            while title in redirects and hops < 5:
                title = redirects[title]
                redirected = True
                hops += 1
            page = pages.get(title, {})
            if page.get("missing") or page.get("invalid") or "pageid" not in page:
                out[linked] = Resolved(linked, title, None, None, redirected)
                continue
            qid = page.get("pageprops", {}).get("wikibase_item")
            out[linked] = Resolved(linked, page["title"], page["pageid"], qid, redirected)
    return out


def sitelinks(client: WikimediaClient, qids: Iterable[str]) -> dict[str, dict[str, str]]:
    """For each Wikidata id, ``{project: title}`` over every Wikipedia that has the article."""
    unique = list(dict.fromkeys(qids))
    out: dict[str, dict[str, str]] = {}
    for chunk in _batches(unique):
        data = client.action_api(
            WIKIDATA_API,
            {"action": "wbgetentities", "ids": "|".join(chunk), "props": "sitelinks"},
        )
        for qid, entity in data.get("entities", {}).items():
            if "missing" in entity:
                continue
            links: dict[str, str] = {}
            for site, link in entity.get("sitelinks", {}).items():
                project = project_for_site(site)
                if project:
                    links[project] = link["title"]
            out[qid] = links
    return out


def titles_for_page_ids(
    client: WikimediaClient, project: str, page_ids: Iterable[int]
) -> dict[int, tuple[str, str | None]]:
    """Current title and Wikidata id of page ids on one wiki (that wiki's own API)."""
    unique = [str(pid) for pid in dict.fromkeys(page_ids)]
    out: dict[int, tuple[str, str | None]] = {}
    for chunk in _batches(unique):
        data = client.action_api(
            api_for_project(project),
            {
                "action": "query",
                "pageids": "|".join(chunk),
                "prop": "pageprops",
                "ppprop": "wikibase_item",
            },
        )
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing") or "pageid" not in page:
                continue
            out[page["pageid"]] = (page["title"], page.get("pageprops", {}).get("wikibase_item"))
    return out
