# Data card (skeleton)

**SKELETON: nothing has been released.** Sections marked "to fill" are completed at release.

## Summary
NewsAttention links each day's news events, as listed on English Wikipedia's Current Events
Portal, to the daily page views of the Wikipedia articles each event links to: by language
edition (exact counts, Wikimedia Analytics API) and by country (noisy counts, Wikimedia's
differentially private page-view files). Derived tables give, for each event and page, a
baseline before the event, the lift over it, the peak day, a half-life and breadth.

- **Curated by:** Obada Kraishan (College of Media and Communication, Texas Tech University)
- **Funded by:** no external funding
- **Languages:** event text in English; page views in every Wikipedia language edition
- **License:** see [licenses](licenses.md) (the proposed split: counts and links CC0 1.0,
  event text CC BY-SA 4.0 with credit)
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
| Table | One row per | Key | Source |
|---|---|---|---|
| `events` | event on a portal day page | `event_id` | Current Events Portal (CC BY-SA 4.0 text) |
| `event_pages` | link from an event to an article | `event_id`, `link_order` | portal links, resolved through the Wikipedia API |
| `views` | article × day × (all countries or one country) | `date`, `qid`, `project`, `country`, `source` | Analytics API (`api`, exact) or DP files (`dp`, noisy) |
| `attention` | event × article × language or country × day | `event_id`, `qid`, `project`, `country`, `date`, `source` | derived |

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

## Size (to fill at release)
Events per day, links per event, rows per table, bytes per month. A 28-day prototype
(2026-10-16 to 2026-11-12) had about 17 events a day and 6.4 links per event.

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
- Known gaps in the country files: no United States rows from 2023-02-06 to 2023-09-19; seven
  days in 2023 rebuilt with the older method; countries of medium and higher risk only from
  2024-02-15; an empty file for 2026-11-08 (as of 2026-11-13).

## Ethics
See [ethics](ethics.md).

## Citation
See `CITATION.cff` (DRAFT until release).

## Contact
Issues on the GitHub repository (a private contact address to fill before release).
