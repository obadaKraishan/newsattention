# Paper facts

Every figure the dataset card (release 0.1.0) and the [method](method.md) give, with where it
comes from and when. Figures only: no event text and no titles. Release 0.1.0 is the dataset as
published on 2026-11-24 (Hugging Face `obadakr/newsattention`, tag `v0.1.0`; the card as
updated the same day).

## Release 0.1.0: coverage and sources
Source: the release's `manifest.json` (built 2026-11-23T16:18:01Z by `newsattention release
build`, code 0.1.0).

| Figure | Value |
|---|---|
| Event days | 2023-02-06 to 2026-11-22 (1,386 portal day pages) |
| Daily views | 2023-01-09 to 2026-11-22 (28 days before the first event, for the baseline) |
| Events | 21,997 |
| Linked Wikidata items | 33,672 |
| Linked English articles without an item | 7 |
| Linked English articles moved inside the span | 4,995 |
| Language editions with views | 198 |
| Countries with published rows | 242 |
| Portal pages read | 2026-11-13 to 2026-11-23 |
| MediaWiki Action API read | 2026-11-13 to 2026-11-23 |
| Wikimedia Analytics API read | 2026-11-13 to 2026-11-23 |
| Country files read | 2026-11-13 to 2026-11-23 |

The country file for 2026-11-22 was not yet published when the last day was read
(2026-11-23), so the events of 2026-11-21 and 2026-11-22 carry `insufficient_files` where a day
has no file.

## Release 0.1.0: tables
Source: the release's `manifest.json` (rows, files and bytes per table; sizes in MB of 10^6
bytes, Parquet with zstd).

| Table | Files | Rows | Size | License |
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

The Kaggle mirror holds the same tables, one file per table (747.7 MB). The Zenodo record holds
the code and documents only (78 files).

## Release 0.1.0: `country_status`
Source: the release's `manifest.json` (counts per status over the 3,969,401 rows).

| Status | Rows | Share |
|---|---:|---:|
| `not_published` | 1,522,020 | 38.3% |
| `tracked` | 1,044,377 | 26.3% |
| `appeared` | 689,541 | 17.4% |
| `unclear` | 678,609 | 17.1% |
| `insufficient_files` | 34,854 | 0.9% |

## Release 0.1.0: moves and joined series
Source: the build summary of the tables behind the release (built 2026-11-23).

| Figure | Value |
|---|---|
| Linked English articles moved inside the span | 4,995 |
| English series joined across a moved page's titles | 4,975 |
| Series in all (item or article, and language edition) | 112,938 |
| Page-id series dropped because the article gained a Wikidata item | 1 |

## The roles: validation of rule version 1 (left out of release 0.1.0)
Source: `newsattention review-score` on the maintainer's three hand-checked sheets, 2026-11-17
(rule version 1 without Wikidata classes, frozen before any answer was read; weighted over the
frame of 21,795 events; 90% intervals from a stratified bootstrap of 10,000 resamples, seed
20261117). Aggregates only; the sheets are not published.

| | The event's own article (Q1) | The larger story (Q2) |
|---|---|---|
| Rule version 1 right, all events | 82.2% (77.2 to 86.8) | 71.2% (63.9 to 78.2) |
| "None" every time right | 86.4% (81.6 to 90.7) | 50.5% |
| Precision (the rule's page is the reviewer's) | 36% (28 of 75 sampled events, weighted 36.0%) | 59% (46 of 91, weighted 58.9%) |
| Recall (of the reviewer's pages, the rule names) | 43% (28 of 37, weighted 42.7%) | 77% (46 of 85, weighted 76.5%) |
| Right where the rule finds an `event` page | 36.0% (27.3 to 45.1) | 47.8% (38.6 to 57.2) |
| Right on the other events | 91.1% (85.5 to 96.2) | 75.7% (67.2 to 83.8) |

Both questions right together: 68.5% (61.2 to 75.4). Target: 90%. The sample: 150 events in
eight strata (year, and whether the rule finds an `event` page), 37 or 38 a year, weights from 1
in 37 to 1 in 320; the reviewer names an own article for 37 of the 150 events (about 14% of
all events once weighted). Rule frozen 2026-11-17 at 19:39:49 UTC, `roles.py` SHA-256
`a5109464712a6c79324fe1125f6ef933a1b7afceeba03abf3cf09410e32f7ac8`. The three sheets are now a
development set.

## The method's "version 1 in numbers"
Source: the [method](method.md), section 2, from the tables built 2026-11-14 (portal days
2023-02-06 to 2026-11-12; the `country_status` shares and the joined series from the rebuild
with the first daily day, 2026-11-13). These figures predate release 0.1.0's tables.

| Figure | Value |
|---|---|
| English event pages | 128,350 |
| With a baseline under the floor of 10 views (no lift) | 10,334 (8%) |
| Day-0 lift, median (10th to 90th percentile) | 1.2 (0.85 to 11.2) |
| Share with a day-0 lift of 2 or more; of 5 or more | 30%; 17% |
| Each event's highest day-0 or day-1 lift over its English links, median | 6.9 |
| Events with an English link reaching a lift of 2 or more | 17,393 of 21,814 |
| English event pages peaking on day 0; on day 1 | 30,144; 29,234 |
| Half-life, median (90th percentile), where observed | 2 days (9) |
| Half-life censored | 33% of event pages |
| Countries on day 0 for an event's widest link, median (10th to 90th percentile) | 27 (8 to 58) |
| Events with at least one published country row on day 0 | 21,640 of 21,821 |
| `country_status` rows (that build) | 3,953,727 |
| Shares: `not_published`, `tracked`, `appeared`, `unclear`, `insufficient_files` | 38.4%, 26.3%, 17.4%, 17.1%, 0.9% |
| Rows `appeared` for English pages created three days before the event or later | 84.7% (`tracked` 0.02%) |
| Day-0 lift of a `tracked` row, median (10th to 90th percentile) | 1.01 (0.69 to 2.11) |
| Rows `insufficient_files` next to a missing file (events of 2026-11-07, 11-08 and 11-12) | 3,021 |
| English series joined across a moved page's titles | 4,942 |
| Old titles of moved pages; now redirecting to their page; leading elsewhere; gone | 8,909; 6,858; 349; 332 |
| Calls for redirect views after a move | 7,116 |
| Move dates checked (at least 10 views a day on one side) | 10,142 |
| Pages that did not move changing by a factor of 5 or more on the same dates | 0.9% |
| Move dates with no such jump | 6,816 (67%) |
| Jumps after creation within 14 days; after a move from a draft | 2,229; 384 |
| Views falling after a move (before the redirect views were added) | 124 dates (287) |
| Views rising after a move | 287 dates |

## The country files (Wikimedia's documentation, as the card and the method give it)
Source: Wikimedia's README of the `country_project_page` files, read 2026-11-13.

| Figure | Value |
|---|---|
| Publication thresholds (lower, medium, higher risk) | 90, 550, 1,000 views a day |
| Pages published only above, worldwide that day | 150 views |
| 95% of counts within (lower, medium, higher risk) | about 36, 177, 353 views |
| Older method (threshold 450, Laplace noise) | United States 2023-02-06 to 2023-09-19, and seven rebuilt days of 2023 |
| Medium and higher-risk countries published from | 2024-02-15 |
| Views counted per browser and day | the first 10 |
| Baseline window; days needed for `tracked` | 28 days; 21 of them |
