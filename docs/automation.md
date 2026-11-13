# Automation (design)

**DESIGN, not built.** This describes how the dataset would update itself every day once the
backfill and the measures are settled. Nothing here runs yet, and no publishing step runs
without the maintainer's approval.

## Timing
Wikimedia publishes the differentially private file for day D at about 02:30 UTC on D+1 (the
file for 2026-11-12 appeared at 02:33 UTC on 2026-11-13), and Analytics API daily counts for D
are normally available a few hours after D ends. The daily job therefore runs at **06:00 UTC**
and processes **D-1**, with a retry at 12:00 UTC if a file is late.

## The daily job (GitHub Actions)
One workflow on a schedule, one job, strictly sequential requests through the project's client
(the same User-Agent, backoff, `maxlag` and request log as in development).

1. **Events.** Read the portal pages for D-1 (first read) and D-8 (the re-read after seven
   days, which replaces the first read). Each read stores the revision id; events whose text or
   links changed between the two reads keep their id when their first source is unchanged
   (see the method's event ids).
2. **Links.** Resolve the new and changed links to canonical titles, page ids and Wikidata ids
   (the English Wikipedia API, 50 titles per request; a typical day needs two to four requests).
3. **Country views.** Download the differentially private file for D-1 (about 18 MB) and keep
   the rows of every item linked by an event in the last 60 days. The file is read once and not
   kept by the job; its size and checksum go into the run's manifest.
4. **Language views.** For each item linked in the last 60 days, the views for D-1 in English
   and in its top five other languages. Two ways, to be chosen with the backfill:
   - **Per-article API calls**, spaced to keep the call count low: one call when an item is
     first linked (its 28-day baseline and the days since), then one call per item at +7 and
     +28 days that covers the whole range. At about 17 events and 110 new links a day, that is
     roughly 110 × 6 languages × 3 calls ≈ 2,000 calls a day, sequential (about 15 minutes).
   - **The daily page-view dump** (`pageview_complete`, all articles in all languages): one
     download a day instead of thousands of calls. Its size decides this (to be measured).
5. **Measures.** Recompute the attention rows of every event in the last 60 days (baseline,
   lift, peak, half-life, breadth); older events are final.
6. **Checks.** `newsattention validate` on every table, the row counts against the last run,
   and the call and byte counts against the job's caps. Any failure stops the job before
   anything is published and opens an issue with the counts (no data in the issue).
7. **Publish** (only after the first release is approved, see below).

The job keeps its state (the last day processed, the items being tracked, retries) in a small
JSON manifest stored with the data, so a missed day is picked up on the next run.

## Where the tables land
- **Hugging Face dataset** (`obadakr/newsattention`): the source of truth for the data.
  Parquet files partitioned by month (`events/2026-11.parquet`, `views_country/2026-11.parquet`,
  and so on), the manifest, and the data card. The git repository holds code and docs only.
- **Kaggle mirror**: the same Parquet files, refreshed weekly.
- **Zenodo**: a frozen snapshot each quarter with its own DOI version, for citation.
- **GitHub releases**: the code, tagged with each Zenodo snapshot.

## Release cadence
| Where | Cadence | What |
|---|---|---|
| Hugging Face | daily (or weekly, if daily commits prove noisy) | new and updated monthly partitions |
| Kaggle | weekly (Mondays) | full mirror |
| Zenodo | quarterly (first week of January, April, July, October) | snapshot with a DOI |
| GitHub | with each Zenodo snapshot | code release |

## Approval and secrets
- Publishing tokens (Hugging Face, Kaggle, Zenodo) are repository secrets that only the
  maintainer creates. Without them the job builds and validates the tables and stops.
- The first release of each channel is made by hand after the maintainer approves it; the
  scheduled job only updates channels that already exist.
- The workflow has `contents: read` permissions, actions pinned to commit SHAs, and no
  `pull_request_target` triggers.

## Does it need a language model?
Only for one question: which linked article is the event's own article. The portal links
an event to many pages (6.4 on average in the prototype), most of them general pages such as a
country or a political party. Rules may be enough (the article was created around the event,
it is the nearest story heading, its views jump on the event day); a hand-checked sample will show how far they
get on a hand-checked sample.

If rules fall short:
- **An open model** (Apache-2.0 or MIT, as the project's license rule requires for published
  outputs) would label the candidates. A day has about 17 events and about 110 candidate
  pages, so the job is small: a few hundred short prompts a week. It would run weekly on
  Kaggle (free GPU quota) rather than in the daily job, and it costs nothing in money.
- **A commercial model** would only serve as a second coder on a validation sample, and only
  with the maintainer's approval of the spend; its cost would be estimated at that time from
  the provider's current prices. Its labels would not be published.

## Costs
GitHub Actions minutes for a private repository are limited; once the repository is public they
are free. The daily job is expected to take 10 to 30 minutes. Storage on Hugging Face, Kaggle
and Zenodo is free at this size (see the data card for the sizes).
