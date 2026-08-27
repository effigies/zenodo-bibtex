import json
import pathlib
import re
import unicodedata

import pytest

from zenodo_bibtex import serialize_record
from zenodo_bibtex.entries import RESOURCE_TYPE_MAP

FIXTURES = pathlib.Path(__file__).parent / "oracle" / "fixtures"
RECORDS = sorted(FIXTURES.glob("*.json"))

REACHABLE_ENTRY_TYPES = {
    "article",
    "book",
    "booklet",
    "dataset",
    # "inbook" is missing deliberately: it is reachable in principle (a
    # publication-section record with imprint pages and publisher but no
    # booktitle would select it over incollection), but a 100-record sample of
    # publication-section records found zero such records. This is corpus
    # availability, not a code property -- unlike phdthesis below.
    "incollection",
    "inproceedings",
    "manual",
    "misc",
    # "phdthesis" is missing because it is genuinely unreachable, not merely
    # unsampled. It requires `school`, which build_fields can never populate:
    # see the comment at the `school` key in fields.py and record 19379015
    # (a Masters thesis whose server BibTeX is `@misc`).
    "proceedings",
    "software",
}


def _entry_type(bibtex: str) -> str:
    return bibtex.split("{", 1)[0].removeprefix("@")


def test_the_corpus_is_not_empty():
    assert RECORDS, "run tests/oracle/refresh.py to generate fixtures"


@pytest.mark.parametrize("path", RECORDS, ids=lambda p: p.stem)
def test_output_is_byte_identical_to_the_server(path):
    record = json.loads(path.read_text())
    expected = path.with_suffix(".bib").read_text()
    assert serialize_record(record) == expected


def test_corpus_covers_every_reachable_entry_type():
    seen = {_entry_type(p.with_suffix(".bib").read_text()) for p in RECORDS}
    assert seen >= REACHABLE_ENTRY_TYPES, REACHABLE_ENTRY_TYPES - seen


def test_no_fixture_produces_an_unpublished_entry():
    # `unpublished` requires `note`, which upstream can never populate.
    seen = {_entry_type(p.with_suffix(".bib").read_text()) for p in RECORDS}
    assert "unpublished" not in seen


def test_no_fixture_produces_a_phdthesis_entry():
    # `phdthesis` requires `school`, which build_fields can never populate
    # (see the comment at the `school` key in fields.py). Record 19379015 is
    # a thesis carrying custom_fields["thesis:thesis"] and proves the point:
    # its server BibTeX is `@misc`.
    seen = {_entry_type(p.with_suffix(".bib").read_text()) for p in RECORDS}
    assert "phdthesis" not in seen


def _is_non_latin_letter(char: str) -> bool:
    """True for a letter outside Latin and its combining diacritics.

    Gated on the Unicode category so punctuation cannot masquerade as a script:
    record 21824843 contains an EM DASH (U+2014), which is above the codepoint
    threshold but is not evidence of non-Latin script coverage.
    """
    return ord(char) > 0x36F and unicodedata.category(char).startswith("L")


def _has_row(bibtex: str, field: str) -> bool:
    return any(line.startswith(f"  {field:<12} =") for line in bibtex.splitlines())


def _row(bibtex: str, field: str) -> str:
    prefix = f"  {field:<12} ="
    rows = [line for line in bibtex.splitlines() if line.startswith(prefix)]
    return rows[0] if rows else ""


def test_corpus_exercises_the_tricky_formatting_paths():
    """Guard every row of the spec's corpus-requirements table.

    This assertion used to cover three properties out of nine, so four
    requirements were unmet and five unguarded -- a fixture refresh could drop
    coverage silently. Results are collected into a dict and asserted together
    so one gap does not mask the others, and the failure message names exactly
    which spec rows regressed.
    """
    pairs = [
        (json.loads(p.read_text()), p.with_suffix(".bib").read_text()) for p in RECORDS
    ]
    bibs = [b for _, b in pairs]

    def date(record) -> str:
        return str(record.get("metadata", {}).get("publication_date", ""))

    covered = {
        "title over 50 characters": any("\n" + " " * 19 in b for b in bibs),
        "non-Latin script": any(any(map(_is_non_latin_letter, b)) for b in bibs),
        "escapable character in a title": any("\\_" in b or "\\&" in b for b in bibs),
        "DOI or URL containing _": any(
            "\\_" in _row(b, "doi") and "\\_" in _row(b, "url") for b in bibs
        ),
        "many authors": any(" and\n" in b for b in bibs),
        "single author": any(
            "  author       = {" in b and " and\n" not in b for b in bibs
        ),
        "creator lacking family_name": any(
            any(
                "family_name" not in creator["person_or_org"]
                for creator in record.get("metadata", {}).get("creators", [])
            )
            for record, _ in pairs
        ),
        "record with no DOI": any(
            not _has_row(b, "doi") and not _has_row(b, "url") for b in bibs
        ),
        "interval publication date": any("/" in date(record) for record, _ in pairs),
        "year-only publication date": any(
            re.fullmatch(r"\d{4}", date(record)) for record, _ in pairs
        ),
        "req_fields unmet, falling back to misc": any(
            record["metadata"]["resource_type"]["id"] in RESOURCE_TYPE_MAP
            and _entry_type(b) == "misc"
            for record, b in pairs
        ),
    }

    assert all(covered.values()), sorted(k for k, v in covered.items() if not v)


def test_no_fixture_emits_a_permanently_absent_field():
    for path in RECORDS:
        bibtex = path.with_suffix(".bib").read_text()
        for field in ("note", "editor", "series", "edition"):
            assert f"  {field:<12} =" not in bibtex, (path.stem, field)
