# Corrections and removals

Anyone can ask for a correction or a removal through the repository's issue forms: **Correction**
(a wrong link, count, measure, country status or page move) and **Removal request** (an event or
an article that should not be listed). Each request is answered within 14 days.

## What happens to a correction
1. The maintainer labels the issue `correction` and checks the claim against the sources.
2. A fault in the code is fixed with a test that fails without the fix; the next version is
   rebuilt with it, and the CHANGELOG names the issue.
3. The wording of an event is the portal's own. It is corrected on Wikipedia, and the next
   re-read of that day (after 7 and after 30 days) brings the change in. NewsAttention never
   edits an event's text.
4. Counts are never edited by hand. A count that differs from the source is a fault in the code
   or a later change at the source; either way the fix comes through a rebuild.

## What happens to a removal
1. The maintainer labels the issue `removal` and decides within 14 days, saying why in the
   issue.
2. If the request is accepted, one line goes into `data/removals.csv`:

   | Column | Meaning |
   |---|---|
   | `kind` | `event` (an event id), `item` (a Wikidata id) or `page` (an English page id) |
   | `id` | the event id, the Wikidata id (like `Q42`) or the page id (a whole number) |
   | `received` | the day the request arrived (YYYY-MM-DD) |
   | `issue` | the issue's number, or empty |
   | `reason` | `privacy`, `copyright`, `error` or `other` |

   The list holds identifiers only, never the reason's details or anyone's name.
3. Every release build reads the list and leaves out every row it names: an event takes its
   links, views and measures with it; an item or a page takes every row of that article. An
   article with a Wikidata item is listed by both its item and its page id.
4. `release check` fails if a row the list names is still in a pack, and the manifest records
   how many entries the list had and how many rows each table lost.
5. The next version is uploaded without those rows. Earlier versions stay in the dataset's file
   history; the issue says so.

`newsattention release build` reads `data/removals.csv` by default (`--removals` names
another file). The file starts with its header only.
