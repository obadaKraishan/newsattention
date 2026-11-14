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
(the same User-Agent, backoff, `maxlag`, request log and one-command-at-a-time lock as in
development). The job runs `newsattention daily`, which already exists and brings the store up
to D-1 from wherever it stopped, so a missed day, or a week of them, costs nothing:

1. **Events.** The portal pages from the day after the last one read to D-1, and every day
   whose re-read after 7 or 30 days is due (each re-read replaces the earlier read; the
   revision ids stay on record).
2. **Links.** New linked titles to canonical titles, page ids and Wikidata ids, and a fresh
   look at linked articles that had no Wikidata item a day earlier.
3. **Moves.** The English move log for the days not read yet.
4. **Country views.** The differentially private files from the day after the last one known
   (at least the last week, so an empty or missing file is asked for again for a week), and
   the rows of linked items; when new items appear, the last 29 files are filtered again so
   they have a baseline.
5. **Language views.** For an item with no series yet: English and up to five other languages
   over the whole span, and the old titles of a moved English page. For an item whose event
   is 7 or 28 days old and whose English series does not reach that day: one call that closes
   the gap, plus its old titles that redirect to it. The first live run (2026-11-14, for
   2026-11-13) made 215 calls: 14 for 10 new items and 201 follow-ups.
6. **Measures and checks** (`newsattention tables` and `validate`): the job rebuilds the tables;
   any failure stops it before anything is published and opens an issue with the counts.
7. **Publish** (only after the first release is approved, see below).

The state lives in the store (day files, the plan, its status and progress files and
`api/meta.json`), so a run that stops is resumed by the next one.

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
