# Release layout (draft)

**DRAFT: nothing is uploaded.** This is the planned layout of the dataset on Hugging Face
(`obadakr/newsattention`), mirrored on Kaggle and snapshotted on Zenodo. Each table is one
configuration, stored as Parquet files by month.

| Configuration | Files | One row per | License |
|---|---|---|---|
| `events` | `events/YYYY-MM.parquet` | event | **CC BY-SA 4.0**, credited to Wikipedia contributors with the portal page and revision id of each event |
| `event_pages` | `event_pages/YYYY-MM.parquet` (by the event's month) | event and linked article | CC0 1.0 |
| `pages` | `pages.parquet` | linked English article (creation estimate, moves) | CC0 1.0 |
| `views_api` | `views_api/YYYY-MM.parquet` | item, language and day (days without a row are 0) | CC0 1.0 |
| `views_dp` | `views_dp/YYYY-MM.parquet` | item, language, country and day, as published by Wikimedia | CC0 1.0 |
| `attention` | `attention/YYYY-MM.parquet` (by the event's month) | event, item, language and day 0 to 28 | CC0 1.0 |
| `attention_summary` | `attention_summary/YYYY-MM.parquet` | event, item and language: the measures | CC0 1.0 |
| `country_status` | `country_status/YYYY-MM.parquet` | event, item, language and country | CC0 1.0 |

The licenses follow [licenses](licenses.md): the counts and links are CC0 1.0 (the Analytics
API, the country files and Wikidata are CC0, and Wikipedia's contributors waive database
rights in facts), and only the event text is CC BY-SA 4.0. A table that joins `events` with
any other table and is shared is an adaptation and carries CC BY-SA 4.0.

## Dataset card metadata (sketch)
```yaml
license:
  - cc0-1.0
  - cc-by-sa-4.0
pretty_name: NewsAttention
configs:
  - config_name: events
    data_files: "events/*.parquet"
  - config_name: event_pages
    data_files: "event_pages/*.parquet"
  - config_name: pages
    data_files: "pages.parquet"
  - config_name: views_api
    data_files: "views_api/*.parquet"
  - config_name: views_dp
    data_files: "views_dp/*.parquet"
  - config_name: attention
    data_files: "attention/*.parquet"
  - config_name: attention_summary
    data_files: "attention_summary/*.parquet"
  - config_name: country_status
    data_files: "country_status/*.parquet"
```

The card states the license of each configuration next to it, the credit line for the event
text ("Event text from Wikipedia's Current Events Portal, by Wikipedia contributors, CC BY-SA
4.0. Changed: wiki markup removed and the text split into one row per event"), the not-affiliated
line, and the corrections route (the repository's issue form).

## Updates
Monthly files of the current and the previous month change every day (new events, re-reads at
7 and 30 days, follow-up views); older months change only when a 30-day re-read lands in them.
Each upload records the build summary (row counts, the last day covered, the request counts).
