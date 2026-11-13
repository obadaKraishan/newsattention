"""Read English Wikipedia's Current Events Portal, one day page at a time.

A day page (``Portal:Current events/2026 November 11``) lists the day's events under fixed
headings such as "Armed conflicts and attacks". Events are bullets; a bullet that has
sub-bullets and cites no source is a story heading (for example a link to an ongoing war),
and the bullets under it are its events. An event ends with its news sources as external
links.

The page is read as wikitext through the MediaWiki Action API, with its revision id, so every
event can be credited to the exact revision it came from. Two layouts are handled: the
current one (``'''Heading'''`` lines after the ``{{Current events}}`` header) and the older
one (``;Heading`` lines inside the template's ``content=`` parameter).
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

from newsattention.client import WikimediaClient
from newsattention.schema import DOMAIN_RE, Event, date_of_portal_page, portal_page_for

ENWIKI_API = "https://en.wikipedia.org/w/api.php"
UNCATEGORIZED = "Uncategorized"

#: The headings in use on current day pages.
KNOWN_CATEGORIES = (
    "Armed conflicts and attacks",
    "Arts and culture",
    "Business and economy",
    "Disasters and accidents",
    "Health and environment",
    "International relations",
    "Law and crime",
    "Politics and elections",
    "Science and technology",
    "Sports",
)

#: Link prefixes that are not articles (namespaces and interwiki prefixes), lowercase.
NON_ARTICLE_PREFIXES = {
    "b", "c", "cat", "category", "commons", "d", "draft", "file", "foundation", "h", "help",
    "image", "m", "media", "meta", "module", "mos", "mw", "n", "p", "phab", "portal", "q", "s",
    "special", "species", "t", "talk", "template", "user", "user talk", "v", "voy", "w", "wikt",
    "wikibooks", "wikidata", "wikinews", "wikipedia", "wikiquote", "wikisource", "wikiversity",
    "wikivoyage", "wiktionary", "wmf", "wp",
}  # fmt: skip

#: Templates whose output is not part of the sentence.
DROP_TEMPLATES = {
    "citation needed", "cn", "clarify", "efn", "flag icon", "flagdeco", "flagicon", "refn",
    "sfn", "update", "when", "better source needed", "dead link", "failed verification",
}  # fmt: skip

LINK_RE = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
EXTLINK_RE = re.compile(r"\[((?:https?:)?//[^\s\]]+)(?:\s+[^\]]*)?\]")
TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
HEADING_RES = (
    re.compile(r"^'''\s*([^'*][^']*?)\s*'''\s*$"),
    re.compile(r"^;\s*(.+?)\s*$"),
    re.compile(r"^=+\s*(.+?)\s*=+\s*$"),
)
BULLET_RE = re.compile(r"^(\*+)\s*(.*)$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
REF_RE = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
LANG_PREFIX_RE = re.compile(r"^[a-z]{2,3}(-[a-z]+)*$")


@dataclass(frozen=True)
class PortalPage:
    """One day page as read from the API."""

    title: str
    day: date
    page_id: int | None
    revision_id: int | None
    revision_time: str | None
    wikitext: str | None

    @property
    def missing(self) -> bool:
        return self.revision_id is None


@dataclass(frozen=True)
class ParsedEvent:
    category: str
    text: str
    depth: int
    links: tuple[str, ...]
    story_links: tuple[str, ...]
    source_urls: tuple[str, ...]
    source_domains: tuple[str, ...]


@dataclass(frozen=True)
class ParsedLink:
    event_id: str
    title: str
    link_order: int
    in_text: bool


def normalize_title(target: str) -> str | None:
    """An article title as MediaWiki stores it, or None for links that are not articles."""
    raw = html.unescape(target).replace("_", " ").replace("\u00a0", " ")
    raw = raw.split("#", 1)[0]
    raw = re.sub(r"\s+", " ", raw).strip()
    if raw.startswith(":"):
        raw = raw[1:].strip()
    if not raw:
        return None
    if ":" in raw:
        prefix = raw.split(":", 1)[0].strip()
        if prefix.lower() in NON_ARTICLE_PREFIXES or LANG_PREFIX_RE.match(prefix):
            return None
    return raw[0].upper() + raw[1:]


def domain_of(url: str) -> str | None:
    """The news site's domain for a cited URL, without ``www.``; archive links are unwrapped."""
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if host.endswith("archive.org") and "/web/" in parts.path:
        match = re.search(
            r"/web/[^/]*/(.+)$", parts.path + (f"?{parts.query}" if parts.query else "")
        )
        if match:
            inner = match.group(1)
            if not re.match(r"^https?://", inner):
                inner = "https://" + inner.lstrip("/")
            return domain_of(inner)
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix) :]
            break
    return host if DOMAIN_RE.match(host) else None


def _render_template(body: str) -> str:
    parts = [p.strip() for p in body.split("|")]
    name = parts[0].lower().replace("_", " ")
    args = [p for p in parts[1:] if "=" not in p]
    if name in DROP_TEMPLATES or name.startswith("flag"):
        return ""
    if name in {"ship", "warship", "sclass"}:
        return " ".join(a for a in args[:2] if a)
    if name in {"convert", "cvt"}:
        return " ".join(args[:2])
    if name == "lang":
        return args[-1] if args else ""
    if name.startswith("lang-") or name in {"ill", "interlanguage link", "w", "abbr"}:
        return args[0] if args else ""
    return " ".join(a for a in args if a)


def render_text(raw: str) -> str:
    """Plain text of one bullet: links become their labels, sources and markup are removed."""
    text = LINK_RE.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), raw)
    text = EXTLINK_RE.sub("", text)
    for _ in range(5):
        new = TEMPLATE_RE.sub(lambda m: _render_template(m.group(1)), text)
        if new == text:
            break
        text = new
    text = text.replace("'''", "").replace("''", "")
    text = TAG_RE.sub("", text)
    text = html.unescape(text).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text


def _links(raw: str) -> list[str]:
    out: list[str] = []
    for match in LINK_RE.finditer(raw):
        title = normalize_title(match.group(1))
        if title and title not in out:
            out.append(title)
    return out


def _sources(raw: str) -> tuple[list[str], list[str]]:
    urls = [m.group(1) for m in EXTLINK_RE.finditer(raw)]
    domains: list[str] = []
    for url in urls:
        dom = domain_of(url)
        if dom and dom not in domains:
            domains.append(dom)
    return urls, domains


def _heading(line: str) -> str | None:
    for pattern in HEADING_RES:
        match = pattern.match(line)
        if match:
            text = render_text(match.group(1))
            return text or None
    return None


def _content_lines(wikitext: str) -> list[str]:
    text = REF_RE.sub("", COMMENT_RE.sub("", wikitext))
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("{{current events"):
            if "content=" not in line:
                continue
            line = line.split("content=", 1)[1].strip()
        if line.endswith("}}") and line.count("{{") < line.count("}}"):
            line = line[:-2].rstrip().rstrip("|").rstrip()
        if line:
            lines.append(line)
    return lines


def parse_wikitext(wikitext: str) -> list[ParsedEvent]:
    """All events on a day page, in page order."""
    category = UNCATEGORIZED
    items: list[tuple[int, str, str]] = []
    for line in _content_lines(wikitext):
        bullet = BULLET_RE.match(line)
        if bullet:
            if bullet.group(2).strip():
                items.append((len(bullet.group(1)), bullet.group(2), category))
            continue
        heading = _heading(line)
        if heading:
            category = heading
    events: list[ParsedEvent] = []
    story: list[tuple[int, list[str]]] = []
    for i, (depth, raw, cat) in enumerate(items):
        while story and story[-1][0] >= depth:
            story.pop()
        urls, domains = _sources(raw)
        has_children = i + 1 < len(items) and items[i + 1][0] > depth
        if has_children and not urls:
            story.append((depth, _links(raw)))
            continue
        text = render_text(raw)
        if not text:
            continue
        story_links: list[str] = []
        for _, links in reversed(story):
            story_links.extend(t for t in links if t not in story_links)
        events.append(
            ParsedEvent(
                category=cat,
                text=text,
                depth=depth,
                links=tuple(_links(raw)),
                story_links=tuple(story_links),
                source_urls=tuple(urls),
                source_domains=tuple(domains),
            )
        )
    return events


def event_id_for(day: date, event: ParsedEvent) -> str:
    """``<date>-<8 hex>``: a hash of the first cited source, or of the text when none is cited.

    Editors reword events more often than they replace sources, so the first source keeps the
    id stable across most later edits.
    """
    key = event.source_urls[0] if event.source_urls else event.text
    return f"{day.isoformat()}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}"


def build_events(page: PortalPage, retrieved_at: datetime) -> tuple[list[Event], list[ParsedLink]]:
    """Events and their links for one day page. Story links follow the event's own links."""
    if page.missing or page.wikitext is None or page.revision_id is None:
        return [], []
    events: list[Event] = []
    links: list[ParsedLink] = []
    seen: dict[str, int] = {}
    for parsed in parse_wikitext(page.wikitext):
        base = event_id_for(page.day, parsed)
        seen[base] = seen.get(base, 0) + 1
        event_id = base if seen[base] == 1 else f"{base}-{seen[base]}"
        events.append(
            Event(
                event_id=event_id,
                date=page.day,
                category=parsed.category,
                text=parsed.text,
                portal_page=page.title,
                revision_id=page.revision_id,
                source_domains=list(parsed.source_domains),
                story_titles=list(parsed.story_links),
                depth=parsed.depth,
                retrieved_at=retrieved_at,
            )
        )
        order = 0
        for title in parsed.links:
            order += 1
            links.append(ParsedLink(event_id, title, order, True))
        for title in parsed.story_links:
            if title in parsed.links:
                continue
            order += 1
            links.append(ParsedLink(event_id, title, order, False))
    return events, links


def fetch_pages(
    client: WikimediaClient,
    days: Iterable[date],
    api: str = ENWIKI_API,
    batch: int = 50,
) -> list[PortalPage]:
    """Read the latest revision of each day page, up to ``batch`` pages per request."""
    wanted = [portal_page_for(day) for day in days]
    out: list[PortalPage] = []
    for start in range(0, len(wanted), batch):
        chunk: Sequence[str] = wanted[start : start + batch]
        data = client.action_api(
            api,
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "ids|timestamp|content",
                "rvslots": "main",
                "titles": "|".join(chunk),
            },
        )
        by_title = {p["title"]: p for p in data.get("query", {}).get("pages", [])}
        for title in chunk:
            page = by_title.get(title, {"title": title, "missing": True})
            day = date_of_portal_page(title)
            if page.get("missing") or not page.get("revisions"):
                out.append(PortalPage(title, day, None, None, None, None))
                continue
            rev = page["revisions"][0]
            out.append(
                PortalPage(
                    title=title,
                    day=day,
                    page_id=page.get("pageid"),
                    revision_id=rev["revid"],
                    revision_time=rev.get("timestamp"),
                    wikitext=rev["slots"]["main"]["content"],
                )
            )
    return out
