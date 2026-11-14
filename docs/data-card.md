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
| `views_api` | item, language and day (inside a series' fetched days, a day without a row had no views) | Analytics API, exact |
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
Version 1 as built on 2026-11-14 (portal days 2023-02-06 to 2026-11-12, views from 2023-01-09):

- 1,376 portal day pages, **21,821 events** (median 15 a day, from 8 to 25 for the middle 80%
  of days; 391 a month in 2023, 613 a month in 2026), with a median of 6 links each.
- **33,417 linked items** (Wikidata ids) behind 37,265 linked titles; 4,941 of their English
  pages were moved inside the span, and each of their series is joined across its titles.
- Language views: 112,530 series (English and up to five other languages per item, 198
  languages in all); country views: the rows of linked items in 1,375 daily files.

| Table | Rows | Size (Parquet, zstd) |
|---|---:|---:|
| `events` | 21,821 | 2.4 MB |
| `event_pages` | 128,516 | 2.4 MB |
| `pages` | 33,425 | 1.0 MB |
| `views_api` | 141,098,686 | 234.5 MB |
| `views_dp` | 58,345,138 | 353.2 MB |
| `attention` | 17,066,406 | 109.8 MB |
| `attention_summary` | 595,301 | 17.7 MB |
| `country_status` | 3,952,208 | 22.9 MB |
| **all** | | **743.9 MB** |

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
  article is decided by a rule, with a known error rate (to fill).
- Known gaps in the country files: United States rows from 2023-02-06 to 2023-09-19 come from
  Wikimedia's older method (threshold 450), as do every country's rows on seven days of 2023;
  countries of medium and higher risk only from 2024-02-15; an empty file for 2026-11-08 (as
  of 2026-11-13). Events before 2023-02-27 have too few baseline days with a file for a
  country status (`insufficient_files`).
- Moved pages: English series are joined across the page's titles at the move dates, and an
  old title that now redirects to the same page adds its views after the move. Views through
  an old title that became another article are left out, and moves in other language editions
  are not followed.
- Roles: which link is the event's own article and which the larger story come from a rule
  (no model), with a confidence; it is checked by hand on a sample of 150 events before the
  roles leave DRAFT.

## Ethics
See [ethics](ethics.md).

## Citation
See `CITATION.cff` (DRAFT until release).

## Contact
Issues on the GitHub repository (a private contact address to fill before release).
