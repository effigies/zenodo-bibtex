import pytest

from zenodo_bibtex import Wrapping, serialize_record, serialize_records

RECORD = {
    "id": "22101090",
    "parent": {
        "id": "7106147",
        "pids": {"doi": {"identifier": "10.5281/zenodo.7106147"}},
    },
    "pids": {"doi": {"identifier": "10.5281/zenodo.22101090"}},
    "metadata": {
        "resource_type": {"id": "software"},
        "title": "NIWorkflows",
        "publisher": "Zenodo",
        "publication_date": "2026-08-01",
        "version": "1.15.0",
        "creators": [
            {"person_or_org": {"name": "Esteban, Oscar", "family_name": "Esteban"}}
        ],
    },
}

# 67 raw chars, 71 escaped (3 underscores and 1 ampersand). Kept as a
# module constant so the wrap-boundary arithmetic in the test below stays
# under the line limit without splitting the literal -- the formatter
# rejoins implicit concatenation, which would then trip E501.
WRAP_TITLE = "Deep_Learning_Models & Methods for Neuro_Imaging Analysis Pipelines"

EXPECTED = (
    "@software{esteban_2026_22101090,\n"
    "  author       = {Esteban, Oscar},\n"
    "  title        = {NIWorkflows},\n"
    "  month        = aug,\n"
    "  year         = 2026,\n"
    "  publisher    = {Zenodo},\n"
    "  version      = {1.15.0},\n"
    "  doi          = {10.5281/zenodo.22101090},\n"
    "  url          = {https://doi.org/10.5281/zenodo.22101090},\n"
    "}"
)


def test_serialize_record_matches_the_expected_entry():
    assert serialize_record(RECORD) == EXPECTED


def test_entry_has_no_trailing_newline():
    assert not serialize_record(RECORD).endswith("\n")


def test_fields_follow_entry_type_order_not_record_order():
    body = serialize_record(RECORD).splitlines()
    names = [line.split("=")[0].strip() for line in body[1:-1]]
    assert names == [
        "author",
        "title",
        "month",
        "year",
        "publisher",
        "version",
        "doi",
        "url",
    ]


def test_underscore_in_a_doi_is_escaped():
    record = {**RECORD, "pids": {"doi": {"identifier": "10.5281/zenodo_1"}}}
    assert r"{10.5281/zenodo\_1}" in serialize_record(record)


def test_all_versions_switches_both_doi_and_citation_key():
    out = serialize_record(RECORD, all_versions=True)
    assert out.startswith("@software{esteban_2026_7106147,")
    assert "{10.5281/zenodo.7106147}" in out


def test_wrapping_mode_is_forwarded():
    record = {
        **RECORD,
        "metadata": {**RECORD["metadata"], "title": "x " * 40},
    }
    assert "\n                   " in serialize_record(record)
    assert "\n                   " not in serialize_record(
        record, wrapping=Wrapping.FIXED
    )


def test_documents_join_entries_with_a_blank_line_and_end_with_a_newline():
    out = serialize_records([RECORD, RECORD])
    assert out == EXPECTED + "\n\n" + EXPECTED + "\n"


def test_empty_input_produces_an_empty_document():
    assert serialize_records([]) == ""


def test_escaping_is_applied_after_wrapping_not_before():
    # This test discriminates between two wrong implementations:
    # - Escaping per-value before format_row would shift wrap boundaries
    #   because backslashes lengthen the text before textwrap.wrap sees it.
    # - Escaping after wrapping on the assembled block applies escapes to
    #   the already-wrapped lines, preserving the correct layout.
    # The raw title is 67 chars, escaped is 71 (4 escapable chars: 3 _ and 1 &).
    # When wrapped at WRAP_WIDTH=50 on the raw value:
    #   First line: 'Deep_Learning_Models & Methods for Neuro_Imaging' (48 chars)
    #   Second line: 'Analysis Pipelines'
    # If escaping happened first (wrong), at 50 chars the first line would end
    # with 'for' instead of 'Neuro_Imaging' due to the extra backslashes.
    record = {
        **RECORD,
        "metadata": {
            **RECORD["metadata"],
            "title": WRAP_TITLE,
        },
    }
    output = serialize_record(record)
    # The first wrapped line should end with the escaped underscore
    assert (
        "  title        = {Deep\\_Learning\\_Models \\& Methods for Neuro\\_Imaging\n"
        in output
    )
    # Verify the output is escaped correctly overall
    assert "Deep\\_Learning" in output
    assert "\\& Methods" in output
    assert "Neuro\\_Imaging" in output


def test_serialize_records_propagates_a_failure_when_no_callback_is_given():
    # Default behaviour is strict: a caller that does not opt into per-record
    # isolation should not silently get a short document. A record with no
    # `metadata` fails in resource_type's subscript chain.
    with pytest.raises(KeyError):
        serialize_records([RECORD, {"id": "2"}])


def test_serialize_records_reports_each_failure_and_keeps_the_rest():
    # The callback is what lets `convert` keep its per-record isolation while
    # still routing through the function that owns ENTRY_SEPARATOR.
    seen = []

    document = serialize_records(
        [RECORD, {"id": "2"}], on_error=lambda record, exc: seen.append((record, exc))
    )

    assert document == EXPECTED + "\n"
    assert len(seen) == 1
    failed_record, exc = seen[0]
    assert failed_record == {"id": "2"}
    assert isinstance(exc, Exception)


def test_serialize_records_reports_a_non_dict_record_to_the_callback():
    seen = []

    document = serialize_records(
        [RECORD, [1, 2, 3]], on_error=lambda record, exc: seen.append(record)
    )

    assert document == EXPECTED + "\n"
    assert seen == [[1, 2, 3]]
