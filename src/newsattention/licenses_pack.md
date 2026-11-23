# Licenses of NewsAttention {{version}}

Two licenses apply, one per table. This file says which applies to which table and column.

{{licenses_table}}

## CC0 1.0: the counts, the links and the measures

Every table except `events` is dedicated to the public domain under CC0 1.0 Universal
(https://creativecommons.org/publicdomain/zero/1.0/). Its sources are CC0 as well: the Wikimedia
Analytics API, Wikimedia's differentially private page views by country, and Wikidata's ids.
The links from events to articles are facts taken from the portal; Wikipedia's contributors
waive their database rights in such facts (Wikimedia Terms of Use, section 7a). Credit is
welcome and not required.

## CC BY-SA 4.0: the event text

The table `events` holds text from Wikipedia's Current Events Portal and is licensed under
Creative Commons Attribution-ShareAlike 4.0 International
(https://creativecommons.org/licenses/by-sa/4.0/).

{{credit}}

Each event row names the portal page (`portal_page`) and the revision read (`revision_id`).
The revision's address is `https://en.wikipedia.org/w/index.php?oldid=` followed by the
revision id; the page's history (`https://en.wikipedia.org/w/index.php?action=history&title=`
followed by the page name) lists the authors. The portal itself is at
https://en.wikipedia.org/wiki/Portal:Current_events.

## Joining the tables

- Using the CC0 tables alone carries no conditions.
- Putting `events` next to the CC0 tables in a collection does not change their license.
- A table that joins the event text with other tables, if shared, is an adaptation of CC BY-SA
  material: it must carry CC BY-SA 4.0 (or a compatible license) and credit the portal's
  contributors.
- Results, figures and statistics computed from the tables are not adaptations of the text.

## The code

The code that builds the tables is under the Apache License 2.0, in the repository
({{repo}}). Wikipedia is a trademark of the Wikimedia Foundation; NewsAttention is not
affiliated with it.
