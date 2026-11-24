
# NewsAttention

Version {{version}}, built on {{built}}. Events from {{first_day}} to {{last_day}}; daily views
from {{views_from}} to {{views_to}}.

## What it is and who it is for

NewsAttention links each day's news events, as English Wikipedia's Current Events Portal lists
them, to how many people read the Wikipedia articles each event links to. Reading is counted
in two ways: by language edition (exact daily counts) and by country (Wikimedia's published,
privacy-protected daily counts). Simple measures of attention come with it: a baseline before
the event, the lift over it, excess views, the peak day, a half-life, and breadth across
languages and countries.

It is made for researchers in communication, journalism and the social sciences who study
public attention to news: how long attention to an event lasts, how it travels across
languages and countries, and which events get little of it. Page views stand for reading on
Wikipedia, not for all public attention.

This version holds {{events}} events on {{event_days}} days, linked to {{items}} Wikidata items
and {{articles_without_item}} English articles without an item, with views in {{languages}}
language editions and {{countries}} countries.

## Load a table

Each table is one configuration with one split, `train` (the Hub's name for a table that is not
split; nothing here is meant as training data). One table, one line:

```python
from datasets import load_dataset

events = load_dataset("{{dataset}}", "events", split="train")
```

The large tables are stored as one Parquet file per month (by the day of the view, or by the
event's day), so one month loads on its own:

```python
views = load_dataset("{{dataset}}", data_files="views_api/2026-10.parquet", split="train")
```

Any Parquet reader works too, for example `pandas.read_parquet("hf://datasets/{{dataset}}/events/")`.

A mirror of the same tables, one file per table, is on Kaggle: {{kaggle_url}}.

## The tables

{{tables_table}}

How the tables join:

- `event_id` joins `events`, `event_pages`, `attention`, `attention_summary` and
  `country_status`.
- `qid` (the Wikidata item) and `project` (the language edition, such as `en.wikipedia`) join
  the views and the measures. An English article that has no Wikidata item is named by its
  `page_id`, with an empty `qid`.
- `pages` is keyed by the English `page_id`; `event_pages` gives each link's `page_id`.

Field definitions are in the code's schema (`src/newsattention/schema.py` in the repository),
and `newsattention validate` checks a file against them. `manifest.json` lists every file with
its rows, size and SHA-256.

## Sources

- **Events:** English Wikipedia's Current Events Portal, one day page per day, read as
  wikitext through the MediaWiki Action API with the revision read (read {{read_portal}}). Each
  day is read again after 7 and after 30 days, and the newer reading replaces the older one.
- **Articles:** the links are resolved through the MediaWiki Action API of English Wikipedia:
  redirects, page ids and the Wikidata id of each article, a creation estimate from the first
  revisions, and the move log (read {{read_mediawiki}}).
- **Views by language edition:** the Wikimedia Analytics API, per-article daily page views
  (all access methods, human readers), exact counts (read {{read_analytics}}). English is
  fetched for every linked item, and up to five other language editions per item: those whose
  pages have the most views in the country files.
- **Views by country:** Wikimedia's differentially private daily page views by country,
  project and page (the `country_project_page` files), filtered to the linked items (files
  read {{read_country}}).

Every row is computed by code from these sources. No row is written or edited by hand, and no
row is produced or labeled by a language model.

## How each measure is made

All language measures are per event, item and language edition, from the exact counts. Day 0
is the event's day.

- **Baseline:** the median daily views over days -28 to -1 (all 28 days are needed).
- **Lift:** the views on a day divided by the baseline, only when the baseline is at least 10
  views a day; below that, a handful of views gives absurd ratios.
- **Excess views:** the sum over days 0 to 7, and over days 0 to 28, of the views minus the
  baseline; empty when the data end before that day.
- **Peak day and peak views:** the day from 0 to 28 with the most views (the earliest on a tie).
- **Half-life:** the days from the peak until the views first fall below half the peak; empty,
  and marked censored, when that has not happened by day 28 or by the last day with data.
- **Breadth, countries:** the countries with a published row for the item on day 0, in any
  language (a lower bound, because of the thresholds below).
- **Breadth, languages:** the language editions (of those fetched) with a lift of 2 or more on
  day 0 or day 1.

A measure stops at a series' last fetched day (the `series` table) and never reads an
unfetched day as zero.

## Country counts and country_status

The country counts are **Wikimedia's published, privacy-protected figures, used as published**.
Wikimedia adds random noise to each count and publishes a row only above a threshold (90, 550
or 1,000 views a day, by the country's risk class); some countries are never published.
NewsAttention never removes the noise, never fills in a missing row and never estimates an
unpublished country. **A missing row means "below the threshold or not published", never
zero.** Country counts count only the first 10 views per browser and day, so they must not be
added to or compared directly with the language counts.

`country_status` describes one event, item, language edition and country:

- `tracked`: a published row on at least 21 of the 28 days before the event. The day-0 lift
  uses the median of the published days only.
- `appeared`: a published row on day 0 or day 1, and on at most 2 of the 28 days before. The
  count rose above the publication threshold; it did not start from zero.
- `not_published`: no row on day 0 or day 1, although both days have a country file.
- `unclear`: published on day 0 or day 1 and on 3 to 20 of the days before.
- `insufficient_files`: too few days have a country file at all to decide (Wikimedia's own
  missing or empty files, or the start of the data).

In this version: {{status_shares}}.

## Page moves and old titles

Articles are renamed. For every linked English article, `pages` gives the moves inside the span
with the old titles and the move dates. The English views of a moved article are joined across
its titles at the move dates, and an old title that now redirects to the same article adds its
readers after the move; such series are marked `joined`. An old title that became another
article is left out. Moves in other language editions are not followed yet. In this version,
{{moved_pages}} linked articles moved inside the span.

## Roles: left out of this release

Most links of an event point to general articles (a country, a party, a person). Which link is
the event's own article, and which the larger story, was decided by a rule (no model) and
checked by hand on a weighted sample of 150 events. The rule did not reach its target of 90%:

- **The event's own article:** right for 82.2% of events, where answering "none" every time
  would be right for 86.4%; when the rule names an own article it is right 36% of the time
  (precision), and it finds 43% of the own articles (recall).
- **The larger story:** right for 71.2% of events, against 50.5% for "none" every time;
  precision 59%, recall 77%.

So the columns `role` and `role_confidence` are **not in this release**. The signals a reader
can use stay in: whether the event's own text links the article (`in_text`), the story
heading level it sits under (`story_level`), the article's estimated creation date and its
moves (`pages`). The three hand-checked sheets are now a development set; a later rule will be
checked on a new sample before any role is released.

## Limits

- **The portal's own choices.** Volunteers choose which events the portal lists, how they are
  worded and what they link. It leans toward English-language news. NewsAttention measures
  attention to the events the portal lists, not to all news.
- **The start date.** Events start on 2023-02-06, when the country files begin; the views start
  28 days earlier, for the baseline.
- **English first.** The events are from the English portal; English views are fetched for
  every linked item and followed up 1, 7 and 28 days after an event; other language editions
  are followed up once, 28 days after, so their measures are complete 28 days after an event.
- **What page views measure.** Reading on Wikipedia: not television, social media or news
  sites, and not agreement, emotion or who the readers are. Wikipedia's reach differs by
  country, language and access to the internet.
- **Gaps in the country files.** United States rows from 2023-02-06 to 2023-09-19, and every
  country's rows on seven days of 2023, come from Wikimedia's older method (`older_method_days`
  counts them); medium and higher-risk countries are published only from 2024-02-15; single
  days can be missing or empty.
- **Late edits.** The portal is edited for days after a date; the re-reads at 7 and 30 days
  catch most edits, and the latest reading is the one released.

## Licenses

- The counts, the links and every measure (every table but `events`) are under **CC0 1.0**.
- The event text in `events` is under **CC BY-SA 4.0**: {{credit}} Each event row gives the
  portal page (`portal_page`) and the revision read (`revision_id`); the page's history on
  Wikipedia lists its authors.
- A table that joins the event text with other tables and is shared is an adaptation and
  carries CC BY-SA 4.0. Results and statistics computed from the tables are not.
- `LICENSES.md` gives the license of each table and column. The code is under the Apache
  License 2.0, in the repository ({{repo}}).

## Corrections and removals

Use the issue forms of the repository ({{repo}}/issues/new/choose): one for a correction (a
wrong link, count or measure) and one for a removal (for example, an event or article that
should not be listed). Opening an issue there needs a free GitHub account; this dataset's
Community tab on Hugging Face (https://huggingface.co/datasets/{{dataset}}/discussions) is a
second route, with a free Hugging Face account. Each request is answered within 14 days. A removal is added to the
removal list that every build reads, so the rows leave the next version; earlier versions stay
in the Hub's file history. Corrections to an event's wording belong on the portal itself and
arrive with the next re-read. This version's removal list has {{removal_entries}} entries.

## How to cite

{{how_to_cite}}

## Updates

New versions are made by hand, about once a week, until an automatic daily update is in place.
Each version's `manifest.json` gives the last day covered and when each source was read. The
newest months change between versions (new events, the re-reads, the follow-up views); older
months change only when a 30-day re-read lands in them.

## Not affiliated

NewsAttention is not affiliated with, endorsed or sponsored by the Wikimedia Foundation.
Wikipedia is a trademark of the Wikimedia Foundation.

Curated by Obada Kraishan (College of Media and Communication, Texas Tech University). No
external funding.
