# Data card

The card that ships with each version (`README.md` on Hugging Face) is built by
`newsattention release build` from [`src/newsattention/dataset_card.md`](../src/newsattention/dataset_card.md),
with that version's numbers. This page keeps the same facts for the repository, with the build
behind release 0.1.0, **published on 2026-11-24**. The figures, each with where it comes from,
are in [paper facts](paper-facts.md).

## Summary
NewsAttention links each day's news events, as listed on English Wikipedia's Current Events
Portal, to the daily page views of the Wikipedia articles each event links to: by language
edition (exact counts, Wikimedia Analytics API) and by country (Wikimedia's published,
privacy-protected counts, used as published). Derived tables give, for each event and article,
a baseline before the event, the lift over it, excess views, the peak day, a half-life and
breadth.

- **Curated by:** Obada Kraishan (College of Media and Communication, Texas Tech University)
- **Funded by:** no external funding
- **Languages:** event text in English; page views in every Wikipedia language edition fetched
- **License:** counts, links and measures CC0 1.0; event text CC BY-SA 4.0 with credit
  ([licenses](licenses.md); every version carries a `LICENSES.md` per table and column)
- **Repository:** <https://github.com/obadaKraishan/newsattention>
- **Dataset:** <https://huggingface.co/datasets/obadakr/newsattention> (tag `v0.1.0`), with a
  mirror of the same tables on Kaggle: <https://www.kaggle.com/datasets/obadakraishan/newsattention>
- **Code and documents (no data table):** Zenodo, DOI 10.5281/zenodo.24487868 (all versions;
  release 0.1.0: 10.5281/zenodo.24487869)

## Uses
- **Intended:** research on public attention to news: how long attention to an event lasts,
  where it travels across countries and languages, which events get little or none, and how
  attention differs by event category and by the news sites the portal cites.
- **Out of scope:** anything about individual readers; attempts to remove the privacy noise or
  to estimate unpublished countries; treating page views as all public attention; ranking
  countries or peoples by "interest" without the caveats below.

## Structure
Each table is one configuration on Hugging Face, stored as Parquet files (one per month for
the large tables); see the [release layout](release-layout.md).

| Table | One row per | Source |
|---|---|---|
| `events` | event on a portal day page | Current Events Portal (CC BY-SA 4.0 text) |
| `event_pages` | link from an event to an article: item, page id, title, link order, `in_text`, `story_level` | portal links, resolved through the Wikipedia API |
| `pages` | linked English article: creation estimate, moves in the span | MediaWiki API (page ids, first revisions, move log) |
| `views_api` | item, language and day (inside a series' fetched days, a day without a row had no views); an English article with no Wikidata item is named by its `page_id`, with an empty `qid` | Analytics API, exact |
| `series` | item and language: first and last day fetched, and whether older titles are joined in | derived |
| `views_dp` | item, language, country and day, as published | differentially private files, noisy |
| `attention` | event, item, language and day 0 to 28 | derived |
| `attention_summary` | event, item and language: the measures | derived |
| `country_status` | event, item, language and country | derived from `views_dp` |

Field definitions are in `src/newsattention/schema.py`; `newsattention validate FILE` checks a
file against them. The roles of the links (`role`, `role_confidence`) are computed in the local
tables but are **not released** (see below).

## Creation
- **Events:** each portal day page is read as wikitext through the MediaWiki API, with its
  revision id, and parsed into headings, events, story headings, links and cited news domains.
  Each day is read again after 7 and after 30 days; each re-read replaces the earlier one.
- **Links:** titles are resolved after redirects to page ids and Wikidata ids.
- **Views:** Analytics API per-article daily views (`all-access`, human `user` agent); the
  daily differentially private file by country, project and page, filtered to the linked items.
- **Measures:** see the [method](method.md).
- **Provenance:** every row is computed by code from the sources; no row is written or edited
  by hand, and no row is produced or labeled by a language model.

## Size
Release 0.1.0 as built on 2026-11-23 (portal days 2023-02-06 to 2026-11-22, views from
2023-01-09 to 2026-11-22; the sources read from 2026-11-13 to 2026-11-23):

- 1,386 portal day pages, **21,997 events**, linked to **33,672 Wikidata items** and 7 English
  articles with no item; 4,995 linked English articles moved inside the span, and each of their
  English series is joined across its titles.
- Language views: 112,938 series in 198 language editions (English and up to five others per
  item); country views: the published rows of the linked items in 242 countries.
- `country_status`: `not_published` 38.3%, `tracked` 26.3%, `appeared` 17.4%, `unclear` 17.1%,
  `insufficient_files` 0.9%.

| Table | Files | Rows | Size (Parquet, zstd) | License |
|---|---:|---:|---:|---|
| `events` | 46 | 21,997 | 2.4 MB | CC BY-SA 4.0 |
| `event_pages` | 46 | 129,770 | 2.4 MB | CC0 1.0 |
| `pages` | 1 | 33,679 | 1.0 MB | CC0 1.0 |
| `views_api` | 47 | 141,581,977 | 235.8 MB | CC0 1.0 |
| `series` | 1 | 112,938 | 0.4 MB | CC0 1.0 |
| `views_dp` | 46 | 58,600,028 | 354.7 MB | CC0 1.0 |
| `attention` | 46 | 17,147,484 | 110.6 MB | CC0 1.0 |
| `attention_summary` | 46 | 600,347 | 17.9 MB | CC0 1.0 |
| `country_status` | 46 | 3,969,401 | 23.0 MB | CC0 1.0 |
| **all** | **325** | **222,197,621** | **748.2 MB** | |

The sources behind it are about 32.8 GB: 32.3 GB of country files, 0.30 GB of Analytics API
answers kept as Parquet, 0.14 GB of move log and 10 MB of portal pages.

## Bias, risks and limits
- Page views are reading on Wikipedia, not all public attention; Wikipedia's reach differs by
  country, language and access.
- Country counts are noisy (95% of rows within about 36 views of the true value for lower-risk
  countries) and thresholded (rows below 90, 550 or 1,000 views are not published, by the
  country's risk class); some countries are never published. A missing country row is not zero.
- The portal's events are an editorial selection by volunteers and lean toward
  English-language news. A few events consist of one linked article title rather than a
  sentence.
- Known gaps in the country files: United States rows from 2023-02-06 to 2023-09-19 come from
  Wikimedia's older method (threshold 450), as do every country's rows on seven days of 2023;
  countries of medium and higher risk only from 2024-02-15; single days can be missing or
  empty (the file for 2026-11-08 was empty when read). Events before 2023-02-27 have too few
  baseline days with a file for a country status (`insufficient_files`).
- **When an event's measures are complete.** English views are fetched again the day after
  an event and at 7 and 28 days, so its English measures are current from the next day. Other
  languages are fetched once more, at the event's day 27, so **other-language measures of an
  event are complete 28 days after it**; until then they stop at the last day fetched (see
  `series`).
- Moved pages: English series are joined across the page's titles at the move dates, and an
  old title that now redirects to the same page adds its views after the move. Views through
  an old title that became another article are left out, and moves in other language editions
  are not followed.
- **Roles left out.** Which link is the event's own article and which the larger story came
  from a rule (no model), checked by hand on a weighted sample of 150 events. It was right for
  82.2% of events on the event's own article, below answering "none" every time (86.4%), and
  for 71.2% on the larger story (against 50.5%); see the [method](method.md), section 4. So the
  first release has no role columns; `in_text`, `story_level`, the creation estimate and the
  moves stay in for users to apply.

## Ethics
See [ethics](ethics.md).

## Citation
The data set's citation is defined once, in `newsattention.citation`; the card's and the Kaggle
description's "How to cite" open with it, and `release check` fails when either does not:

Kraishan, O. (2026). *NewsAttention: Daily news events linked to how many people read about
them on Wikipedia* (Version 0.1.0) [Data set]. Hugging Face.
https://huggingface.co/datasets/obadakr/newsattention

A BibTeX entry follows it, then the release date and the Zenodo DOI of the code and documents
(no data table): https://doi.org/10.5281/zenodo.24487868 (all versions), and the credit to
Wikipedia's contributors. `CITATION.cff` gives the dataset as the preferred citation, with both
DOIs.

## Contact
The repository's issue forms, for a correction or a removal request; each is answered within
14 days ([corrections and removals](corrections.md)).
