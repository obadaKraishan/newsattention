# Method

**The measures in section 2 are accepted. The roles of linked pages (section 4) are still a
DRAFT until the hand check is scored.** Numbers marked "prototype" come from a 28-day sample
(portal days 2026-10-16 to 2026-11-12); numbers marked "version 1" come from the backfill from
2023-02-06.

## 1. Units
- **Event:** one bullet on an English Current Events Portal day page that reports something
  that happened, under one of the portal's headings ("Armed conflicts and attacks", "Politics
  and elections" and so on). A bullet that has sub-bullets and cites no source is a *story
  heading* (for example a link to an ongoing war), not an event; its links are kept as the
  event's *story links*. Each event keeps the page name and the revision id it was read from.
- **Event page:** one article an event links to, after redirects, with its page id and its
  Wikidata id. Links in the event's own text come first (in reading order), then the story
  links, nearest heading first. The role of each page (the event's own article, or a general
  page such as a country, a party or a war) is decided by a rule (section 4).
- **Day:** a UTC calendar day, as used by both Wikimedia sources. The event day is the portal
  page's date, which is the date the editors file the event under (usually the day it
  happened, sometimes the day it was reported).
- **Language** (exact counts): daily views of the page in one language edition, from the
  Analytics API, all access methods, human readers only (`agent=user`).
- **Country** (noisy counts): daily views of the page in one language edition from one country,
  from Wikimedia's differentially private files.

An item is followed across languages through its Wikidata id: the English page of an event and
its German page are the same item in two languages.

## 2. Measures
All language measures are computed per event, item and language edition, from Analytics API
counts (exact). The country measure is computed per event, item, language and country, from
Wikimedia's differentially private counts as published.

| Measure | Definition | Notes |
|---|---|---|
| Baseline | Median daily views over days -28 to -1 | All 28 days needed (four full weeks, so weekdays balance). The series start 28 days before 2023-02-06, so every version 1 event has a full baseline window |
| Lift | Views on a day divided by the baseline | Only when the baseline is at least 10 views a day (the floor); below it a handful of views gives absurd ratios (the prototype had lifts up to 234,024) |
| Excess views | Sum over days 0 to 7, and 0 to 28, of (views minus baseline) | Empty when the data end before day 7 or day 28 |
| Peak day | The day from 0 to 28 with the most views (the earliest on ties) | Days since the event |
| Half-life | Days from the peak until views first fall below half the peak | Censored (empty, with `half_life_censored`) when that has not happened by day 28 or by the last day with data |
| Breadth (countries) | Countries with a published row for the item on day 0, in any language | A lower bound, see the limits |
| Breadth (languages) | Language editions (of those fetched) with a lift of 2 or more on day 0 or day 1 | Only languages where the article exists and has a baseline of 10 or more |
| `country_status` | See below | Never treats a missing row as zero |

**`country_status`**, for each event, item, language and country that has at least one
published row from day -28 to day 1:

| Status | Rule |
|---|---|
| `tracked` | A published row on at least 21 of the 28 baseline days. The lift on day 0 uses the median of the published baseline days only, and the number of those days is reported |
| `appeared` | Published on day 0 or day 1, and on at most 2 of the 28 baseline days |
| `not_published` | No row on day 0 or day 1, and both days have a country file (and not tracked) |
| `unclear` | Everything else (published on day 0 or 1 and on 3 to 20 baseline days) |
| `insufficient_files` | Fewer than 21 of the baseline days, or neither day 0 nor day 1, have a country file at all; or neither day has a row and one of them has no file. The status cannot be decided |

`appeared` means that the country's count **rose above the publication threshold**, not that it
started from nothing: below the threshold the count is unknown, not zero. A `tracked` country
without a row on day 0 has no lift. Rows are never filled in, and the noise is never removed.
`insufficient_files` covers Wikimedia's own missing days (an empty file, the start of the data);
it was added to the accepted four statuses so that a missing *file* is not read as a missing
*row*. Each row also counts its `older_method_days`: days in the window whose rows came from
Wikimedia's older method (United States rows until 2023-09-19, and seven rebuilt days in 2023).

**Limits under noise and thresholds (country measures).**
- Each country count has Gaussian noise added. For lower-risk countries 95% of counts are
  within about 36 views of the true value; for medium and higher-risk countries within about
  177 and 353 views (Wikimedia's README).
- A row is published only above 90 views (lower risk), 550 (medium) or 1,000 (higher), and only
  for pages with more than 150 views worldwide that day. Countries classed "not published" never
  appear. **A missing row means "below the threshold or not published", never zero.**
- Some rows come from Wikimedia's older method (threshold 450, Laplace noise): all United
  States rows from 2023-02-06 to 2023-09-19 and every row on the seven rebuilt days of 2023.
- Only the first 10 page views per browser and day are counted, so country counts are lower
  than the Analytics API's totals and the two must not be added or compared directly.
- Breadth depends on country size and on how much each country reads Wikipedia: a large country
  passes the threshold for many more pages. Breadth should be compared within a country over
  time or against a country's own typical breadth, not raw across countries.

**Limits of the language measures.**
- The Analytics API counts views of a page under its title; views of redirects to it are not
  included. For English pages that moved inside the span, the old titles are fetched too and
  the series are joined at the move dates (the day of a move adds both titles); joined series
  are flagged. After a move, an old title that now redirects to the same page is fetched for
  the days after the move too, and its views (readers who arrive through the old title) are
  added. An old title that became another article, a disambiguation page or nothing is left
  out, since its later views are not this page's. Moves in other language editions are not
  followed yet.
- Each series has a first and a last day fetched (the `series` table). After the backfill,
  `daily` extends the English series of an event's links at 7 and 28 days; other language
  editions keep the backfill's last day. The measures stop at a series' last day and never
  read an unfetched day as zero.
- A page created on or just before the event day has no baseline; its lift is undefined and
  its views are the signal (this is also what marks it as the event's own article).
- An earlier event about the same page inside the 28-day window raises the baseline; the
  median limits this but does not remove it.

**Version 1 in numbers** (portal days 2023-02-06 to 2026-11-12, built 2026-11-14; the
`country_status` shares and the joined series are from the later rebuild with the first
daily day, 2026-11-13).
- **Lift.** Of 128,350 English event pages, 10,334 (8%) have a baseline under the floor of 10
  views and no lift. For the others the lift on day 0 has a median of 1.2 (10th to 90th
  percentile 0.85 to 11.2); 30% reach 2 or more and 17% reach 5 or more. Taking each event's
  highest lift on day 0 or day 1 over its English links (0 when none has a baseline), the
  median is 6.9, and 17,393 of the 21,814 events with an English link reach 2 or more.
- **Peak and half-life.** 30,144 English event pages peak on day 0 and 29,234 on day 1. The
  half-life has a median of 2 days (90th percentile 9) where it is observed, and is censored
  for 33% of event pages (no fall below half the peak by day 28 or by the last day of data).
- **Breadth.** On day 0, the event's link that reaches the most countries has a published row
  in a median of 27 countries (10th to 90th percentile 8 to 58); 21,640 of the 21,821 events
  have at least one such row.
- **`country_status`** (3,953,727 rows): `not_published` 38.4%, `tracked` 26.3%, `appeared`
  17.4%, `unclear` 17.1%, `insufficient_files` 0.9%. For English pages created three days
  before the event or later, 84.7% of rows are `appeared` and 0.02% `tracked`, as the
  definition intends. `insufficient_files` covers the events before 2023-02-27, when fewer than
  21 baseline days have a country file, and the days next to a missing file (below). A `tracked` row has a day-0 lift with a
  median of 1.01 (10th to 90th percentile 0.69 to 2.11).
- **A day without a file.** When neither day 0 nor day 1 has a row and one of them has no
  country file (the empty file of 2026-11-08, or the newest day, whose next file is not read
  yet), the status is `insufficient_files`, not `not_published`: 3,021 rows of the events of
  2026-11-07, 2026-11-08 and 2026-11-12 in the backfill.
- **Joined series.** 4,942 English series are joined across the titles of a moved page. Of
  8,909 old titles, 6,858 now redirect to their page, and their views after the move are added
  (7,116 calls); 349 lead elsewhere and 332 no longer exist, so they are left out. At each move
  date with at least 10 views a day on one side (10,142 dates), views over the 7 days after the
  move were compared with the 7 days before; pages that did not move change by a factor of 5 or
  more on the same dates 0.9% of the time. 6,816 move dates (67%) show no such jump. Most jumps
  have a plain cause: the page was created in the 14 days before the move (2,229) or moved into
  the articles from a draft (384), so there was no article before. Views fell after the move at
  124 dates, down from 287 before the redirect views were added; most of the rest lead through
  an old title that is now another page. Views rose at 287 dates: a page that takes over a
  title that was already a redirect to it gains that title's readers, whose earlier views are
  not counted.

## 3. What page views do and do not measure
Page views measure **information seeking on Wikipedia**: how many times people opened an
article. Research has used them as a measure of public attention and interest and has
validated them against other measures:

- News coverage is followed by more views and edits of the related articles (Geiß, Leidecker &
  Roessing, 2016, *New Media & Society*, doi:10.1177/1461444815600281), and collective attention
  to Zika in US states followed news exposure more than local case counts (Tizzoni et al., 2020,
  *PLOS Computational Biology*, doi:10.1371/journal.pcbi.1007633). Attention to COVID-19 on
  Wikipedia tracked media coverage in four countries (Gozzi et al., 2020, *Journal of Medical
  Internet Research*, doi:10.2196/21597).
- Views track other behavior: votes (Smith & Gustafson, 2017, *Public Opinion Quarterly*,
  doi:10.1093/poq/nfx007; Yasseri & Bright, 2016, *EPJ Data Science*,
  doi:10.1140/epjds/s13688-016-0083-3), influenza-like illness (McIver & Brownstein, 2014,
  *PLOS Computational Biology*, doi:10.1371/journal.pcbi.1003581; Generous et al., 2014,
  doi:10.1371/journal.pcbi.1003892) and box-office revenue (Mestyán, Yasseri & Kertész, 2013,
  *PLOS ONE*, doi:10.1371/journal.pone.0071226).
- Current events renew attention to older, related articles, a measurable form of collective
  memory (García-Gavilanes et al., 2017, *Science Advances*, doi:10.1126/sciadv.1602368), and
  topics of attention around portal events can be traced through views and links
  (Gildersleve, Lambiotte & Yasseri, 2023, *Journal of Computational Social Science*,
  doi:10.1007/s42001-023-00215-w).
- The differentially private country files have been used to measure country-level interest
  in a topic (Meier, 2024, WebSci '24, doi:10.1145/3614419.3644007).

The references were confirmed against their DOI records on 2026-11-13; the one-line summaries
are to be checked against the full texts before any publication.

Page views do **not** measure attention outside Wikipedia (television, social media, news
sites), agreement or emotion, or who the readers are. Wikipedia's reach differs by country,
language, age and access to the internet, so a low count can mean little interest or little
use of Wikipedia. Bots that pass as human readers are filtered by Wikimedia's heuristics but
not perfectly.

## 4. The role of each linked page (DRAFT until the hand check is scored)
Most links point to general pages. Every linked page of every event gets one role, by a rule
that reads only stored signals (no model), with a confidence:

- `event`: the article about this specific happening (at most one per event);
- `story`: an article about the larger ongoing story the event is one development of;
- `context`: anything else, such as a country, a person, an organization or a general topic.

**Signals**, for one event and one linked page:

| Signal | Meaning |
|---|---|
| new | The page was created in the 14 days before the event or later, or moved into the articles (from a draft) within 14 days of the event |
| event class / context class | The page's Wikidata "instance of" class, judged by the head word of the class's English label: "mass shooting" (shooting) names a happening, "city in Fakeland" (city) names a place. The item's own classes decide; when none of their head words is known, their superclasses decide, then the superclasses of those. A happening wins a tie |
| year | The title holds the event's year (or a season such as 2025-26 that spans it) |
| words | The title shares a word of four letters or more with the event's text, and has more than that word |
| jump | Views on day 0 or day 1 at least 5 times the baseline; or, without a baseline of 10 views, a peak of at least 500 views by day 3 |
| in text | The event's own text links the page, not a story heading above it |

**The rule** (version 1, `newsattention.roles`):

1. A page with a context class is `context`.
2. The `event` page, at most one, is chosen among candidates. A page that the event's text
   links is a candidate when it is new, or has the event's year and a jump together with an
   event class or shared words. The nearest story heading is a candidate when it is new, shares
   words and has the year, or has an event class, the year, shared words and a jump: the portal
   often lists an event under its own article. The candidate with the most signals wins (new
   counts twice), then a link in the text over the heading, then the earlier link.
3. Every other page that a story heading links, or that has an event class and is not new, is
   `story`. The event's main story is the one under the nearest heading; a timeline or a list
   comes last.
4. The rest is `context`.

**Confidence** counts the signals that agree with the role. For `event`: new (counted twice),
event class, year, words and jump; 4 or more is `high`, 3 `medium`, fewer `low`. For `story`:
a story heading, the nearest heading, an event class, and a page older than 30 days; 3 or more
`high`, 2 `medium`, fewer `low`. For `context`: a context class is `high`, an old page without
an event class `medium`, anything else `low`.

The S1 prototype's reading check (30 events) found that most links are general pages, that
story articles with a year in the title also jump, that renamed pages look new, and that new
articles about people or companies are not the event. Version 1 answers these with the story
heading, the moves into the articles, and the Wikidata class.

**Validation.** A seeded sample of 150 events (spread evenly over 2023 to 2026, half where
the rule finds an `event` page) is checked by hand, blind to the rule, against two questions:
which link is the article about the event itself, and which is the article about the larger
story. The rule is fixed before the sample is drawn and is not changed on the sampled events.
With 150 events the 95% interval around an accuracy of 90% is about ±5 points. Until the sheets
are scored, the roles stay DRAFT.

## 5. Known gaps
- **Events with no article.** Some events link only to general pages; their attention is only
  visible through those pages, which also gather views for other reasons.
- **Countries Wikimedia does not publish.** Countries classed "not published" on Wikimedia's
  Country and Territory Protection List never appear, and medium and higher-risk countries
  appear only from 2024-02-15. The United States is missing from 2023-02-06 to 2023-09-19, seven
  days in 2023 were rebuilt with an older method, and single days can be missing (the file for
  2026-11-08 was empty when read on 2026-11-13).
- **The editors' selection.** The portal is written by volunteers. Its choice of events, of
  categories and of links reflects their attention, and it leans toward English-language news.
  NewsAttention measures attention to the events the portal lists, not to all news.
- **Late edits.** Editors keep adding and rewording events for days after a date: when the
  prototype read the pages on 2026-11-13, the pages for 2026-11-11 and 2026-11-12 had been
  edited that same day, and the page for 2026-11-12 held 14 events against a median of 17.5.
  Edits also come much later: of the 21 day pages that were at least seven days old, 12 had
  been edited seven or more days after their day ended (the latest 23 days after; the edits may
  be small). Each day is therefore read again after 7 days and after 30 days; each re-read
  replaces the earlier one, and the number of events added, removed or changed is logged.
  An event keeps its id across edits when its first cited source is unchanged; ids that change
  are logged.
- **Different counting rules.** Country counts (first 10 views per browser per day, human
  filter tightened on 2023-05-25) and language counts (all human views) are kept in separate
  columns and never mixed.
