import pytest

from zenodo_bibtex.entries import select_entry
from zenodo_bibtex.fields import (
    build_fields,
    publication_year_month,
    record_id,
    resource_type,
)


def _dated(value: str | None) -> dict:
    metadata = {} if value is None else {"publication_date": value}
    return {"metadata": metadata}


def test_full_iso_date_yields_year_and_month():
    assert publication_year_month(_dated("2022-09-22")) == ("2022", "sep")


def test_year_only_date_yields_no_month():
    assert publication_year_month(_dated("2022")) == ("2022", None)


def test_interval_uses_its_lower_bound():
    assert publication_year_month(_dated("2019-01/2020-06")) == ("2019", "jan")


def test_unparseable_date_yields_neither_field():
    # Upstream raises AttributeError further down this path; we omit instead.
    # See the spec's "Defensive divergences".
    assert publication_year_month(_dated("definitely not a date")) == (None, None)


def test_missing_date_yields_neither_field():
    assert publication_year_month(_dated(None)) == (None, None)


def test_year_is_a_digit_string_so_it_renders_unbraced():
    year, _ = publication_year_month(_dated("2022-09-22"))
    assert year.isdigit()


def test_december_maps_to_dec():
    assert publication_year_month(_dated("2021-12-01")) == ("2021", "dec")


def test_edtf_season_notation_yields_neither_field():
    # EDTF Level 2 season forms (2020-21 through 2020-25) raise AttributeError
    # inside babel_edtf.parse_edtf, not ParseException, so the except clause in
    # publication_year_month has to catch both or these dates crash the record.
    assert publication_year_month(_dated("2020-21")) == (None, None)


def test_uncertain_date_yields_neither_field():
    # Uncertain/approximate dates like 2020? parse but are neither Date nor
    # Interval. This covers the `elif not isinstance(parsed, Date)` branch in
    # publication_year_month, which is the only thing standing between an
    # UncertainOrApproximate object and an AttributeError on .year.
    assert publication_year_month(_dated("2020?")) == (None, None)


ABSENT_FIELDS = ("note", "editor", "series", "edition")

RECORD = {
    "id": "22101090",
    "parent": {
        "id": "7106147",
        "pids": {"doi": {"identifier": "10.5281/zenodo.7106147"}},
    },
    "pids": {"doi": {"identifier": "10.5281/zenodo.22101090"}},
    "metadata": {
        "resource_type": {"id": "software"},
        "title": "NIWorkflows: NeuroImaging Workflows",
        "publisher": "Zenodo",
        "publication_date": "2026-08-01",
        "version": "1.15.0",
        "creators": [
            {"person_or_org": {"name": "Esteban, Oscar", "family_name": "Esteban"}},
            {"person_or_org": {"name": "Markiewicz, Christopher J."}},
        ],
    },
}


def test_resource_type_is_read_from_metadata():
    assert resource_type(RECORD) == "software"


def test_record_id_defaults_to_the_version_id():
    assert record_id(RECORD) == "22101090"


def test_record_id_uses_the_parent_when_all_versions():
    assert record_id(RECORD, all_versions=True) == "7106147"


def test_authors_are_person_or_org_names_in_order():
    assert build_fields(RECORD)["author"] == [
        "Esteban, Oscar",
        "Markiewicz, Christopher J.",
    ]


def test_url_is_derived_from_the_doi():
    assert build_fields(RECORD)["url"] == "https://doi.org/10.5281/zenodo.22101090"


def test_all_versions_uses_the_parent_doi():
    fields = build_fields(RECORD, all_versions=True)
    assert fields["doi"] == "10.5281/zenodo.7106147"
    assert fields["url"] == "https://doi.org/10.5281/zenodo.7106147"


def test_doi_falls_back_to_metadata_identifiers():
    record = {
        "id": "1",
        "metadata": {
            "resource_type": {"id": "dataset"},
            "identifiers": [
                {"scheme": "other", "identifier": "x"},
                {"scheme": "doi", "identifier": "10.1234/abc"},
            ],
        },
    }
    assert build_fields(record)["doi"] == "10.1234/abc"


def test_record_without_any_doi_has_no_doi_or_url():
    record = {"id": "1", "metadata": {"resource_type": {"id": "dataset"}}}
    fields = build_fields(record)
    assert fields["doi"] is None
    assert fields["url"] is None


@pytest.mark.parametrize("field", ABSENT_FIELDS)
def test_permanently_absent_fields_are_not_in_the_map(field):
    assert field not in build_fields(RECORD)


def test_custom_fields_populate_journal_and_imprint_values():
    record = {
        "id": "1",
        "metadata": {"resource_type": {"id": "publication-article"}},
        "custom_fields": {
            "journal:journal": {"title": "J", "volume": "3", "issue": "4"},
            "imprint:imprint": {"title": "B", "pages": "1-10"},
            "meeting:meeting": {"place": "Geneva"},
            "thesis:university": "UniGe",
        },
    }
    fields = build_fields(record)
    assert fields["journal"] == "J"
    assert fields["volume"] == "3"
    assert fields["number"] == "4"
    assert fields["booktitle"] == "B"
    assert fields["pages"] == "1-10"
    assert fields["venue"] == "Geneva"
    assert fields["school"] == "UniGe"


def test_school_stays_none_when_only_thesis_thesis_is_populated():
    # Zenodo stores the university under custom_fields["thesis:thesis"]["university"],
    # not custom_fields["thesis:university"] (which is what upstream's get_school
    # reads; see the comment at the `school` key in build_fields). Record 19379015 in
    # the oracle corpus is a Masters thesis carrying exactly this shape, and its
    # server BibTeX is `@misc` with no `school` row.
    #
    # Unlike note/editor/series/edition, `school` IS a key in the returned
    # field map -- it is merely always None for real thesis records, because the key
    # upstream reads is never the one Zenodo populates. Do not fold this into
    # ABSENT_FIELDS above; that parametrization is for keys absent from the map
    # entirely, and `school` is not one of those.
    record = {
        "id": "1",
        "metadata": {"resource_type": {"id": "publication-thesis"}},
        "custom_fields": {
            "thesis:thesis": {"university": "Instituto Superior Técnico"},
        },
    }
    fields = build_fields(record)
    assert fields["school"] is None
    assert select_entry("publication-thesis", fields).name == "misc"


def test_swhid_is_read_from_the_top_level_swh_object():
    # Discovered via the oracle (record 14640297 and others): Zenodo's own BibTeX
    # output does emit `swhid` for software records with a Software Heritage
    # archival identifier, read from the top-level `swh.swhid` key. See the
    # docstring on `build_fields` for why this isn't a straight port of the pinned
    # invenio-rdm-records commit.
    record = {
        "id": "1",
        "metadata": {"resource_type": {"id": "software"}},
        "swh": {"swhid": "swh:1:dir:deadbeef;origin=https://doi.org/10.5281/zenodo.1"},
    }
    assert (
        build_fields(record)["swhid"]
        == "swh:1:dir:deadbeef;origin=https://doi.org/10.5281/zenodo.1"
    )


def test_swhid_is_none_when_the_record_has_no_swh_object():
    record = {"id": "1", "metadata": {"resource_type": {"id": "software"}}}
    assert build_fields(record)["swhid"] is None


def test_swhid_is_none_when_swh_is_explicitly_null():
    # Zenodo records without Software Heritage archival carry a top-level
    # `"swh": null` rather than omitting the key -- seen in 33 of 34 sampled
    # records in the oracle corpus.
    record = {
        "id": "1",
        "metadata": {"resource_type": {"id": "software"}},
        "swh": None,
    }
    assert build_fields(record)["swhid"] is None


def test_locations_become_a_semicolon_delimited_address_list():
    record = {
        "id": "1",
        "metadata": {
            "resource_type": {"id": "dataset"},
            "locations": {
                "features": [
                    {
                        "place": "CERN",
                        "description": "on site",
                        "geometry": {"type": "Point", "coordinates": [6.05, 46.23]},
                    }
                ]
            },
        },
    }
    assert build_fields(record)["address"] == [
        "name=CERN; description=on site; lat=6.05; lon=46.23"
    ]


def test_absent_optional_values_are_none():
    record = {"id": "1", "metadata": {"resource_type": {"id": "dataset"}}}
    fields = build_fields(record)
    assert fields["title"] is None
    assert fields["publisher"] is None
    assert fields["version"] is None
    assert fields["author"] is None
    assert fields["address"] is None
