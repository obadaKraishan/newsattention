# Release layout

**Proposed for version 0.1.0; nothing is uploaded.** The dataset goes to Hugging Face
(`obadakr/newsattention`), with a Kaggle mirror of the same tables; Zenodo keeps the code and
the documents only, through a GitHub release. `newsattention release build` writes a version's
files into `data/release/VERSION/` (never tracked), and `newsattention release check` checks
them.

## On Hugging Face
Each table is one **configuration** with one **split**, `train`, so a user loads one table in
one line:

```python
from datasets import load_dataset

events = load_dataset("obadakr/newsattention", "events", split="train")
```

| Configuration | Files | One row per | License |
|---|---|---|---|
| `events` (default) | `events/YYYY-MM.parquet` | event | **CC BY-SA 4.0**, credited to Wikipedia's contributors with the portal page and revision id of each event |
| `event_pages` | `event_pages/YYYY-MM.parquet` (by the event's month) | event and linked article: item, page id, title, link order, `in_text`, `story_level` | CC0 1.0 |
| `pages` | `pages/pages.parquet` | linked English article (creation estimate, moves) | CC0 1.0 |
| `views_api` | `views_api/YYYY-MM.parquet` | item, language and day (inside a series' fetched days, a day without a row had no views) | CC0 1.0 |
| `series` | `series/series.parquet` | item and language: the first and last day fetched, and whether older titles are joined in | CC0 1.0 |
| `views_dp` | `views_dp/YYYY-MM.parquet` | item, language, country and day, as published by Wikimedia | CC0 1.0 |
| `attention` | `attention/YYYY-MM.parquet` (by the event's month) | event, item, language and day 0 to 28 | CC0 1.0 |
| `attention_summary` | `attention_summary/YYYY-MM.parquet` | event, item and language: the measures | CC0 1.0 |
| `country_status` | `country_status/YYYY-MM.parquet` | event, item, language and country | CC0 1.0 |

Next to the tables: `README.md` (the card), `LICENSES.md` (the license of each table and column)
and `manifest.json` (every file's rows, size and SHA-256, each table's license, and the first
and last day each source was read). Every Parquet file also names its table, license and version
in its own metadata, and the event files carry the credit line.

**Why this layout.**
- **One configuration per table** because the tables have different columns; a configuration
  is how the Hub keeps them apart and how `load_dataset` names them. `events` is the default:
  it is small and it is where a reader starts.
- **One split, `train`**, because the tables are not split for training or testing; `train` is
  the Hub's name for a single split, so every tool that expects a split finds one.
- **Monthly files** (shards) for the large tables (`views_api`, `views_dp`, `attention`, and the
  others for the same reason): each file is a few megabytes, the viewer reads one file at a
  time, a user can load one month with `data_files`, and an update changes only the newest
  months, so a new version uploads a few files rather than the whole table.
- `pages` and `series` are one file each, in their own folders, so every configuration reads
  `TABLE/*.parquet`.

Views and measures are keyed by the Wikidata item (`qid`) and the language edition. A linked
English article with no Wikidata item has its English views under its `page_id`, with an empty
`qid`, in `views_api`, `series`, `attention` and `attention_summary` (in `views_dp`, `page_id`
is the page of the published row). Once such an article has an item, its views are under the
item instead. This layout was accepted on 2026-11-23.

**Left out.** The roles (`role`, `role_confidence`) are computed in the local tables but do not
ship (see the [method](method.md), section 4); `release check` fails on either column. Rows
named in `data/removals.csv` are left out of every table (see
[corrections and removals](corrections.md)).

## On Kaggle
The Kaggle command line uploads the files of one folder and skips subfolders, so the mirror
holds the same tables as **one Parquet file per table** (`events.parquet` and so on), with the
same `LICENSES.md`, a manifest of its own files, `dataset-metadata.json` and a cover drawn by
code (`newsattention release kaggle`). Kaggle shows one license per dataset: the mirror shows
CC BY-SA 4.0, the one license that is true of every file (CC0 material may be shared under it),
and `LICENSES.md` gives each table's own license.

## Updates
Versions are made by hand, about weekly, until the automatic update. Monthly files of the
current and the previous month change between versions (new events, re-reads at 7 and 30 days,
follow-up views); older months change only when a 30-day re-read lands in them. English views
of an event are fetched again the day after it and at 7 and 28 days, other languages once more
at its day 27, so other-language measures of an event are complete 28 days after it.
