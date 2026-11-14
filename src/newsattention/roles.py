"""The role of each linked page: the event's own article, the larger story, or context.

A rule, not a model. For every link of every event it reads stored signals and gives one role:

- ``event``: the article about this specific happening (at most one per event);
- ``story``: an article about the larger ongoing story the event is a development of;
- ``context``: anything else (a country, a person, an organization, a general topic).

The signals, for one event and one linked page:

- ``new``: the page was created in the 14 days before the event or later, or moved into the
  articles (from a draft) within 14 days of the event.
- ``event_class`` / ``context_class``: the page's Wikidata class, judged by the head word of the
  class's English label ("mass shooting" -> shooting -> an event; "city in Fakeland" -> city ->
  context). The item's own classes decide; when none of their head words is known, their
  superclasses decide, then the superclasses of those.
- ``year``: the title holds the event's year (or a season such as 2025-26 that spans it).
- ``words``: the title shares a word with the event's text and has more than that one word.
- ``jump``: views on day 0 or day 1 at least 5 times the baseline, or, with no baseline of 10
  views, a peak of at least 500 views by day 3.
- ``in_text``: the event's own text links the page (not a story heading above it).

The rule:

1. A page with a context class is ``context``.
2. A page the event's text links can be ``event`` when it is ``new``, or has an event class and
   the event's year, or has the year, the words and a jump. Of several, the one with the most
   signals wins (then the earlier link).
3. Every other page that a story heading links, or that has an event class and is not new, is
   ``story``.
4. The rest is ``context``.

Confidence counts the signals that agree with the role: for ``event`` among new (counted
twice), event class, year, words and jump (4 or more high, 3 medium, else low); for ``story``
among story heading, nearest heading, event class and old page (3 or more high, 2 medium,
else low); for ``context`` a context class is high, an old page without an event class medium,
anything else low.

The rule is fixed as :data:`RULE_VERSION` before the hand-checked sample is drawn.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

RULE_VERSION = "1"


def _words(text: str) -> list[str]:
    return text.split()


NEW_DAYS = 14
OLD_DAYS = 30
JUMP_LIFT = 5.0
JUMP_PEAK_VIEWS = 500
JUMP_PEAK_DAY = 3

#: Head words of class labels that name a happening.
EVENT_HEADS = frozenset(
    _words(
        """
    occurrence event events incident incidents accident accidents disaster disasters catastrophe
    attack attacks bombing bombings shooting shootings stabbing massacre massacres killing
    killings murder murders homicide assassination kidnapping abduction hijacking crime crimes
    war wars battle battles siege offensive invasion operation conflict insurgency uprising
    rebellion revolution coup skirmish clash clashes raid airstrike airstrikes strike strikes
    protest protests demonstration demonstrations riot riots unrest election elections referendum
    by-election primary primaries caucus inauguration summit conference ceremony visit
    negotiations talks trial case lawsuit scandal investigation impeachment earthquake
    earthquakes tsunami eruption storm storms cyclone hurricane typhoon tornado tornadoes flood
    floods flooding landslide wildfire wildfires fire fires wave drought avalanche blizzard crash
    crashes collision derailment explosion explosions sinking shipwreck collapse spill outage
    blackout pandemic epidemic outbreak crisis famine tournament championship championships
    season match race prix olympics games festival contest competition launch spaceflight
    flight mission landing execution shutdown campaign genocide persecution pogrom evacuation
    deportation ruling verdict sentencing hearing debate funeral wedding coronation abdication
    resignation dismissal merger acquisition bankruptcy default recession boycott sanctions
    ceasefire truce blockade occupation annexation secession independence
    """
    )
)

#: Head words of class labels that name a thing, place, person or idea.
CONTEXT_HEADS = frozenset(
    _words(
        """
    human person people country state nation city town village municipality capital region
    province district county territory island archipelago river mountain lake sea ocean
    peninsula continent area neighborhood neighbourhood settlement commune prefecture oblast
    governorate republic kingdom emirate organization organisation company business enterprise
    corporation conglomerate agency ministry department government party parliament legislature
    assembly court army forces unit militia group union club team federation association
    university school college hospital newspaper broadcaster network channel website platform
    software product brand ship vessel aircraft airline airport station bridge building stadium
    mosque church temple dam plant facility prison religion ideology movement language office
    position title profession occupation film album song book novel series work species taxon
    disease chemical compound drug medication vaccine virus award prize name concept discipline
    technology weapon missile rifle currency index exchange politician
    """
    )
)

PREPOSITIONS = {"of", "in", "for", "by", "at", "on", "to", "from", "with", "within", "during"}
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})(?:[\u2013-](\d{2,4}))?\b")
WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
STOPWORDS = frozenset(
    _words(
        """
    the and that this with from into over after before their there they them were was have has
    been being which while where when what about against between during under above below more
    most some such than then also other others into upon would could should said says will
    january february march april may june july august september october november december
    """
    )
)


def head_word(label: str | None) -> str | None:
    """The head word of a class label: the last word before the first preposition."""
    if not label:
        return None
    words = label.lower().replace("(", " ").replace(")", " ").split()
    head: list[str] = []
    for w in words:
        if w in PREPOSITIONS:
            break
        head.append(w)
    if not head:
        return None
    last = head[-1].strip(",.;:")
    if len(head) >= 2 and f"{head[-2]} {last}" == "grand prix":
        return "prix"
    return last


def class_kind(
    item_classes: Iterable[str], classes: Mapping[str, Mapping[str, Any]], tiers: int = 3
) -> tuple[str | None, str | None]:
    """``("event" | "context" | None, the deciding label)`` for one item's classes."""
    tier = list(dict.fromkeys(item_classes))
    seen: set[str] = set()
    for _ in range(tiers):
        event_label = context_label = None
        for cid in tier:
            info = classes.get(cid) or {}
            head = head_word(info.get("label"))
            if head in EVENT_HEADS and event_label is None:
                event_label = info.get("label")
            elif head in CONTEXT_HEADS and context_label is None:
                context_label = info.get("label")
        if event_label or context_label:
            # A class that names a happening wins over one that names a thing at the same tier:
            # an item that is both an "election" and a "process" is an election.
            return ("event", event_label) if event_label else ("context", context_label)
        seen.update(tier)
        tier = [
            s
            for cid in tier
            for s in (classes.get(cid) or {}).get("subclass_of", [])
            if s not in seen
        ]
        if not tier:
            break
    return None, None


def years_in(title: str) -> set[int]:
    """Years a title names, with seasons such as 2025-26 counted for both years."""
    out: set[int] = set()
    for m in YEAR_RE.finditer(title):
        first = int(m.group(1))
        out.add(first)
        if m.group(2):
            tail = m.group(2)
            second = int(tail) if len(tail) == 4 else (first // 100) * 100 + int(tail)
            if first < second <= first + 2:
                out.update(range(first, second + 1))
    return out


def content_words(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(text.lower()) if len(w) >= 4 and w not in STOPWORDS}


@dataclass(frozen=True)
class Signals:
    new: bool
    event_class: bool
    context_class: bool
    year: bool
    words: bool
    jump: bool
    in_text: bool
    story_level: int | None
    old: bool

    def event_score(self) -> int:
        return 2 * self.new + self.event_class + self.year + self.words + self.jump


@dataclass(frozen=True)
class PageFacts:
    """What is stored about one linked page."""

    created: date | None
    into_articles: tuple[date, ...]  # days the page moved into the articles from elsewhere
    kind: str | None  # "event", "context" or None, from its Wikidata classes


def signals(
    event_day: date,
    event_text: str,
    link: Mapping[str, Any],
    facts: PageFacts | None,
    summary: Mapping[str, Any] | None,
) -> Signals:
    created = facts.created if facts else None
    window = timedelta(days=NEW_DAYS)
    new = bool(
        (created is not None and created >= event_day - window)
        or (facts and any(abs((d - event_day).days) <= NEW_DAYS for d in facts.into_articles))
    )
    old = created is not None and created < event_day - timedelta(days=OLD_DAYS) and not new
    title = link.get("page_title") or ""
    title_words = content_words(title)
    year = event_day.year in years_in(title)
    words = bool(title_words & content_words(event_text)) and len(title_words) >= 2
    jump = False
    if summary:
        lifts = [x for x in (summary.get("lift_day0"), summary.get("lift_day1")) if x is not None]
        base = summary.get("baseline")
        if lifts and max(lifts) >= JUMP_LIFT:
            jump = True
        elif (base is None or base < 10) and (summary.get("peak_views") or 0) >= JUMP_PEAK_VIEWS:
            jump = (summary.get("peak_day") or 99) <= JUMP_PEAK_DAY
    kind = facts.kind if facts else None
    return Signals(
        new=new,
        event_class=kind == "event",
        context_class=kind == "context",
        year=year,
        words=words,
        jump=jump,
        in_text=bool(link.get("in_text")),
        story_level=link.get("story_level"),
        old=old,
    )


def _level(count: int, high: int, medium: int) -> str:
    return "high" if count >= high else "medium" if count >= medium else "low"


def assign(links: list[Mapping[str, Any]], sigs: list[Signals]) -> list[tuple[str, str]]:
    """``(role, confidence)`` for each link of one event, in link order."""
    out: list[tuple[str, str] | None] = [None] * len(links)
    candidates = []
    for k, s in enumerate(sigs):
        if s.context_class:
            out[k] = ("context", "high")
            continue
        if s.in_text and (s.new or (s.event_class and s.year) or (s.year and s.words and s.jump)):
            candidates.append((-s.event_score(), links[k].get("link_order", k + 1), k))
    if candidates:
        k = min(candidates)[2]
        out[k] = ("event", _level(sigs[k].event_score(), 4, 3))
    for k, s in enumerate(sigs):
        if out[k] is not None:
            continue
        heading = not s.in_text
        if heading or (s.event_class and not s.new):
            count = heading + (s.story_level == 1) + s.event_class + s.old
            out[k] = ("story", _level(count, 3, 2))
        elif s.old and not s.event_class:
            out[k] = ("context", "medium")
        else:
            out[k] = ("context", "low")
    return [o for o in out if o is not None]


def main_story(links: list[Mapping[str, Any]], roles: list[tuple[str, str]]) -> int | None:
    """The link number of the event's main story: the nearest heading, else the best in-text one."""
    order = {"high": 0, "medium": 1, "low": 2}
    best = None
    for link, (role, conf) in zip(links, roles, strict=True):
        if role != "story":
            continue
        key = (link.get("story_level") or 99, order[conf], link["link_order"])
        if best is None or key < best[0]:
            best = (key, link["link_order"])
    return best[1] if best else None


def summarize(
    events: Mapping[str, Mapping[str, Any]], roles: Mapping[str, list[tuple[str, str]]]
) -> dict[str, Any]:
    """Shares of roles and confidences, by year and category, and events by what they have."""
    by_role: Counter[str] = Counter()
    by_conf: Counter[tuple[str, str]] = Counter()
    by_year: dict[str, Counter[str]] = defaultdict(Counter)
    by_cat: dict[str, Counter[str]] = defaultdict(Counter)
    has: Counter[str] = Counter()
    for eid, rs in roles.items():
        ev = events.get(eid, {})
        year, cat = eid[:4], ev.get("category", "")
        kinds = {r for r, _ in rs}
        for r, c in rs:
            by_role[r] += 1
            by_conf[(r, c)] += 1
            by_year[year][r] += 1
        label = (
            "both"
            if {"event", "story"} <= kinds
            else "event only"
            if "event" in kinds
            else "story only"
            if "story" in kinds
            else "neither"
        )
        has[label] += 1
        by_cat[cat][label] += 1
        by_year[year][f"events: {label}"] += 1
    return {
        "rule_version": RULE_VERSION,
        "links": sum(by_role.values()),
        "roles": dict(by_role.most_common()),
        "confidence": {f"{r} {c}": n for (r, c), n in sorted(by_conf.items())},
        "events": sum(has.values()),
        "events_have": dict(has.most_common()),
        "by_year": {y: dict(c) for y, c in sorted(by_year.items())},
        "by_category": {
            k: dict(c) for k, c in sorted(by_cat.items(), key=lambda x: -sum(x[1].values()))
        },
    }
