# Prior art

Checked on 2026-11-13.

## The answer
**No living, public dataset links dated news events to Wikipedia page views by country, and
none does so by language edition as a daily, updated series.** Each half of the link exists on
its own:

- **Events without views.** Parsers and knowledge graphs of the Current Events Portal
  (WikiEvents at ESWC 2023, EventKG, OEKG, WCEP, PastEvents) carry the events and their linked
  articles but no page views.
- **Views without events.** Wikimedia's differentially private country files, the Analytics
  API and the living archives of daily top articles (on Hugging Face and Kaggle) carry page
  views but no events.
- **Research datasets that join the two are frozen and narrow.** The closest is the
  WikiNewsTopics repository of Gildersleve, Lambiotte and Yasseri (2023): one year of portal
  events (2017-12-01 to 2018-11-30) linked to English articles and their daily English views,
  with no country or other-language views, no stated license and its larger files on Dropbox.
  Ruprechter, Burghardt and Helic (2023) give 7-day view totals in four language editions for
  17,490 event articles drawn from Wikidata, not the portal, with no daily series and reader
  country only as a predictor. Tizzoni et al. (2020) give news coverage and daily views by US
  state for one topic (Zika, 2016).

What NewsAttention adds: the link itself, maintained every day; country and language views
for every linked article; derived attention measures (baseline, lift, peak, half-life,
breadth); and an open license with credit to the portal's editors.

## Resources

"GitHub API", "HF API", "Zenodo API" and "Kaggle CLI" are read-only listings of each
resource's metadata (last push, license, version dates).

| # | Resource | What it links | Granularity | License (as stated) | Living or frozen | Last update (where seen) |
|---|---|---|---|---|---|---|
| 1 | Gildersleve, Lambiotte & Yasseri, "Between News and History" ([arXiv 2211.07616](https://arxiv.org/abs/2211.07616); *J. Comput. Soc. Sci.* 6(2), 2023, doi:10.1007/s42001-023-00215-w); [pgilders/WikiNewsNetwork-01-WikiNewsTopics](https://github.com/pgilders/WikiNewsNetwork-01-WikiNewsTopics) | Portal events → English articles → daily English views (plus clickstream and the link network) | Day; English only; no country | Not stated (GitHub API: no license) | Frozen (2017-12-01 to 2018-11-30) | Last push 2023-07-03 (GitHub API) |
| 2 | Wikimedia differentially private page views by country, project and page ([analytics.wikimedia.org](https://analytics.wikimedia.org/published/datasets/country_project_page/00_README.html)); method in Adeleye et al. ([arXiv 2308.16298](https://arxiv.org/abs/2308.16298)) | Page × country × project → noisy daily views | Day; country; every project | CC0 for all Analytics datasets ([dumps legal page](https://dumps.wikimedia.org/legal.html)); the README names none | Living (raw data, no events) | 2026-11-12 file posted 2026-11-13 02:33 UTC (directory listing) |
| 3 | WCEP multi-document summarization (Gholipour Ghalandari et al., [ACL 2020](https://aclanthology.org/2020.acl-main.120/); [complementizer/wcep-mds-dataset](https://github.com/complementizer/wcep-mds-dataset)) | Portal event summaries → cited news articles | Event (dated); English; no views | Repository: MIT; the dataset's own license not stated | Frozen (2016-08-25 to 2019-08-20) | Last commit 2022-11-03 (GitHub API) |
| 3a | WCEP-10 on Hugging Face ([ccdv/WCEP-10](https://huggingface.co/datasets/ccdv/WCEP-10)) and about 20 copies | As WCEP, ten articles per event | As WCEP | Not stated | Frozen | 2024-09-10 (HF API) |
| 4 | **WikiEvents (ESWC 2023)**: Michaelis, Huang & Usbeck, SEMMES workshop ([CEUR Vol-3443](https://ceur-ws.org/Vol-3443/ESWC_2023_SEMMES_WikiEvents.pdf)); data [doi:10.25592/uhhfdm.11447](https://www.fdr.uni-hamburg.de/record/11447); extractor [semantic-systems/current-events-to-kg](https://github.com/semantic-systems/current-events-to-kg) | Portal events → summaries, linked articles, Wikidata entities, places, time spans (RDF) | Day; English portal; no views | Data: CC BY-SA 4.0; extractor: GPL-3.0 | Frozen release (2020-01 to 2022-12); the extractor can be re-run | Data 2023-02-07; extractor last commit 2023-03-21 |
| 5 | **WikiEvents (NAACL 2021)**: Li, Ji & Han, document-level event argument extraction ([2021.naacl-main.69](https://aclanthology.org/2021.naacl-main.69)); [raspberryice/gen-arg](https://github.com/raspberryice/gen-arg). Unrelated to row 4 despite the name | Documents → annotated events and arguments | Document; English; no views | Repository: MIT; dataset license not checked | Frozen | Last push 2023-03-28 (GitHub API) |
| 6 | EventKG (Gottschalk & Demidova; [Zenodo 10424118](https://zenodo.org/records/10424118), v3.2) | Events from Wikidata, DBpedia, YAGO, the portal and event lists → entities, relations, times, places | Event; 15 languages; no views | Zenodo: CC BY-SA 4.0 | Frozen versions | v3.2, 2023-12-22 (Zenodo API) |
| 7 | OEKG, Open Event Knowledge Graph ([Zenodo 4503163](https://zenodo.org/records/4503163), v2.1) | EventKG and six other event datasets | Event; multilingual; no views stated | Zenodo: CC BY-SA 4.0 | Frozen | v2.1, 2021-02-01 (Zenodo API) |
| 8 | EventKG+Click (Abdollahi, Gottschalk & Demidova, [arXiv 2010.12370](https://arxiv.org/abs/2010.12370); [saraabdollahi/EventKG-Click](https://github.com/saraabdollahi/EventKG-Click)) | EventKG events → language-specific clickstream counts | Event; three language editions; no country | CC BY 4.0 (README) | Frozen | Last push 2021-11-30 (GitHub API) |
| 9 | PastEvents ([p-e-w/pastevents](https://github.com/p-e-w/pastevents)) | A searchable archive of the portal | Day; English; no views | Code: AGPL-3.0; content license not checked (the site refuses scripted requests) | Said to update daily; not checked | Last push 2024-04-10 (GitHub API) |
| 10 | Kaggle "Current Events on Wikipedia" (thebiggerbang/wikipedia-current-events) | Portal events (one JSON file) | Not checked | Not checked (page needs a browser) | Frozen | 2018-03-27 (Kaggle CLI) |
| 11 | Hugging Face [Reubencf/wikipedia-current-events-2026](https://huggingface.co/datasets/Reubencf/wikipedia-current-events-2026) | Portal text by day and section, as instruction pairs | Day; English; no views | Not stated | Frozen | 2026-04-09 (HF API) |
| 12 | Hugging Face [nevirim/wikipedia-attention-13lang](https://huggingface.co/datasets/nevirim/wikipedia-attention-13lang) | Daily top-1,000 articles in 13 language editions, with a cross-language "spike" signal by Wikidata id | Day; language; top 1,000 only; no country; no events | CC0-1.0 (card) | Living, daily | Created 2026-11-08; last modified 2026-11-12 (HF API) |
| 13 | Hugging Face [vtasca/wikipedia-pageviews](https://huggingface.co/datasets/vtasca/wikipedia-pageviews) (also on Kaggle and GitHub) | Daily top-100 English articles → views | Day; English; no country; no events | Card: "cc" (no version) | Living, daily (GitHub Actions) | 2026-11-12 (GitHub API) |
| 14 | Kaggle daily top-article sets (canerkonuk/wikipedia-top-viewed-articles; danielaijdkx/indonesian-wikipedia-daily-top-articles) | Top articles → views | Day; projects; country not checked | Not checked (pages need a browser) | Living | 2026-11-12 and 2026-11-13 (Kaggle CLI) |
| 15 | Kaggle "Web Traffic Time Series Forecasting" (2017 competition) | About 145,000 Wikipedia pages → daily views | Day; language, access and agent in the page key; no country; no events | Not checked (rules page needs a browser) | Frozen (2015-07-01 to 2017-09-10, per third-party descriptions) | Files dated 2019-12-11 (Kaggle CLI) |
| 16 | Wikimedia's Pageviews Analysis tools (Pageviews, Topviews, Langviews) | Article → views; top articles per project; one article across languages | Day; project; no country; no events | Data from the Analytics API (CC0); the tools are interactive, with no dataset release | Living tools | Not applicable |
| 17 | Analytics API, most-viewed pages per country (`top-per-country`) | Country → its 1,000 most-viewed pages that day, across projects | Day; country; approximate counts (`views_ceil`) | CC0 1.0 (API spec) | Living API, no events | Not applicable |
| 18 | Horta Ribeiro et al., "Sudden Attention Shifts on Wikipedia During the COVID-19 Crisis", ICWSM 2021 ([epfl-dlab/wiki_pageviews_covid](https://github.com/epfl-dlab/wiki_pageviews_covid)) | Articles by topic → daily views around mobility restrictions | Day; 12 language editions; no country | Not stated (GitHub API: no license) | Frozen | Last push 2021-05-23 (GitHub API) |
| 19 | Tizzoni et al., Zika 2016 ([Zenodo 3603916](https://zenodo.org/records/3603916)), for *PLOS Comput. Biol.* 16(3), 2020 | GDELT news, TV captions, Zika article views, case counts | Day; US, by state and city; one topic | CC BY 4.0 | Frozen (2016) | 2020-03-02 (Zenodo API) |
| 20 | Ruprechter, Burghardt & Helic, "Poor attention", *PLOS ONE* 18(11), 2023 ([ruptho/wiki-event-bias](https://github.com/ruptho/wiki-event-bias); [Zenodo 7701969](https://zenodo.org/records/7701969)) | 17,490 event articles (Wikidata items with a date and a country) → 7-day views and edits | Event; en, de, it, es; reader country only as a predictor | Zenodo: CC BY 4.0; code: GPL-3.0 | Frozen (events 2016 to 2020) | Zenodo v1.0 2023-03-06 |
| 21 | García-Gavilanes, Tsvetkova & Yasseri, aircraft-crash attention data ([Zenodo 4977739](https://zenodo.org/records/4977739)) | Aircraft crashes → views and edits | English and Spanish; no country | CC0 | Frozen | 2016-09-13 (Zenodo API) |
| 22 | Meier, "Using Wikipedia Pageview Data to Investigate Public Interest in Climate Change at a Global Scale", WebSci 2024 (doi:10.1145/3614419.3644007) | 3,965 climate articles → country views (213 countries, 2017 to 2022) | Day; country; one topic | No data release found | Frozen study | 2024 |
| 23 | WikiLingDiv ([Zenodo 22127016](https://zenodo.org/records/22127016), v1.1) | Country × year × language edition → total views | Year; country × language; no articles; no events | CC BY 4.0 | Frozen | v1.1, 2026-08-27 (Zenodo API) |

## Notes
- **WikiNewsTopics (row 1)** is the method to cite: it is the only study that uses the portal
  as its event source and links events to daily views. Its event table is in the repository as
  an HDF5 file, not a documented dataset.
- **The two WikiEvents (rows 4 and 5)** are different things. The ESWC 2023 graph is the
  closest event-side resource (daily, with linked articles and Wikidata ids), but it has no
  views and its data stop at 2022-12.
- **Living page-view archives (rows 12 to 14)** link no events and have no country.
  The 13-language "spike" signal of row 12 is the nearest living attention product, and it is
  very new (created 2026-11-08).
- **Country views in research (rows 19, 20, 22)** are single-topic or frozen; none uses the
  portal's events.
- Also seen and not relevant: a 2026 data bundle that uses portal text as news context for
  stock prices (no views), and small, stale repositories of portal scripts.

## Pages that need a browser
These pages refuse scripted requests or need a login; they were not opened with browser
automation. They do not change the answer above.
- <https://pastevents.org/>: content license, downloads, whether it still updates daily.
- <https://dl.acm.org/doi/10.1145/3614419.3644007>: data availability of Meier (2024).
- <https://link.springer.com/article/10.1007/s42001-023-00215-w>: the published data
  statement of Gildersleve et al. (2023).
- Kaggle dataset and competition pages in rows 10, 14 and 15: descriptions and licenses.

## Not checked
The clickstream period of EventKG+Click, the dataset license of the NAACL 2021 WikiEvents,
the data release of Gozzi et al. (2020), and any GDELT-to-Wikipedia dataset beyond Tizzoni
et al. (two searches found none).
