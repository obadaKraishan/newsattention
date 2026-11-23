## What it is

NewsAttention links each day's news events, as English Wikipedia's Current Events Portal lists
them, to how many people read the Wikipedia articles each event links to: by language edition
(exact daily counts) and by country (Wikimedia's published, privacy-protected daily counts),
with simple measures of attention (baseline, lift, excess views, peak day, half-life, breadth).

Version {{version}}: {{events}} events from {{first_day}} to {{last_day}}, linked to {{items}}
Wikidata items, with views in {{languages}} language editions and {{countries}} countries. It is
made for researchers who study public attention to news. Page views stand for reading on
Wikipedia, not for all public attention.

This is a mirror of the Hugging Face dataset {{dataset}}
(https://huggingface.co/datasets/{{dataset}}), with the same tables, one file per table.

## Files

{{tables_table}}

`event_id` joins the event tables; `qid` (the Wikidata item) and `project` (the language
edition) join the views and the measures. `manifest.json` lists every file with its rows, size
and SHA-256 and when each source was read.

## Country counts

The country counts are Wikimedia's published, privacy-protected figures, used as published:
noise is never removed, a missing row is never filled in, and a missing row means "below the
threshold or not published", never zero. `country_status` says, for each event, item,
language and country, whether the country was `tracked`, `appeared`, `not_published`,
`unclear` or had `insufficient_files`.

## Roles left out

Which link is the event's own article was decided by a rule that scored below its 90% target on
a hand-checked sample (82.2% on the event's own article, against 86.4% for answering "none"
every time), so the role columns are not in this release. `in_text`, `story_level` and the
`pages` table (creation estimate, moves) stay in.

## Licenses

Every table except `events` is under CC0 1.0. The event text in `events` is under CC BY-SA
4.0: {{credit}} Kaggle shows one license for a dataset, so this page shows CC BY-SA 4.0, the one
license true of every file; `LICENSES.md` gives each table's own license.

## Sources

- English Wikipedia's Current Events Portal, read through the MediaWiki Action API
  (read {{read_portal}}).
- The Wikimedia Analytics API, per-article daily page views (read {{read_analytics}}).
- Wikimedia's differentially private daily page views by country (files read
  {{read_country}}).

## How to cite

{{how_to_cite}}

## Corrections and removals

Use the issue forms of the repository ({{repo}}); each request is answered within 14 days.

## Not affiliated

NewsAttention is not affiliated with, endorsed or sponsored by the Wikimedia Foundation.
Wikipedia is a trademark of the Wikimedia Foundation.
