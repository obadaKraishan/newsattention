# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Backfill commands, each resumable: `portal-backfill` and `reread` (each day read again 7
  and 30 days after it ends; a changed revision replaces the day's events and every read
  stays on record), `reparse` and `parse-report` (what the parser could not read, by month),
  `links`, `pages` (creation dates estimated from page ids, checked on a random sample, and the
  English move log), `dp-download` and `dp-filter` (the country files, with the documented
  gaps and each day's smallest count per country recorded), `plan` (append-only) and
  `api-backfill` (raw chunks of 250 calls).
- `tables`: events, event_pages, pages, views_dp, views_api (moved English pages joined across
  their titles and flagged), attention, attention_summary and country_status, as Parquet files
  by month; `validate` checks Parquet files and folders.
- The accepted measures: baseline, lift with a floor of 10 views, excess views over days 0 to
  7 and 0 to 28, peak day, half-life (censored), breadth, and `country_status` (tracked,
  appeared, not_published, unclear, insufficient_files).
- `daily`: yesterday's portal page, due re-reads, new links, the move log, the new country file
  (missing files retried for a week), and language views for new items and for 7- and 28-day
  follow-ups, one summary line per step.
- Story links carry their heading level; heading variants map to the ten standard headings;
  currency, unit, ship, magnitude and formula templates are rendered.
- The client retries timeouts and dropped connections, caps groups of hosts together (every
  `/w/api.php` request), counts only file downloads against the byte cap, and logs times in
  milliseconds.
- New dependencies: pyarrow (Parquet tables) and numpy (series arithmetic).
- Project skeleton: Apache-2.0 license, README, citation draft, CI on Python 3.10 to 3.13 with
  SHA-pinned actions, and Dependabot for the actions.
- `newsattention.client`: a sequential client for Wikimedia hosts. Every request carries the
  project's User-Agent with a contact URL, backs off on HTTP 429 and 5xx (honoring
  `Retry-After`), sends `maxlag` to the MediaWiki Action API, counts against call and byte
  caps, and is written to a request log (time, method, host, path, status, bytes). A 403 stops
  that source. Downloads are written once and made read-only.
- `newsattention.schema`: the Event, EventPage, Views and Attention tables as frozen pydantic
  models, and `newsattention validate FILE` for `.jsonl` and `.csv` files, including the unique
  key of each table.
- `newsattention.portal`: reads Current Events Portal day pages as wikitext with their revision
  ids and parses headings, events, story headings above nested events, article links and the
  cited news domains (archive links are unwrapped). Both the current and the older page layouts
  are read.
- `newsattention.wikidata`: linked titles to canonical titles, page ids and Wikidata ids (after
  redirects), Wikidata ids to titles in other languages, and page ids to titles on any language
  edition, in batches of 50.
- `newsattention.dpviews`: streams a daily differentially private page-view file and keeps the
  rows of chosen Wikidata items; reads the seven-column files in use and the six-column layout
  in the README; reads the dataset's directory listing.
- `newsattention.pageviews`: per-article daily views from the Analytics API (all access, human
  users), with zero days filled in only up to the last complete day.
- `newsattention.measures`: baseline (median of the 28 days before), lift, peak day, half-life
  and breadth.
- `newsattention sample`: builds a small linked sample step by step; each step is skipped on a
  re-run, so no request is spent twice; an event keeps one row per article when two of its
  links reach the same article through a redirect. `newsattention sizes` reports the size of a full
  backfill of the differentially private files from their directory listings.
- The client keeps a minimum interval between requests (0.35 s from the command line), under
  the Analytics API's limit of 200 requests a minute for clients identified by User-Agent.
- Documentation: prior art, sources, licenses, method (draft), automation (design), data card
  (skeleton) and ethics. The method re-reads each portal day after 7 and after 30 days.
