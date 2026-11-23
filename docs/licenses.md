# Licenses

Checked on 2026-11-13 from the primary pages quoted below. This page is not legal advice.

## Software
The NewsAttention code is licensed under the Apache License 2.0 (see `LICENSE`).

## Sources

| Source | License | Primary page and quote |
|---|---|---|
| Analytics API (per-article views, top articles, top per country) | **CC0 1.0** | [Access policy](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/access-policy.html): "Data provided by the API is available under the CC0 1.0 license". The API's own specification ([api-spec.json](https://wikimedia.org/api/rest_v1/metrics/pageviews/api-spec.json)) says the same: "Data provided by this API is available under the [CC0 1.0 license]" |
| Differentially private page views by country (`country_project_page` and the two historical sets) | **CC0 1.0** (by the general rule; the dataset's README names no license) | [Dumps license page](https://dumps.wikimedia.org/legal.html): "All Analytics datasets are available under the Creative Commons Zero (CC0) public domain dedication, unless otherwise specified." The [README](https://analytics.wikimedia.org/published/datasets/country_project_page/00_README.html) specifies nothing else |
| Page-view dumps (`pageviews`, `pageview_complete`) | **CC0 1.0** (same rule) | Same dumps license page, "Analytics Datasets" |
| Current Events Portal text | **CC BY-SA 4.0** (and GFDL) | Dumps license page: "all original textual content is licensed under the GNU Free Documentation License (GFDL) and the Creative Commons Attribution-Share-Alike 4.0 License." The [Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use), section 7, license contributed text under "Creative Commons Attribution-ShareAlike 4.0 International License" and GFDL: "Reusers may comply with either license or both." |
| Wikidata structured data (ids, sitelinks) | **CC0 1.0** | Dumps license page: "Copyrights of structured data in the main, Property, Lexeme, and EntitySchema namespaces are waived using the Creative Commons Zero (CC0) public domain dedication." [Wikidata:Licensing](https://www.wikidata.org/wiki/Wikidata:Licensing): "All structured data (i.e. the main, Property, Lexeme, and EntitySchema namespaces) is released into the public domain under Creative Commons Zero." |
| Wikipedia's names and logos | Trademarks of the Wikimedia Foundation | [Trademark policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_Trademark_Policy): marks may be used "to describe ... A derivative work of Wikimedia content in a way that is not misleading"; a domain name containing a mark needs permission; no use may "create the impression that your use is in any way endorsed, sponsored by, or is part of the Wikimedia Foundation" |

## Crediting the portal
Wikipedia's guidance on [reusing its content](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content) asks for credit "either by including a) a hyperlink (where possible) or URL to the page or pages you are re-using, b) a hyperlink (where possible) or URL to an alternative, stable online copy which is freely accessible, which conforms with the license, and which provides credit to the authors in a manner equivalent to the credit given on this website, or c) a list of all authors", and for "a licensing notice stating that the work is released under CC BY-SA". Changes must be indicated.

NewsAttention therefore:
- keeps, in every event row, the portal page name (`portal_page`) and the revision read
  (`revision_id`); together they give the URL
  `https://en.wikipedia.org/w/index.php?title=<page>&oldid=<revision_id>`, whose history lists
  the authors;
- states in the data card and in the events table's metadata: "Event text from Wikipedia's
  Current Events Portal, by Wikipedia contributors, CC BY-SA 4.0
  (https://creativecommons.org/licenses/by-sa/4.0/). Changed: wiki markup removed and the text
  split into one row per event";
- never edits the wording of an event; corrections happen on the portal and arrive with the
  next re-read.

## License of the release (decided 2026-11-23)
| Table | License | Why |
|---|---|---|
| `events` (event text, category, story headings, cited domains) | **CC BY-SA 4.0**, credited to Wikipedia's contributors with the page name and revision id | The text is the editors' work under CC BY-SA 4.0 |
| `event_pages` (which articles each event links to) | CC0 1.0 | The links are facts taken from the portal. A database built from a substantial part of a CC BY-SA 4.0 database can count as an adaptation where database rights exist (section 4(b) of the license), but Wikipedia's contributors waive those rights: "Where you own Sui Generis Database Rights covered by CC BY-SA 4.0, you waive these rights. As an example, this means facts you contribute to the projects may be reused freely without attribution." ([Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use), section 7a). Credit is given anyway |
| `pages`, `series` (article facts, fetched days) | CC0 1.0 | From the MediaWiki API's page facts and move log; facts, with nothing creative added |
| `views_api`, `views_dp` (exact language counts and noisy country counts) | CC0 1.0 | Both sources are CC0; NewsAttention adds nothing creative |
| `attention`, `attention_summary`, `country_status` (the measures) | CC0 1.0 | Computed from CC0 counts; keyed by NewsAttention's own event ids and Wikidata ids |

Every release carries a `LICENSES.md` that gives the license of each table and column, and each
Parquet file names its license in its own metadata. The code keeps the Apache License 2.0.
Kaggle takes one license per dataset: the Kaggle mirror shows CC BY-SA 4.0, the one license
that is true of every file, and its `LICENSES.md` gives each table's own license.

**What share-alike means for people who merge the tables.**
- Using the CC0 tables alone (counts and measures) carries no conditions; credit is welcome.
- Putting the CC BY-SA tables next to the CC0 tables in a collection does not change the CC0
  tables' license.
- A table that *joins* event text with anything else is an adaptation of CC BY-SA material: if it is shared, it must carry CC BY-SA 4.0 (or a compatible
  license) and credit the portal's editors. Results, figures and statistics computed from the
  tables are not adaptations of the text and can be shared under any terms.
- Quoting a few events in a paper is ordinary quotation with credit.

## Media-side measure: GDELT
GDELT's [terms](https://www.gdeltproject.org/about.html#termsofuse) allow "unlimited and unrestricted use for any academic, commercial, or governmental use of any kind without fee" and redistribution "in any form", provided that "any use or redistribution of the data must include a citation to the GDELT Project and a link to this website". A GDELT-based measure (for example the number of news articles that mention an event's article title or Wikidata entity each day) could therefore be released, but as a separate table that carries the GDELT credit, not inside the CC0 tables. Nothing was built with GDELT.
