# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
  re-run, so no request is spent twice. `newsattention sizes` reports the size of a full
  backfill of the differentially private files from their directory listings.
- Documentation: prior art, sources, licenses, method (draft), automation (design), data card
  (skeleton) and ethics.
