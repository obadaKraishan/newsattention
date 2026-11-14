"""Review sheets for checking, by hand, which link is each event's own article.

A sheet is an ``.xlsx`` workbook written with the standard library: a "Guide" tab and an
"Events" tab. Each event takes a block of rows: a first row with its number, date, category
and text, and two dropdowns, then one row per link with its number and its title, which opens
the article on Wikipedia. The dropdowns ask "Which link is the article about this event
itself?" and "Which link is the article about the larger story?", each with "none" and the
link numbers. The event id sits in a hidden column so a filled sheet can be read back.

The sheet is blind: it shows nothing the rule chose and no page views, and the links keep
the order in which the event's text and headings link them.

:func:`check_sheet` reads a filled sheet back (as Excel, LibreOffice, Numbers or Google Sheets
save it) and reports what is missing or invalid by event number, never by title.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

Q1 = "Which link is the article about this event itself?"
Q2 = "Which link is the article about the larger story?"
NONE = "none"
HEADERS = [
    "No.",
    "Date",
    "Category",
    "Event",
    "Link",
    "Article (opens Wikipedia)",
    f"Q1. {Q1}",
    f"Q2. {Q2}",
    "Notes (optional)",
    "id",
]
COLUMNS = "ABCDEFGHIJ"
WIDTHS = [5, 11, 18, 60, 5, 45, 22, 22, 30, 4]

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


GUIDE = [
    "How to fill in this sheet (about 40 minutes for 50 events)",
    "Each block on the Events tab is one event from Wikipedia's Current Events Portal: its date, "
    "its category and its text, then its links, numbered. Click a title to open the article. "
    "For each event, answer the two yellow cells from their dropdowns.",
    "Q1. Which link is the article about this event itself? Choose the article whose subject is "
    "this specific happening: this attack, this earthquake, this election, this court ruling. It "
    "is often new, and its title often names the place and the year. Choose none if no link is "
    "about the event itself, which is common.",
    "Q2. Which link is the article about the larger story? Choose the article about the ongoing "
    "story that this event is one development of: a war, a crisis, a campaign, a series of "
    "protests, a long trial. Choose none if there is no such link. One article cannot answer both "
    "questions.",
    "Everything else is background: a country, a city, a person, a party, a company, a general "
    "topic. Background links are never the answer to either question.",
    "Example 1 (invented). 'A magnitude 6.8 earthquake strikes the coast of Fakeland, killing 40 "
    "people.' Links: 1 Fakeland, 2 2031 Fakeland earthquake, 3 Earthquake. Q1 = 2, Q2 = none.",
    "Example 2 (invented). Under the heading 'Fakeland-Otherland war': 'Otherland's army retakes "
    "the town of Bramble after a two-week siege.' Links: 1 Fakeland-Otherland war, 2 Otherland, "
    "3 Bramble, 4 Siege of Bramble. Q1 = 4, Q2 = 1.",
    "Example 3 (invented). 'Fakeland's parliament passes a law raising the minimum wage.' Links: "
    "1 Parliament of Fakeland, 2 Minimum wage. Q1 = none, Q2 = none: both are background.",
    "When you are unsure: choose none and write a short note in the Notes column (for example "
    "'2 is close but covers the whole week of storms'). A note helps more than a guess. You "
    "do not need to read the articles in full; the title and its first lines are enough.",
    "Do not change the layout: do not insert or delete rows or columns, and keep the file as "
    ".xlsx. You can stop and come back at any time.",
]


@dataclass(frozen=True)
class SheetEvent:
    """One event as the sheet shows it: no rule output, no page views."""

    number: int
    event_id: str
    date: str
    category: str
    text: str
    links: Sequence[str]  # article titles, in link order (1 is the first)


def article_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="()_,'-.:!*;@~")


def _cell(ref: str, value: Any, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>' if style else ""
    if isinstance(value, int):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    text = escape(str(value))
    space = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return f'<c r="{ref}"{s} t="inlineStr"><is><t{space}>{text}</t></is></c>'


def _row(number: int, cells: Iterable[str], height: float | None = None) -> str:
    ht = f' ht="{height}" customHeight="1"' if height else ""
    return f'<row r="{number}"{ht}>{"".join(cells)}</row>'


# Styles: 0 default, 1 bold header, 2 wrapped top-aligned text, 3 hyperlink, 4 answer cell.
_TOP = '<alignment wrapText="1" vertical="top"/>'
STYLES = "".join(
    [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>',
        '<font><b/><sz val="11"/><name val="Calibri"/></font>',
        '<font><u/><color rgb="FF0563C1"/><sz val="11"/><name val="Calibri"/></font></fonts>',
        '<fills count="3"><fill><patternFill patternType="none"/></fill>',
        '<fill><patternFill patternType="gray125"/></fill>',
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/>',
        '<bgColor indexed="64"/></patternFill></fill></fills>',
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>',
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>',
        '</cellStyleXfs><cellXfs count="5">',
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" ',
        f'applyAlignment="1">{_TOP}</xf>',
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" ',
        f'applyAlignment="1">{_TOP}</xf>',
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>',
        '<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFill="1" ',
        'applyAlignment="1"><alignment vertical="top"/></xf>',
        '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>',
        "</cellStyles></styleSheet>",
    ]
)


def _guide_sheet(lines: Sequence[str]) -> str:
    rows = [
        _row(i + 1, [_cell(f"A{i + 1}", line, 1 if i == 0 else 2)]) for i, line in enumerate(lines)
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<cols><col min="1" max="1" width="110" customWidth="1"/></cols>'
        f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
    )


def _events_sheet(events: Sequence[SheetEvent]) -> tuple[str, list[str]]:
    rows = [_row(1, [_cell(f"{c}1", h, 1) for c, h in zip(COLUMNS, HEADERS, strict=True)], 45)]
    validations: list[str] = []
    links: list[tuple[str, str]] = []
    r = 2
    for ev in events:
        choices = ",".join([NONE, *(str(k) for k in range(1, len(ev.links) + 1))])
        rows.append(
            _row(
                r,
                [
                    _cell(f"A{r}", ev.number, 2),
                    _cell(f"B{r}", ev.date, 2),
                    _cell(f"C{r}", ev.category, 2),
                    _cell(f"D{r}", ev.text, 2),
                    _cell(f"G{r}", None, 4),
                    _cell(f"H{r}", None, 4),
                    _cell(f"I{r}", None, 2),
                    _cell(f"J{r}", ev.event_id),
                ],
            )
        )
        for ref in (f"G{r}", f"H{r}"):
            validations.append(
                f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" '
                f'errorTitle="Choose from the list" error="Choose none or a link number." '
                f'sqref="{ref}"><formula1>"{choices}"</formula1></dataValidation>'
            )
        for k, title in enumerate(ev.links, 1):
            r += 1
            rows.append(_row(r, [_cell(f"E{r}", k), _cell(f"F{r}", title, 3)]))
            links.append((f"F{r}", article_url(title)))
        r += 2  # one blank row between events
    hidden = ' hidden="1"'
    cols = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"{hidden if i == 10 else ""}/>'
        for i, w in enumerate(WIDTHS, 1)
    )
    hyper = "".join(
        f'<hyperlink ref="{ref}" r:id="rId{i}"/>' for i, (ref, _) in enumerate(links, 1)
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'xmlns:r="{REL_NS}">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(rows)}</sheetData>"
        f'<dataValidations count="{len(validations)}">{"".join(validations)}</dataValidations>'
        f"<hyperlinks>{hyper}</hyperlinks></worksheet>"
    )
    rels = [
        f'<Relationship Id="rId{i}" Type="{REL_NS}/hyperlink" Target="{escape(url)}" '
        'TargetMode="External"/>'
        for i, (_, url) in enumerate(links, 1)
    ]
    return xml, rels


def write_sheet(path: Path | str, events: Sequence[SheetEvent], guide: Sequence[str]) -> Path:
    """Write one review workbook (a "Guide" tab and an "Events" tab)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    events_xml, link_rels = _events_sheet(events)
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">'
            f'<Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'xmlns:r="{REL_NS}"><bookViews><workbookView activeTab="1"/></bookViews><sheets>'
            '<sheet name="Guide" sheetId="1" r:id="rId1"/>'
            '<sheet name="Events" sheetId="2" r:id="rId2"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">'
            f'<Relationship Id="rId1" Type="{REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{REL_NS}/worksheet" Target="worksheets/sheet2.xml"/>'
            f'<Relationship Id="rId3" Type="{REL_NS}/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/styles.xml": STYLES,
        "xl/worksheets/sheet1.xml": _guide_sheet(guide),
        "xl/worksheets/sheet2.xml": events_xml,
        "xl/worksheets/_rels/sheet2.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">{"".join(link_rels)}</Relationships>'
        ),
    }
    tmp = path.with_name(path.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    tmp.replace(path)
    return path


# Reading a filled sheet back ----------------------------------------------------------------


def _col_row(ref: str) -> tuple[str, int]:
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    if not m:
        raise ValueError(f"unexpected cell reference {ref!r}")
    return m.group(1), int(m.group(2))


def _events_part(zf: zipfile.ZipFile) -> str:
    """The worksheet named "Events" (whatever the program that saved it called the file)."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target", "") for r in rels}
    for sheet in wb.iter(f"{{{NS['m']}}}sheet"):
        if sheet.get("name") == "Events":
            target = targets[sheet.get(f"{{{REL_NS}}}id")].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise ValueError('the workbook has no tab named "Events"')


def read_cells(path: Path | str) -> dict[tuple[str, int], str]:
    """Every non-empty cell of the "Events" tab as text, by (column, row)."""
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter(f"{{{NS['m']}}}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        sheet = ET.fromstring(zf.read(_events_part(zf)))
    out: dict[tuple[str, int], str] = {}
    for c in sheet.iter(f"{{{NS['m']}}}c"):
        kind = c.get("t")
        if kind == "inlineStr":
            value = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
        else:
            v = c.find("m:v", NS)
            if v is None or v.text is None:
                continue
            value = shared[int(v.text)] if kind == "s" else v.text
        value = value.strip()
        if value:
            out[_col_row(c.get("r", ""))] = value
    return out


def _as_choice(value: str | None) -> str | int | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v == NONE:
        return NONE
    try:
        number = float(v)
    except ValueError:
        return value
    return int(number) if number.is_integer() else value


@dataclass
class SheetCheck:
    """What a filled sheet holds, and what is missing or invalid (no titles)."""

    events: int = 0
    complete: int = 0
    answers: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and self.complete == self.events


def check_sheet(path: Path | str) -> SheetCheck:
    """Read a filled sheet back: two valid answers for every event, or what is wrong."""
    cells = read_cells(path)
    starts = sorted(r for (c, r), v in cells.items() if c == "A" and r > 1)
    out = SheetCheck()
    for i, r in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else max(rr for _, rr in cells) + 1
        n_links = sum(1 for (c, rr) in cells if c == "E" and r < rr < nxt)
        number = cells[("A", r)]
        out.events += 1
        answer: dict[str, Any] = {"number": number, "event_id": cells.get(("J", r))}
        fine = True
        for col, name in (("G", "Q1"), ("H", "Q2")):
            raw = cells.get((col, r))
            choice = _as_choice(raw)
            if choice is None:
                out.problems.append(f"event {number}: {name} is not answered")
                fine = False
            elif choice != NONE and not (isinstance(choice, int) and 1 <= choice <= n_links):
                out.problems.append(
                    f"event {number}: {name} must be none or a link number from 1 to {n_links}"
                )
                fine = False
            answer[name] = choice
        if fine and answer["Q1"] != NONE and answer["Q1"] == answer["Q2"]:
            out.problems.append(
                f"event {number}: Q1 and Q2 name the same link; one article cannot be both"
            )
            fine = False
        if answer["event_id"] is None:
            out.problems.append(f"event {number}: its hidden id is missing; was a column deleted?")
            fine = False
        answer["notes"] = cells.get(("I", r), "")
        out.complete += fine
        out.answers.append(answer)
    if not out.events:
        out.problems.append("no events found on the Events tab")
    return out
