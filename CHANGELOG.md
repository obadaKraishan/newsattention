# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The repository is public (2026-11-24); `main` is protected by the four CI checks (Python 3.10
  to 3.13), and every change goes through a pull request.
- `newsattention.citation`: the data set's citation, defined once (APA 7 for a data set, with
  the version, and the same as a BibTeX entry). The card's and the Kaggle description's "How to
  cite" open with it, then the BibTeX entry, then the credit to Wikipedia's contributors;
  `release check` fails when either does not open with it.
- `release card` writes the card and the Kaggle description again from a pack's manifest,
  leaving every data file as it is.
- `release build` writes a version's files from the tables into `data/release/VERSION/`: the
  nine tables (one file per month for the large ones), a `manifest.json` with every file's
  rows, size and SHA-256, each table's license and the first and last day each source was
  read, a `LICENSES.md` that gives the license of each table and column, and the dataset card.
  Each Parquet file names its table, license and version in its metadata; the event files
  carry the credit line. The role columns (`role`, `role_confidence`) do not ship.
- `release check` fails on a role column, a file outside the manifest or different from it, a
  table without its license, event text in a CC0 table, a country row below the smallest
  published count (a zero or a filled row), a row the removal list names, and a raw HTML tag or
  the wrong configurations in the card.
- `release kaggle` writes the Kaggle mirror's folder (one Parquet file per table, the same
  `LICENSES.md`, a manifest, `dataset-metadata.json` and a cover drawn by code at 560 by 280).
- `page visibility` and `page headings`: signed-out checks of the dataset's Hugging Face page
  (no token, no cookie, no netrc login).
- The removal list `data/removals.csv` (empty), which every release build reads, and two issue
  forms (a correction and a removal request, answered within 14 days), with
  `docs/corrections.md` saying what happens to each.
- `.zenodo.json` for a Zenodo record of the code and documents only.
- `validate` accepts a released `event_pages` file that lacks both role columns (the release
  leaves them out); a file with one of them and not the other still fails.
- `review-key`: the rule's answers for the sampled events from the current code, with the
  Wikidata classes or without them (`--without-classes`), recording the rule's version and the
  SHA-256 of `roles.py`; it refuses when the tables show an event's links otherwise than its
  sheet did.
- `review-score`: compares the rule's answers with filled sheets. For each question it gives
  the weighted share right over all events, with a 90% interval from a stratified bootstrap,
  by stratum, year and the rule's confidence, and the three kinds of difference (the rule
  names a link where the hand answer is none, the reverse, or both name different links). It
  prints and writes aggregates only; `--differences` also writes the differences by event
  number (no titles, no text). It refuses a key made with another `roles.py`, and with
  `--freeze` a `roles.py` other than the frozen one.
- `review-recheck`: a blind copy of some sampled events for a second pass by the same reader,
  drawn within the strata in proportion to the sample (seeded, without looking at any answer),
  in a new order with new numbers, and its key in a separate file.
- `daily` follows English series up at days 1, 7 and 28 (the day-1 follow-up is new: day-0
  views of an item already in the plan arrive the next day instead of a week later), and every
  other language once, at day 27 of an event (days 0 to 27, on the 28th day). Other-language
  measures of an event are complete 28 days after it.
- Linked English articles with no Wikidata item get an English call by title over the span and
  the same follow-ups; their series is named by the page id.
- Docs: the method records the hand check of the roles as done (the frame, the weights, two
  development checks, the freeze and the scores of rule version 1, which is below its 90%
  target on both questions); the data card carries the build of 2026-11-17 and the roles'
  measured limits; the automation page gives what a daily run costs.

### Changed
- The roles are left out of the first release: rule version 1 scored below its target, and
  below answering "none" every time on the event's own article. The method records the
  comparison with precision and recall; the three hand-checked sheets are now a development set.
- The release layout (one configuration per table, one split, monthly files) and the licenses
  (CC0 1.0 for every table but `events`, CC BY-SA 4.0 for the event text) are decided.
- CI runs the full Python matrix (3.10 to 3.13) when the workflow is started by hand; pushes
  and pull requests still run 3.12 only.
- The data card describes release 0.1.0 as built on 2026-11-23 (events through 2026-11-22).
- `series`, `attention` and `attention_summary` gain a `page_id` column, and `qid` may be empty
  in `views_api`, `series`, `attention` and `attention_summary`: such a row is an English
  article with no Wikidata item, named by its page id. A page-id series is left out once the
  article has an item, since its views are then under the item.
- The portal parser renders the six templates the backfill met without a rule (`#expr`,
  `AFL`, `INRConvert`, `Renminbi`, `circa`, and `unreliable inline`, which is dropped).
- One Wikimedia command at a time: every command that sends requests takes a lock on one file
  for as long as it runs; a second command stops with a plain message naming the holder, or
  queues with `--wait`. `--cap-action` and `--cap-wikidata` cap Wikipedia's and Wikidata's API
  apart.
- `daily` catches up: each step starts where the store stops (portal days after the last one
  read, the move log, country files after the last one known), and the 7-day and 28-day
  follow-ups are worked out from what each series already covers, so a run after missed days
  loses nothing.
- Each language-view call records the days it asked for; `series` (new table) gives, per item
  and language, the first and last day fetched, and the measures stop at a series' last day
  instead of reading unfetched days as zero. Calls made before this have their last day in
  `store/api/meta.json`.
- `country_status`: when neither day 0 nor day 1 has a row and one of them has no country file,
  the status is `insufficient_files`, not `not_published`.
- The `pages` table lists only articles that a current event links.
- Roles (`newsattention.roles`, rule version 1): every event page gets `event` (the article
  about this happening, at most one per event), `story` (the larger ongoing story) or
  `context`, with a confidence (`high`, `medium`, `low`) from how many stored signals agree:
  page creation against the event day, moves into the articles, the Wikidata class (by the
  head word of its English label), the event's year in the title, words shared with the
  event's text, a jump in views, and whether the text or a story heading links it. No model.
  `event_pages` gains `role_confidence`.
- `api-backfill --max-calls N` stops at the first chunk boundary after N calls, so a long run
  can be done in slices and another command can take the lock in between.
- `review-sheets`: draws the hand-checked sample (150 events, seeded, spread evenly over 2023 to
  2026, half where the rule finds an `event` page), writes three blind sheets of 50 and a guide,
  and keeps the rule's answers in a separate answer key that the sheets never reference. A
  separate design file records the frame, the strata and each sampled event's chance of being
  drawn, so later rules can be scored with weights; `--through` ends the frame on a given day,
  and the command refuses to draw again over existing sheets.
- Review sheets (`newsattention.review`): `.xlsx` workbooks written with the standard library,
  with a guide tab and one block per event (date, category, text, numbered links that open the
  article) and two dropdowns per event; `review-check FILE...` reads filled sheets back and
  reports what is missing or invalid by event number, never by title (`--answers` keeps them).
- `links` (and so `daily`) asks again about a linked article that had no Wikidata item, once
  the answer is a day old: new articles often get their item a day or two late, and language
  views are planned per item. `daily` plans the old titles of a new item whose page moved.
- `classes`: the Wikidata "instance of" classes of every linked item, and for three tiers of
  classes their English label and "subclass of" values, in batches of 50; resumable, and it
  stops rather than pushes when Wikidata stays lagged.
- `old-titles`: plans the views that reach a moved page through its old titles after each move,
  for old titles that now redirect to the same page (a title that became another article is
  left out). The series add those views, a later call replacing the days it asked for, and
  `daily` follows them up with their page.
- Backfill commands, each resumable: `portal-backfill` and `reread` (each day read again 7
  and 30 days after it ends; a changed revision replaces the day's events and every read
  stays on record), `reparse` and `parse-report` (what the parser could not read, by month),
  `links`, `pages` (creation dates estimated from page ids, checked on a random sample, and the
  English move log), `dp-download` and `dp-filter` (the country files, with the documented
  gaps and each day's smallest count per country recorded), `plan` (append-only) and
  `api-backfill` (raw chunks of 250 calls).
- Docs: the data card and the method carry the numbers of version 1 as built (portal days
  2023-02-06 to 2026-11-12); the sources page records the request rates the backfill met.
- The client's spacing between requests counts from when a request really starts: a sleep
  that ended late made the next request up to about 34 ms early.
- `api-check`: checks, without a request, that every planned language-view call has its saved
  result: each chunk is read in full and compared with the plan and the status log (row count,
  identity, dates inside the span, no day twice), and the indices to fetch again are listed.
- Raw files, the store's state files (progress, status, revisions, coverage, country rows) and
  the request log are flushed to the disk before a run moves on (`F_FULLFSYNC` on macOS, which
  also empties the drive's cache; `fsync` elsewhere). A chunk of language views is on the disk
  before its status and progress lines are written, so an external drive that drops off stops
  the run instead of losing a chunk.
- `tables`: events, event_pages, pages, views_dp, views_api (moved English pages joined across
  their titles and flagged), attention, attention_summary and country_status, as Parquet files
  by month; `validate` checks Parquet files and folders.
- The accepted measures: baseline, lift with a floor of 10 views, excess views over days 0 to
  7 and 0 to 28, peak day, half-life (censored), breadth, and `country_status` (tracked,
  appeared, not_published, unclear, insufficient_files).
- `daily`: yesterday's portal page, due re-reads, new links, the move log, the new country file
  (missing files retried for a week, and a file that comes late filtered when it arrives), and
  language views for new items and for 7- and 28-day
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
