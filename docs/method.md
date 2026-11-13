# Method

**DRAFT: not yet accepted by the maintainer.** Numbers marked "prototype" come from a 28-day
sample (portal days 2026-10-16 to 2026-11-12, read on 2026-11-13) and are there to show the
scale, not as results.

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
All measures are computed per event, page and language (or country), from the event day on.

| Measure | Definition | Notes |
|---|---|---|
| Baseline | Median daily views over the 28 days before the event day (days -28 to -1) | Needs all 28 days; the median resists one earlier spike and the weekly cycle |
| Lift | Views on a day divided by the baseline | Only when the baseline is at least 10 views a day. Below that, a handful of views gives absurd ratios (the prototype had lifts up to 234,024 on near-empty baselines); such pages report their views and excess views instead |
| Excess views | Sum over days 0 to k of (views minus baseline) | Proposed k = 7 and 28 |
| Peak day | The day with the most views from the event day on (the earliest on ties) | Reported as days since the event |
| Half-life | Days from the peak until views first fall below half the peak | Right-censored when the series ends first (reported as "not yet") |
| Breadth (countries) | Countries with a published row for the page on the event day (any language) | A lower bound; see the limits |
| Breadth (languages) | Language editions whose lift on day 0 or 1 is at least 2 | Only languages where the article exists |

**Limits under noise and thresholds (country measures).**
- Each country count has Gaussian noise added. For lower-risk countries 95% of counts are
  within about 36 views of the true value; for medium and higher-risk countries within about
  177 and 353 views (Wikimedia's README).
- A row is published only above 90 views (lower risk), 550 (medium) or 1,000 (higher), and only
  for pages with more than 150 views worldwide that day. Countries classed "not published" never
  appear. **A missing row means "below the threshold or not published", never zero.** So a
  country baseline cannot be computed for most pages, and country lift is not defined in the
  first release; country measures are breadth and the event-day counts.
- Only the first 10 page views per browser and day are counted, so country counts are lower
  than the Analytics API's totals and the two must not be added or compared directly.
- Breadth depends on country size and on how much each country reads Wikipedia: a large country
  passes the threshold for many more pages. Breadth should be compared within a country over
  time or against a country's own typical breadth, not raw across countries.

**Limits of the language measures.**
- The Analytics API counts views of a page under its title; views of redirects to it are not
  included, and a page moved during the window splits its series. Titles are resolved on the
  day the event is read.
- A page created on or just before the event day has no baseline; its lift is undefined and
  its views are the signal (this is also what marks it as the event's own article).
- An earlier event about the same page inside the 28-day window raises the baseline; the
  median limits this but does not remove it.

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

## 4. The event's own article (to be validated)
Most links point to general pages. A first rule marks a linked page as the event's own article
when **it is new** (at least 14 of the 28 baseline days have zero views) **or its title holds a
year and its views on the event day or the day after are at least five times its baseline**.
In the prototype the rule flags 242 of 3,113 English links (7.8%), so about 92% of links are
general pages, and 174 of 487 events (36%) have at least one flagged link. A reading check of
30 random events found that 9 of them link an article about the event itself (9 of their 184
links, 4.9%). The rule found the right page in 7 of those 9 events, flagged 4 events that have
no such article, and was right about 24 of the 30 events. Its errors point to the next rule:

- **Story articles with a year in the title** ("2026 ... civil unrest", "... involvement in
  the 2026 ... war", a year overview) also jump; the event's own article is usually the
  *nearest* story heading or the most specific page.
- **Pages renamed recently** have almost no views under their new title, so they look new
  (the Analytics API counts views by title). Page moves need to be detected (the page's
  creation date or move log, or its Wikidata id, which is far older than a new item's).
- **New pages about people or companies** created because of the event are new but are not
  the event. Wikidata's "instance of" property can tell an event (an election, a strike, an
  attack) from a person or a company.
- **Own articles without a year in the title** (named incidents) are missed.

A later stage will validate a refined rule on a larger sample; a language model is considered
only if rules fall short.

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
