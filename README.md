# NewsAttention

NewsAttention is a daily dataset that links each day's news events to how many people read
about them on Wikipedia, by country and by language. It is built for communication and
journalism researchers who need open, comparable data on public attention: how long attention
to an event lasts, where it travels, and which events never get any.

**Status: release 0.1.0 is published** (24 November 2026):
- the dataset on Hugging Face: <https://huggingface.co/datasets/obadakr/newsattention> (tag
  `v0.1.0`);
- a mirror of the same tables on Kaggle:
  <https://www.kaggle.com/datasets/obadakraishan/newsattention>.

Version 0.1.0 holds 21,997 events from 2023-02-06 to 2026-11-22; daily views from 2023-01-09 to
2026-11-22. The tables, their licenses and how each measure is made are on the dataset card and
in the [release layout](docs/release-layout.md).

## What it measures
- **Events:** the dated news events that Wikipedia's volunteer editors list on the English
  Current Events Portal, with the articles each event links to and the news sites it cites.
- **Reading by language:** daily page views of each linked article in English and in other
  language editions, from the Wikimedia Analytics API (human readers only).
- **Reading by country:** daily page views of each linked article by country, from Wikimedia's
  differentially private page-view files.
- **Derived measures:** for each event, page and day, a baseline (the median of the 28 days
  before the event), the lift over that baseline, the peak day, a half-life and breadth (how
  many countries and languages read about it).

## What it does not measure
- **Page views are reading on Wikipedia, not all public attention.** People who follow the
  news on television, social media or news sites and never open Wikipedia are not counted.
  Wikipedia's readership differs across countries and languages.
- **Country counts are noisy and thresholded by design.** Wikimedia adds random noise to
  protect readers' privacy, releases a row only above a threshold, and never publishes some
  countries. NewsAttention uses these counts exactly as published: it never removes the noise,
  fills in missing rows or estimates countries that are not published.
- **The event list is an editorial selection.** The portal is written by volunteers and leans
  toward English-language news. An event that is not on the portal is not in the dataset.
- **No individual readers.** None of the sources hold data about individual readers or
  editors, and NewsAttention infers nothing about anyone.

## Install (development)
```bash
uv sync
uv run newsattention --help
uv run pytest
```

## Documentation
- [Method](docs/method.md)
- [Data sources](docs/sources.md)
- [Licenses](docs/licenses.md)
- [Release layout](docs/release-layout.md)
- [Data card](docs/data-card.md)
- [Corrections and removals](docs/corrections.md)
- [Prior art](docs/prior-art.md)
- [Automation (design)](docs/automation.md)
- [Ethics](docs/ethics.md)

## How to cite
Cite the dataset with its version:

> Kraishan, O. (2026). *NewsAttention: Daily news events linked to how many people read about
> them on Wikipedia* (Version 0.1.0) [Data set]. Hugging Face.
> https://huggingface.co/datasets/obadakr/newsattention

When you use the event text, please also credit Wikipedia's contributors: the text is from
Wikipedia's Current Events Portal, under CC BY-SA 4.0, and each event row names the portal page
and the revision it was read from. `CITATION.cff` gives the dataset's citation for GitHub's
"Cite this repository"; the dataset card's "How to cite" also gives a BibTeX entry.

## Corrections and removals
Use the repository's issue forms: one for a correction (a wrong link, count, measure or country
status) and one for a removal request. Each request is answered within 14 days; see
[docs/corrections.md](docs/corrections.md).

## Credit
The events come from Wikipedia's Current Events Portal, written by Wikipedia's volunteer
editors (CC BY-SA 4.0). Page views come from the Wikimedia Foundation (CC0 1.0). Wikipedia is
a trademark of the Wikimedia Foundation; NewsAttention is an independent project and is not
endorsed by or affiliated with the Wikimedia Foundation.

## License
The software is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)). The data:
the counts, the links and every measure under CC0 1.0, and the event text under CC BY-SA 4.0
with credit to Wikipedia's contributors; see [docs/licenses.md](docs/licenses.md).
