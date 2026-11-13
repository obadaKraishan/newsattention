# Sources

Every claim below was read on **2026-11-13** on the primary page linked next to it; quotes are
exact. Licenses are on the [licenses](licenses.md) page.

## 1. Wikimedia Analytics API (page views)
Primary pages: [access policy](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/access-policy.html),
[API specification](https://wikimedia.org/api/rest_v1/metrics/pageviews/api-spec.json),
[page views](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/concepts/page-views.html),
[country data](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/concepts/country-data.html),
[troubleshooting](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/troubleshooting.html),
[rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits).

**Access rules.**
- "The API requires an HTTP User-Agent header for all requests." Preferred format:
  "`<client name>/<version> (<contact information>) <library/framework name>/<version>`".
  NewsAttention sends `newsattention/<version> (https://github.com/obadaKraishan)
  python-requests/<version>`.
- "To stay within a safe request rate, wait for each request to finish before sending another
  request."
- Rate limits: unauthenticated bot requests with a compliant User-Agent get **200 requests per
  minute**, enforced per minute; clients should "respect the Retry-After header provided with a
  429 Too Many Requests status code" and "limit the number of concurrent requests to 3 or fewer".
  The page notes that "The rate limits described on this page are new in 2026 and are subject to
  experimentation and change." In the prototype the API answered 429 about twice a minute at
  about 200 requests a minute; NewsAttention now spaces requests 0.35 s apart (about 170 a
  minute).

**The three endpoints that matter here** (from the specification):

| Endpoint | What it returns | Counts |
|---|---|---|
| `per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}` | "Returns a time series of numbers of page views for a wiki page." One item per day (or month): `project`, `article`, `granularity`, `timestamp` (YYYYMMDDHH), `access`, `agent`, `views` | **Exact** integers ("Number of page views"). `access` is `all-access`, `desktop`, `mobile-app` or `mobile-web`; `agent` is `all-agents`, `user`, `spider` or `automated`; `granularity` is `daily` or `monthly` |
| `top/{project}/{access}/{year}/{month}/{day}` | "Lists the 1000 most-viewed pages on a Wikimedia project." Each article has `article`, `rank`, `views`; `day` may be `all-days` | **Exact** integers |
| `top-per-country/{country}/{access}/{year}/{month}/{day}` | "Lists the 1000 most-viewed pages for a given country, across all Wikimedia projects, excluding page views from bots and web crawlers." Each article has `article`, `project`, `rank`, `views_ceil` | **Approximate** ("views_ceil": "Approximate number of page views"); "this endpoint omits countries and pages with 1000 or fewer views" |

The per-project country endpoint (`top-by-country`) is **bucketed**: "Instead of reporting
7,876,451 views, the API returns "views": "1000000-9999999"", and "The API only returns page
view data for countries with more than 100 page views in the requested time period."

**Gaps and zeros.** "404 not found responses from the API can mean that there are 0 page views
for the given project, time span and filters specified in the query", and "zero values are
omitted from API responses". Data for a day "was loaded on" the next day at 00:00 UTC in the
documentation's example; loading "is usually done within a few hours, but can take 24 hours or
more if there are problems". NewsAttention fills omitted days with zero only up to the last day
known to be complete. On 2026-11-13 the daily counts for 2026-11-12 were complete.

**Redirects.** "Redirects, particularly redirects based on alternate spellings of a page title,
aren't counted as views of the actual page." Views are requested for the canonical title.

## 2. Differentially private page views by country, project and page
Primary pages: [current README](https://analytics.wikimedia.org/published/datasets/country_project_page/00_README.html),
[current files](https://analytics.wikimedia.org/published/datasets/country_project_page/),
[historical README](https://analytics.wikimedia.org/published/datasets/country_project_page_historical/00_README.html),
[pre-2017 README](https://analytics.wikimedia.org/published/datasets/country_project_page_historical_pre_2017/00_README.html),
[Country and Territory Protection List](https://foundation.wikimedia.org/wiki/Legal:Wikimedia_Foundation_Country_and_Territory_Protection_List).

### The current set (from 2023-02-06)
- "Time range: 6 Feb 2023 - present"; "Time granularity: daily".
- **Columns.** The README lists six features: "country", "project", "page_id", "page_title",
  "item_id (If existing, the cross-project Wikidata QID for the page. If not existing, an empty
  string.)" and "gbc (the differentially-private number of pageviews this page_id received)",
  and names the files `<year>-<month>-<day>.csv`. **The files actually published are
  `YYYY-MM-DD.tsv`, tab-separated, without a header, with seven columns**: the country's name,
  its two-letter code, then project, page_id, page_title (with underscores), item_id and gbc
  (checked in the files for 2026-10-16 and 2026-11-12, and in the earliest file, 2023-02-06,
  which has 268,416 rows, all of seven columns).
- **Which views.** Only "the first 10 unique pageviews for a given device in a given day", and
  only pages that "have received >150 global pageviews on that day".
- **Noise.** Gaussian zCDP, "sensitivity=10 unique pageviews", with rho by risk class; "For lower
  risk countries, pageview counts are 95% likely to be within 35.7 pageviews of the true value.
  For medium risk countries, the 95% confidence interval is 176.5 pageviews. For higher risk
  countries, the 95% confidence interval is 352.5 pageviews."
- **Thresholds.** "only rows with >90 pageviews (for lower risk countries — >550 pageviews and
  >1000 pageviews for medium and higher risk countries, respectively) are released". The
  smallest count in the files read is 90: the threshold is applied before rounding.
- **Risk classes** (protection list): "0 to 60 — lower risk", "60 to 67.5 — medium risk",
  "67.5 to 75 — higher risk", and "75 to 100 — not published": "For reasons of user and editor
  safety, the Wikimedia Foundation does not publish aggregated data about them." The list names
  sixteen countries and territories as not published: "Afghanistan, Belarus, China, Cuba,
  Eritrea, Hong Kong, Iran, Macao, Myanmar, North Korea, Russia, Saudi Arabia, Syria,
  Turkmenistan, Vietnam, and Venezuela". The files read had 189 and 192 country codes.
- **Medium and higher-risk countries only from 2024-02-15**: "From 15 Feb 2024 on, this dataset
  includes information about countries deemed "medium risk" and "higher risk"".
- **Missing data.** "data from the United States was not published from 6 Feb 2023 to 19 Sep
  2023", and "seven days of data (19 Jun 2023; 25 Oct 2023; and 13, 17, 19, 23, and 27 Nov 2023)
  were previously missing"; for those, "we've made smaller datasets for those countries/days
  available using the same techniques ... as the historical pageview dataset". **The current
  files do hold United States rows for 2023-02-06 to 2023-09-19, but from that older method:**
  the 2023-02-06 file has 44,219 United States rows whose smallest count is 450 (the historical
  set's threshold), against 90 for every other country. So a file of that period mixes two
  methods, and NewsAttention records the smallest count per country and day as data. In the listing
  those seven files are about 6 MB, against 20 to 26 MB for normal days. The file for
  **2026-11-08 is empty** (0 bytes, posted 2026-11-09 02:39).
- **Bots.** "From 25 May 2023 on, a more aggressive filter was used to only retrieve
  human-contributed views, not bot/web indexer views. Data before this date may contain
  bot-influenced counts." Also: "Data from 6 Feb 2023 may be incomplete".
- **Titles.** "the title in the dataset might not be the canonical non-redirect name".
- **Size.** 1,376 files from 2023-02-06 to 2026-11-12, about **32.2 GB** in all (from the
  listing's rounded sizes); 17.8 MB for 2026-11-12, with yearly medians of 23, 25, 23 and 20 MB
  (2023 to 2026).
- **Timing.** Each day's file is posted at about 02:20 to 02:50 UTC the next day (2026-11-12 at
  02:33 UTC on 2026-11-13). Files are served gzip-compressed; a HEAD request that asks for no
  compression gives the full size.

### The two historical sets
| | `country_project_page_historical` | `country_project_page_historical_pre_2017` |
|---|---|---|
| Time range | "9 Feb 2017 - 5 Feb 2023" | "1 July 2015 - 8 Feb 2017" |
| Count column | "private_count" | "gbc" |
| Wikidata id | "item_id" | none |
| Noise | "Laplace noise (epsilon=1, noise scale=30)"; "95% likely to be within 89.9 pageviews of the true value" | "Laplace noise (epsilon=1, noise scale=300)" |
| Release threshold | "only rows with >450 pageviews are released" | "only rows with >3500 pageviews are released" |
| Which views | all views of pages with ">150 global pageviews" (no 10-per-device cap) | the same; before 2017-02-09 "WMF's internal systems did not drop edit previews ... and did not log page_ids" |
| Files | 2,183, about 13.8 GB; 5 days without a file (2017-06-26, 2017-07-24, 2020-07-19, 2020-07-20, 2022-10-19) | 589, about 0.16 GB, none missing |

The three sets differ in noise, thresholds and counting rules, so a series that crosses
2017-02-09 or 2023-02-06 changes method at that date.

## 3. Page-view dumps (for a backfill of language views)
Primary page: [pageview_complete](https://dumps.wikimedia.org/other/pageview_complete/readme.html).
"Pageview complete is our best effort to provide a comprehensive timeseries of per-article
pageview data for Wikimedia projects." Rows hold the wiki code, title, page id, "daily total"
and hourly counts. The daily `user` files for 2026-11-01 to 2026-11-12 are 0.47 to 0.82 GB each
(bzip2); the monthly `user` file for 2026-10 is 5.67 GB.

## 4. Wikipedia's Current Events Portal
Primary pages: [Portal:Current events](https://en.wikipedia.org/wiki/Portal:Current_events),
[Reusing Wikipedia content](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content),
[Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use).

- **Page names.** One page per day: `Portal:Current events/<year> <Month> <day>` (for example
  `Portal:Current events/2026 November 11`). Year pages (`Portal:Current events/1994` to
  `/2001`) summarize earlier years.
- **How far back.** Day pages start in 2002 (223 day pages for 2002) and cover every day from
  2003 (368 pages for 2003, 366 for 2004, 365 for 2005).
- **Layout.** Current pages start with `{{Current events|year=...|month=...|day=...}}` and list
  events under bold headings; older pages (for example 2004) put the events inside the
  template's `content=` parameter under `;Heading` lines. Events are bullets; a bullet with
  sub-bullets that cites no source is a story heading. Sources are external links at the end of
  an event.
- **Revisions.** The MediaWiki API returns each page's latest revision id and time
  (`prop=revisions`, up to 50 pages a request). Pages keep changing for days: the pages for
  2026-11-11 and 2026-11-12 were last edited on 2026-11-13.
- **Credit.** Text is reused with credit "either by including a) a hyperlink (where possible)
  or URL to the page or pages you are re-using, b) a hyperlink (where possible) or URL to an
  alternative, stable online copy ..., or c) a list of all authors." NewsAttention credits each
  event with its page name and revision id, which lead to the page's history.
- **Other language editions.** 122 language editions link a counterpart of the portal page. A
  first look at five: Spanish keeps day pages (`Portal:Actualidad/10 de abril de 2007`, at least
  2006 to 2014; recent years not checked), Japanese keeps monthly pages
  (`Portal:最近の出来事/2026年11月`), Russian keeps half-year archives
  (`Портал:Текущие события/Архив/2006-1`), and French and Chinese show no day archive among
  their portal's subpages. None was parsed.

## 5. Wikidata
Primary pages: [Wikidata:Licensing](https://www.wikidata.org/wiki/Wikidata:Licensing),
[Wikidata:Data access](https://www.wikidata.org/wiki/Wikidata:Data_access),
[maxlag](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter).

- Access: the Action API (`wbgetentities`, up to 50 ids a request), the Linked Data Interface
  (`https://www.wikidata.org/wiki/Special:EntityData/Q42.json`) and full dumps. The data-access
  page asks clients to "make liberal use of the `maxlag` parameter"; the maxlag manual
  recommends "`maxlag=5` (seconds)" for Wikimedia wikis.
- On 2026-11-13 Wikidata answered every request with `maxlag` ("Waiting for wdqs1011:
  13.483333333333 seconds lagged", type `wikibase-queryservice`): Wikidata's lag includes the
  query service. The client waited and retried, then stopped. Titles in other languages were
  taken instead from each Wikipedia's own API, by the page ids in the country files, and checked
  against the item's Wikidata id. Wikidata ids for English titles come from the English
  Wikipedia API (`prop=pageprops`, `ppprop=wikibase_item`), not from Wikidata.

## 6. A candidate media-side measure: GDELT
Primary page: [GDELT, Terms of Use](https://www.gdeltproject.org/about.html#termsofuse).
"all datasets released by the GDELT Project are available for unlimited and unrestricted use for
any academic, commercial, or governmental use of any kind without fee." "You may redistribute,
rehost, republish, and mirror any of the GDELT datasets in any form. However, any use or
redistribution of the data must include a citation to the GDELT Project and a link to this
website (https://www.gdeltproject.org/)." Nothing was built with GDELT.

## 7. Trademarks
Primary page: [Wikimedia Foundation Trademark Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_Trademark_Policy).
- Describing reuse is allowed: "You can use the non-stylized wordmarks (e.g., "Wikipedia") to
  describe: ... A derivative work of Wikimedia content in a way that is not misleading (e.g.,
  "the encyclopedic content on this site is derived from Wikipedia")."
- "You need permission to register or use a domain name that contains a Wikimedia mark in it."
- "Please do not create the impression that your use is in any way endorsed, sponsored by, or is
  part of the Wikimedia Foundation."
- "Please do not create a website that mimics the "look and feel" of a Wikimedia site."
- A notice near the first use of a mark is asked for "When reasonable". NewsAttention's name
  holds no Wikimedia mark, describes its sources in plain words and says it is not endorsed by
  or affiliated with the Wikimedia Foundation.
