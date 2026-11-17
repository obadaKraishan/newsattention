# Data card (draft)

**DRAFT: nothing has been released.** The numbers below describe version 1 as built on
2026-11-14 (portal days 2023-02-06 to 2026-11-12); sections marked "to fill" are completed at
release.

## Summary
NewsAttention links each day's news events, as listed on English Wikipedia's Current Events
Portal, to the daily page views of the Wikipedia articles each event links to: by language
edition (exact counts, Wikimedia Analytics API) and by country (noisy counts, Wikimedia's
differentially private page-view files). Derived tables give, for each event and page, a
baseline before the event, the lift over it, the peak day, a half-life and breadth.

- **Curated by:** Obada Kraishan (College of Media and Communication, Texas Tech University)
- **Funded by:** no external funding
- **Languages:** event text in English; page views in every Wikipedia language edition
- **License:** see [licenses](licenses.md): counts and links CC0 1.0, event text CC BY-SA 4.0
  with credit (one license per table, listed in the [release layout](release-layout.md))
- **Repository:** <https://github.com/obadaKraishan/newsattention>
- **Dataset:** Hugging Face `obadakr/newsattention` (to fill), Kaggle mirror (to fill), Zenodo
  DOI (to fill)

## Uses
- **Intended:** research on public attention to news: how long attention to an event lasts,
  where it travels across countries and languages, which events get little or none, and how
  attention differs by event category and by the news sites the portal cites.
- **Out of scope:** anything about individual readers; attempts to remove the privacy noise or
  to estimate unpublished countries; treating page views as all public attention; ranking
  countries or peoples by "interest" without the caveats below.

## Structure
Each table is a set of Parquet files, one per month.

| Table | One row per | Source |
|---|---|---|
| `events` | event on a portal day page | Current Events Portal (CC BY-SA 4.0 text) |
| `event_pages` | link from an event to an article, with its role (`event`, `story` or `context`) and a confidence | portal links, resolved through the Wikipedia API; roles from a rule (DRAFT, see the method) |
| `pages` | linked English article: creation estimate, moves in the span | MediaWiki API (page ids, first revisions, move log) |
| `views_api` | item, language and day (inside a series' fetched days, a day without a row had no views); an English article with no Wikidata item is named by its `page_id`, with an empty `qid` | Analytics API, exact |
| `series` | item and language: first and last day fetched, and whether older titles are joined in | derived |
| `views_dp` | item, language, country and day, as published | differentially private files, noisy |
| `attention` | event, item, language and day 0 to 28 | derived |
| `attention_summary` | event, item and language: the measures | derived |
| `country_status` | event, item, language and country | derived from `views_dp` |

Field definitions are in `src/newsattention/schema.py`; `newsattention validate FILE` checks a
file against them.

## Creation
- **Events:** each portal day page is read as wikitext through the MediaWiki API, with its
  revision id, and parsed into headings, events, story headings, links and cited news domains.
  Each day is read again after 7 and after 30 days; each re-read replaces the earlier one.
- **Links:** titles are resolved after redirects to page ids and Wikidata ids.
- **Views:** Analytics API per-article daily views (`all-access`, human `user` agent); the
  daily differentially private file by country, project and page, filtered to the linked items.
- **Measures:** see the [method](method.md).
- **Provenance:** every row is computed by code from the sources; no row is written or edited
  by hand, and no language model is used (to fill if one is added: model name and license).

## Size
Version 1 as built on 2026-11-17 (portal days 2023-02-06 to 2026-11-16, views from 2023-01-09):

- 1,380 portal day pages, **21,886 events** (median 15 a day, from 8 to 25 for the middle 80%
  of days; 391 a month in 2023, 613 a month in 2026), with a median of 6 links each.
- **33,514 linked items** (Wikidata ids) behind 37,375 linked titles, and 7 linked English
  articles with no item; 4,960 English pages were moved inside the span, and each of their
  series is joined across its titles.
- Language views: 112,693 series (English and up to five other languages per item, 198
  languages in all); country views: the rows of linked items in the daily files.

| Table | Rows | Size (Parquet, zstd) |
|---|---:|---:|
| `events` | 21,886 | 2.4 MB |
| `event_pages` | 128,929 | 2.5 MB |
| `pages` | 33,521 | 1.0 MB |
| `views_api` | 141,275,572 | 234.6 MB |
| `series` | 112,693 | 0.4 MB |
| `views_dp` | 58,460,446 | 353.8 MB |
| `attention` | 17,086,285 | 110.1 MB |
| `attention_summary` | 596,896 | 17.8 MB |
| `country_status` | 3,958,148 | 22.9 MB |
| **all** | | **745.5 MB** |

The sources behind it are about 32.6 GB: 32.2 GB of country files, 0.29 GB of Analytics API
answers kept as Parquet, 0.14 GB of move log and 10 MB of portal pages.

## Bias, risks and limits
- Page views are reading on Wikipedia, not all public attention; Wikipedia's reach differs by
  country, language and access.
- Country counts are noisy (95% of rows within about 36 views of the true value for lower-risk
  countries) and thresholded (rows below 90, 550 or 1,000 views are not published, by the
  country's risk class); some countries are never published. A missing country row is not zero.
- The portal's events are an editorial selection by volunteers and lean toward
  English-language news.
- Most links point to general pages (a country, a party); which page is the event's own
  article is decided by a rule. Against a weighted hand-checked sample of 150 events, rule
  version 1 (without Wikidata classes) is right for 82% of events on the event's own article
  and 71% on the larger story, below its 90% target (see the method).
- Known gaps in the country files: United States rows from 2023-02-06 to 2023-09-19 come from
  Wikimedia's older method (threshold 450), as do every country's rows on seven days of 2023;
  countries of medium and higher risk only from 2024-02-15; an empty file for 2026-11-08 (as
  of 2026-11-13). Events before 2023-02-27 have too few baseline days with a file for a
  country status (`insufficient_files`).
- **When an event's measures are complete.** English views are fetched again the day after
  an event and at 7 and 28 days, so its English measures are current from the next day. Other
  languages are fetched once more, at the event's day 27, so **other-language measures of an
  event are complete 28 days after it**; until then they stop at the last day fetched (see
  `series`).
- Moved pages: English series are joined across the page's titles at the move dates, and an
  old title that now redirects to the same page adds its views after the move. Views through
  an old title that became another article are left out, and moves in other language editions
  are not followed.
- Roles: which link is the event's own article and which the larger story come from a rule
  (no model), with a confidence, and stay DRAFT. On the hand-checked sample, when the rule
  names an `event` page it is that event's own article for about 36% of events: it often takes
  a recent article about a happening that lasts days or weeks (protests, floods, a battle, a
  crisis) for the event's own article, where the reviewer reads it as the larger story. The
  confidence does not yet track how often a role is right. The roles do not use Wikidata
  classes yet (they could not be fetched while Wikidata was lagged), so new articles about
  people or organizations can still be taken for the event's own article, and the old article
  of a scheduled event (an election) can be taken for the larger story.

## Ethics
See [ethics](ethics.md).

## Citation
See `CITATION.cff` (DRAFT until release).

## Contact
Issues on the GitHub repository (a private contact address to fill before release).
