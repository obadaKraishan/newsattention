# Ethics

## Privacy
- **No individual readers or editors.** None of the sources hold data about individual
  people: the portal is a list of public news events, the Analytics API returns counts per
  article and day, and the country files are aggregated with differential privacy. NewsAttention
  publishes no table about individual readers or editors and infers no personal attribute
  (such as nationality, politics or religion) about anyone.
- **The country counts are used exactly as published.** Wikimedia adds calibrated noise to
  each country count, releases a row only above a threshold, and does not publish countries on
  its Country and Territory Protection List that it classes as "not published". NewsAttention
  never tries to remove the noise, to fill in rows below the threshold, or to estimate counts
  for countries that are not published. Measures are computed only from published rows, and
  the documentation says where a missing row means "below the threshold" rather than "zero".
- **No re-identification.** Joining the country files with other data to learn about the
  readers of a page is out of scope and against the spirit of the privacy protection. Users of
  the dataset are asked not to attempt it.
- **Sensitive events.** The portal lists wars, attacks, disasters and crimes, which name
  places and sometimes people. NewsAttention adds nothing to what the portal already states.
  Event text is shipped only as the portal wrote it (see licenses), and corrections made on
  the portal reach the dataset when a day is re-read.

## Credit
- **Wikipedia's editors** write the Current Events Portal. Every event row names the portal page
  and the revision it came from, so each event can be credited to the editors in that page's
  history. Event text is CC BY-SA 4.0 (see [licenses](licenses.md)).
- **The Wikimedia Foundation** publishes the page views (CC0 1.0) and the differentially
  private country files. The data card credits both and links to their documentation.
- NewsAttention is an independent project. It does not use the Wikipedia or Wikimedia names or
  logos in its own name, and it does not suggest endorsement by the Wikimedia Foundation.

## Limits users should know
- Page views are reading on Wikipedia, which is not all public attention. Wikipedia's reach
  differs by country, language, age and access to the internet.
- The portal's event list is an editorial selection by volunteers and leans toward
  English-language news. Events that the portal never lists, and countries with little
  English-language coverage, are under-represented.
- See the [method](method.md) for the noise, the thresholds and the known gaps.

## Corrections and takedown
Corrections (a wrong link, a wrong date, an event that should be removed) can be reported
through the repository's issue tracker. Requests about the portal's text itself belong on the
portal page on Wikipedia, where the editors can change it; the dataset follows on its next
re-read. A contact address for private requests will be added before the first release.
