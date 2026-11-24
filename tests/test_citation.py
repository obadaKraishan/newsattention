"""The data set's citation: one definition, and the card and the Kaggle text open with it."""

from __future__ import annotations

import json
from pathlib import Path

from newsattention import citation, release
from tests.test_release import make_tables

WANTED = (
    "Kraishan, O. (2026). *NewsAttention: Daily news events linked to how many people read "
    "about them on Wikipedia* (Version 0.1.0) [Data set]. Hugging Face. "
    "https://huggingface.co/datasets/obadakr/newsattention"
)


def test_the_citation_is_apa_7_word_for_word():
    assert citation.apa("0.1.0") == WANTED
    plain = citation.apa("0.1.0", markdown=False)
    assert "*" not in plain and plain.endswith("/obadakr/newsattention")  # no full stop
    assert ": Daily news" in plain and "(Version 0.1.0)" in plain


def test_the_bibtex_entry_says_the_same():
    entry = citation.bibtex("0.1.0")
    assert entry.startswith("@misc{kraishan_newsattention_2026,")
    for part in (
        "author = {Kraishan, Obada}",
        "title = {{NewsAttention}: Daily news events linked to how many people read about "
        "them on {Wikipedia}}",
        "year = {2026}",
        "version = {0.1.0}",
        "publisher = {Hugging Face}",
        f"url = {{{citation.URL}}}",
    ):
        assert part in entry
    assert entry.count("{") == entry.count("}")


def test_how_to_cite_opens_with_the_citation_then_bibtex_then_the_credit():
    body = citation.how_to_cite("0.1.0")
    first, second, third = body.split("\n\n", 2)
    assert first == WANTED
    assert second.startswith("```bibtex\n@misc{") and second.endswith("```")
    assert third == citation.WIKIPEDIA_CREDIT
    text = "# X\n\n## How to cite\n\n" + body + "\n\n## Next\n"
    assert citation.opens_with_citation(text, "0.1.0")
    assert not citation.opens_with_citation(text, "0.1.1")
    assert not citation.opens_with_citation("## Other\n", "0.1.0")
    assert not citation.opens_with_citation("## How to cite\n\nPlease cite us.\n", "0.1.0")


def test_the_card_and_the_kaggle_text_open_with_it(tmp_path: Path):
    tables = make_tables(tmp_path)
    pack, kaggle = tmp_path / "pack", tmp_path / "kaggle"
    release.build_pack(tables, pack, "0.1.0")
    release.build_kaggle(pack, kaggle)
    card = (pack / "README.md").read_text()
    meta = json.loads((kaggle / "dataset-metadata.json").read_text())
    assert citation.opens_with_citation(card, "0.1.0")
    assert citation.opens_with_citation(meta["description"], "0.1.0")
    assert release.check_pack(pack) == [] and release.check_kaggle(kaggle, pack) == []


def test_check_fails_when_the_citation_is_not_first(tmp_path: Path):
    tables = make_tables(tmp_path)
    pack, kaggle = tmp_path / "pack", tmp_path / "kaggle"
    release.build_pack(tables, pack, "0.1.0")
    release.build_kaggle(pack, kaggle)
    card = (pack / "README.md").read_text()
    (pack / "README.md").write_text(card.replace(WANTED, "Please cite this data set."))
    meta_path = kaggle / "dataset-metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["description"] = meta["description"].replace(WANTED, "Cite us.")
    meta_path.write_text(json.dumps(meta))
    assert any("does not open with the data set's citation" in p for p in release.check_pack(pack))
    assert any("'How to cite' does not open" in p for p in release.check_kaggle(kaggle, pack))
    # release card writes both again from the manifest; the data files stay as they are.
    before = {
        f["path"]: f["sha256"] for f in json.loads((pack / "manifest.json").read_text())["files"]
    }
    written = release.rewrite_card(pack, kaggle)
    assert len(written) == 2
    assert release.check_pack(pack) == [] and release.check_kaggle(kaggle, pack) == []
    assert all(release.sha256(pack / p) == h for p, h in before.items())


def test_the_card_command(tmp_path: Path, capsys):
    from newsattention import cli

    tables = make_tables(tmp_path)
    pack, kaggle = tmp_path / "pack", tmp_path / "kaggle"
    release.build_pack(tables, pack, "0.1.0")
    release.build_kaggle(pack, kaggle)
    removals = tmp_path / "removals.csv"
    removals.write_text("kind,id,received,issue,reason\n")
    args = ["release", "card", "--pack", str(pack), "--kaggle", str(kaggle)]
    assert cli.main([*args, "--removals", str(removals)]) == 0
    assert "written:" in capsys.readouterr().out
    (pack / "stray.txt").write_text("x")
    assert cli.main([*args, "--removals", str(removals)]) == 1


ROOT = Path(__file__).parent.parent


def test_the_readme_cites_the_data_set_word_for_word():
    from newsattention import __version__

    readme = (ROOT / "README.md").read_text()
    section = readme[readme.index("## How to cite") :]
    quoted = " ".join(
        line.removeprefix("> ").strip() for line in section.splitlines() if line.startswith(">")
    )
    assert quoted == citation.apa(__version__)


def test_citation_cff_and_zenodo_follow_the_citation_and_the_version():
    import re

    from newsattention import __version__

    cff = (ROOT / "CITATION.cff").read_text()
    preferred = cff[cff.index("preferred-citation:") :]
    assert f'title: "{citation.TITLE}"' in preferred
    assert f'version: "{__version__}"' in preferred and "type: data" in preferred
    assert f'url: "{citation.URL}"' in preferred
    assert cff.count(f'orcid: "{citation.ORCID}"') == 2
    assert re.search(rf'^version: "{re.escape(__version__)}"$', cff, re.M)
    assert "DRAFT" not in cff
    zenodo = json.loads((ROOT / ".zenodo.json").read_text())
    assert zenodo["version"] == __version__
    assert zenodo["creators"][0]["orcid"] == citation.ORCID.rsplit("/", 1)[1]
