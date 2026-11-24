"""How to cite NewsAttention: the one definition the card, the Kaggle description and the
release check follow.

The citation is APA 7 for a data set, with the version of the release; the DOI of the code and
documents on Zenodo is added beside it once the archive exists.
"""

from __future__ import annotations

AUTHOR_APA = "Kraishan, O."
FAMILY, GIVEN = "Kraishan", "Obada"
ORCID = "https://orcid.org/0009-0007-7180-8620"
TITLE = "NewsAttention: Daily news events linked to how many people read about them on Wikipedia"
PUBLISHER = "Hugging Face"
URL = "https://huggingface.co/datasets/obadakr/newsattention"
#: The year of release 0.1.0.
YEAR = 2026
#: The day each release was published, and the DOIs of the code and documents on Zenodo (no
#: data table): one for all versions (it resolves to the latest) and one per release.
RELEASE_DATES = {"0.1.0": "2026-11-24"}
ZENODO_ALL_VERSIONS = "10.5281/zenodo.24487868"
ZENODO_RELEASES = {"0.1.0": "10.5281/zenodo.24487869"}
#: The credit the event text asks for, given after the citation.
WIKIPEDIA_CREDIT = (
    "When you use the event text, please also credit Wikipedia's contributors: the text is from "
    "Wikipedia's Current Events Portal, under CC BY-SA 4.0, and each event row names the portal "
    "page and the revision it was read from."
)


def apa(version: str, year: int = YEAR, markdown: bool = True) -> str:
    """The data set's citation (APA 7); the title in italics when ``markdown``.

    No full stop follows the address, as APA 7 writes it.
    """
    title = f"*{TITLE}*" if markdown else TITLE
    return f"{AUTHOR_APA} ({year}). {title} (Version {version}) [Data set]. {PUBLISHER}. {URL}"


def bibtex(version: str, year: int = YEAR) -> str:
    """The same citation as a BibTeX entry (braces keep the capitals of the names)."""
    title = TITLE.replace("NewsAttention", "{NewsAttention}").replace("Wikipedia", "{Wikipedia}")
    return "\n".join(
        [
            f"@misc{{kraishan_newsattention_{year},",
            f"  author = {{{FAMILY}, {GIVEN}}},",
            f"  title = {{{title}}},",
            f"  year = {{{year}}},",
            f"  version = {{{version}}},",
            f"  publisher = {{{PUBLISHER}}},",
            "  note = {Data set},",
            f"  url = {{{URL}}}",
            "}",
        ]
    )


def archive_sentence(version: str) -> str | None:
    """The release date and the Zenodo DOI of the code and documents, once the archive exists."""
    date = RELEASE_DATES.get(version)
    if date is None:
        return None
    text = (
        f"Release {version} was published on {date}. The code and documents that build the "
        "dataset (no data table) are archived on Zenodo: "
        f"https://doi.org/{ZENODO_ALL_VERSIONS} (all versions)"
    )
    if version in ZENODO_RELEASES:
        text += f"; release {version}: https://doi.org/{ZENODO_RELEASES[version]}"
    return text + "."


def how_to_cite(version: str) -> str:
    """The body of a "How to cite" section: the citation, the BibTeX entry, the release date and
    the Zenodo DOI of the code and documents (once released), then the credit."""
    parts = [apa(version), f"```bibtex\n{bibtex(version)}\n```"]
    archive = archive_sentence(version)
    if archive:
        parts.append(archive)
    parts.append(WIKIPEDIA_CREDIT)
    return "\n\n".join(parts)


def opens_with_citation(text: str, version: str) -> bool:
    """Whether the text's "How to cite" section opens with the citation, word for word."""
    head = "## How to cite\n"
    at = text.find(head)
    if at < 0:
        return False
    rest = text[at + len(head) :].lstrip("\n")
    first = rest.split("\n\n", 1)[0].strip()
    return first == apa(version)
