"""Scoring the roles rule against the hand-checked review sample.

The sample is stratified (see :mod:`newsattention.review`): each drawn event stands for
``weight`` events of the frame. A share over the frame is the weighted share over the sample,
and its 90% interval comes from a stratified bootstrap: each stratum is resampled on its own,
with replacement, as many events as were drawn from it, and the interval is the 5th and 95th
percentile of the resampled weighted shares.

For each question (``Q1``, the event's own article; ``Q2``, the larger story) the rule's answer
(a link number or ``none``) is right when it equals the hand answer. A difference is one of
three kinds:

- ``rule_link_hand_none``: the rule names a link where the hand answer is none;
- ``hand_link_rule_none``: the hand answer names a link where the rule says none;
- ``different_links``: both name a link, but different ones.

Nothing here reads a title or an event's text. Results name events by sheet and number only,
and the per-event list (:func:`differences`) is written only when asked for.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

NONE = "none"
TARGET = 0.90
LEVEL = 0.90
QUESTIONS = ("Q1", "Q2")
KINDS = ("rule_link_hand_none", "hand_link_rule_none", "different_links")
CONFIDENCES = ("high", "medium", "low", NONE)


@dataclass(frozen=True)
class Scored:
    """One sampled event: its design, the rule's answers and the hand answers."""

    sheet: str
    number: int
    event_id: str
    stratum: str  # "2024-found" or "2024-not-found"
    weight: float
    category: str
    rule: Mapping[str, Any]  # Q1, Q2, Q1_confidence, Q2_confidence, roles
    hand: Mapping[str, Any]  # Q1, Q2, notes

    @property
    def year(self) -> str:
        return self.stratum[:4]

    @property
    def found(self) -> bool:
        return not self.stratum.endswith("not-found")

    def right(self, q: str) -> bool:
        return self.rule[q] == self.hand[q]

    def kind(self, q: str) -> str | None:
        return kind(self.rule[q], self.hand[q])

    def role_of_hand_link(self, q: str) -> str | None:
        """The role the rule gave the link the hand answer names (None for "none")."""
        link = self.hand[q]
        if link == NONE:
            return None
        return str(self.rule["roles"][int(link) - 1][0])

    @property
    def note(self) -> bool:
        return bool(str(self.hand.get("notes") or "").strip())


def kind(rule: Any, hand: Any) -> str | None:
    """The kind of difference between two answers, or None when they agree."""
    if rule == hand:
        return None
    if hand == NONE:
        return "rule_link_hand_none"
    if rule == NONE:
        return "hand_link_rule_none"
    return "different_links"


def weighted_share(rows: Sequence[Scored], hit: Callable[[Scored], bool]) -> float | None:
    total = sum(r.weight for r in rows)
    if not total:
        return None
    return sum(r.weight for r in rows if hit(r)) / total


def bootstrap_interval(
    rows: Sequence[Scored],
    hit: Callable[[Scored], bool],
    reps: int,
    seed: int,
    level: float = LEVEL,
) -> tuple[float, float] | None:
    """The stratified bootstrap interval of the weighted share of ``hit``.

    Within a stratum every event has the same weight, so a resample's weighted share is the
    sum over strata of (the stratum's frame size) times (its resampled share), over the frame.
    """
    if not rows:
        return None
    by: dict[str, list[Scored]] = defaultdict(list)
    for r in rows:
        by[r.stratum].append(r)
    groups = [
        (sum(r.weight for r in members), [hit(r) for r in members])
        for _, members in sorted(by.items())
    ]
    total = sum(w for w, _ in groups)
    rng = random.Random(seed)
    stats = []
    for _ in range(reps):
        s = 0.0
        for w, hits in groups:
            n = len(hits)
            s += w * sum(hits[rng.randrange(n)] for _ in range(n)) / n
        stats.append(s / total)
    stats.sort()
    lo = stats[math.floor((1 - level) / 2 * reps)]
    hi = stats[math.ceil((1 + level) / 2 * reps) - 1]
    return lo, hi


def verdict(interval: tuple[float, float] | None, target: float = TARGET) -> str:
    if interval is None:
        return "no events"
    lo, hi = interval
    if lo >= target:
        return "meets the target: the whole interval is at or above it"
    if hi < target:
        return "below the target: the whole interval is under it"
    return "not settled: the interval contains the target"


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def _share_block(
    rows: Sequence[Scored], hit: Callable[[Scored], bool], reps: int, seed: int
) -> dict[str, Any]:
    interval = bootstrap_interval(rows, hit, reps, seed)
    return {
        "events": len(rows),
        "right_events": sum(1 for r in rows if hit(r)),
        "right_weighted": _r(weighted_share(rows, hit)),
        "interval90": None if interval is None else [_r(interval[0]), _r(interval[1])],
    }


def question_summary(rows: Sequence[Scored], q: str, reps: int, seed: int) -> dict[str, Any]:
    """Every aggregate for one question (no event is named)."""

    def hit(r: Scored) -> bool:
        return r.right(q)

    out = _share_block(rows, hit, reps, seed)
    out["target"] = TARGET
    out["verdict"] = verdict(
        None if out["interval90"] is None else (out["interval90"][0], out["interval90"][1])
    )
    out["by_found"] = {
        label: _share_block([r for r in rows if r.found == flag], hit, reps, seed + k)
        for k, (label, flag) in enumerate((("found", True), ("not found", False)), 1)
    }
    years = sorted({r.year for r in rows})
    out["by_year"] = {
        y: _share_block([r for r in rows if r.year == y], hit, reps, seed + 10 + k)
        for k, y in enumerate(years)
    }
    out["by_stratum"] = {}
    for s in sorted({r.stratum for r in rows}):
        members = [r for r in rows if r.stratum == s]
        right = sum(1 for r in members if hit(r))
        out["by_stratum"][s] = {
            "events": len(members),
            "right_events": right,
            "share": _r(right / len(members)),
            "weight": _r(members[0].weight),
        }
    out["differences"] = {
        k: {
            "events": sum(1 for r in rows if r.kind(q) == k),
            "weighted": _r(weighted_share(rows, lambda r, k=k: r.kind(q) == k)),
        }
        for k in KINDS
    }
    out["by_confidence"] = {}
    for level in CONFIDENCES:
        members = [r for r in rows if (r.rule.get(f"{q}_confidence") or NONE) == level]
        out["by_confidence"][level] = {
            "events": len(members),
            "right_events": sum(1 for r in members if hit(r)),
            "right_weighted": _r(weighted_share(members, hit)),
        }
    roles: dict[str, Counter[str]] = {k: Counter() for k in KINDS[1:]}
    for r in rows:
        k = r.kind(q)
        if k in roles:
            roles[k][r.role_of_hand_link(q) or NONE] += 1
    out["rule_role_of_hand_link"] = {k: dict(sorted(c.items())) for k, c in roles.items()}
    if q == "Q2":

        def among(r: Scored) -> bool:
            return r.right(q) or (r.hand[q] != NONE and r.role_of_hand_link(q) == "story")

        out["hand_link_among_rule_story_pages"] = _share_block(rows, among, reps, seed + 50)
    return out


def summarize(rows: Sequence[Scored], reps: int, seed: int) -> dict[str, Any]:
    """The aggregates for both questions, both together, and the notes."""

    def both(r: Scored) -> bool:
        return r.right("Q1") and r.right("Q2")

    noted = [r for r in rows if r.note]
    return {
        "events": len(rows),
        "frame_events": round(sum(r.weight for r in rows)),
        "bootstrap": {"reps": reps, "seed": seed, "level": LEVEL, "kind": "stratified percentile"},
        "Q1": question_summary(rows, "Q1", reps, seed),
        "Q2": question_summary(rows, "Q2", reps, seed + 100),
        "both_right": _share_block(rows, both, reps, seed + 200),
        "notes": {
            "events_with_note": len(noted),
            "Q1_right_events": sum(1 for r in noted if r.right("Q1")),
            "Q2_right_events": sum(1 for r in noted if r.right("Q2")),
        },
    }


def differences(rows: Iterable[Scored]) -> list[dict[str, Any]]:
    """Each event where the rule and the hand differ: sheet, number, category, kinds (no text)."""
    out = []
    for r in sorted(rows, key=lambda r: (r.sheet, r.number)):
        kinds = {q: r.kind(q) for q in QUESTIONS}
        if not any(kinds.values()):
            continue
        out.append(
            {
                "sheet": r.sheet,
                "number": r.number,
                "stratum": r.stratum,
                "category": r.category,
                "note": r.note,
                **{
                    f"{q}_{name}": value
                    for q in QUESTIONS
                    for name, value in (
                        ("difference", kinds[q] or "same"),
                        ("rule_confidence", r.rule.get(f"{q}_confidence") or NONE),
                        ("rule_role_of_hand_link", r.role_of_hand_link(q) if kinds[q] else None),
                    )
                },
            }
        )
    return out


def join(
    design: Sequence[Mapping[str, Any]],
    key: Sequence[Mapping[str, Any]],
    answers: Sequence[Mapping[str, Any]],
    categories: Mapping[str, str],
) -> list[Scored]:
    """One :class:`Scored` per design event; every event must have a key and a hand answer.

    Events are matched by id, and the sheet and number must agree in all three, so a sheet
    whose rows were moved or a key for another sample is refused.
    """
    by_key = {k["event_id"]: k for k in key}
    by_answer = {a["event_id"]: a for a in answers}
    out = []
    for d in design:
        eid, where = d["event_id"], f"{d['sheet']} event {d['number']}"
        k, a = by_key.get(eid), by_answer.get(eid)
        if k is None:
            raise ValueError(f"{where}: the answer key has no entry for this event")
        if a is None:
            raise ValueError(f"{where}: no filled sheet holds this event (hidden column J)")
        for name, other in (("answer key", k), ("filled sheet", a)):
            if (other["sheet"], int(other["number"])) != (d["sheet"], int(d["number"])):
                raise ValueError(
                    f"{where}: the {name} has it as {other['sheet']} event {other['number']}"
                )
        out.append(
            Scored(
                sheet=d["sheet"],
                number=int(d["number"]),
                event_id=eid,
                stratum=d["stratum"],
                weight=float(d["weight"]),
                category=categories.get(eid, ""),
                rule=k,
                hand=a,
            )
        )
    if len(by_answer) != len(out):
        raise ValueError(
            f"the filled sheets hold {len(by_answer)} events, the design {len(out)}: "
            "were sheets from another sample given?"
        )
    return out
