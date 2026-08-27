import textwrap

from zenodo_bibtex.format import WRAP_WIDTH, Wrapping, citation_key, escape, format_row


def test_escape_backslashes_the_unsupported_characters():
    assert escape("a&b%c$d_e#f") == r"a\&b\%c\$d\_e\#f"


def test_escape_leaves_ordinary_text_untouched():
    assert escape("plain text 123") == "plain text 123"


def test_field_name_is_padded_to_twelve_columns():
    assert format_row("title", "T") == "  title        = {T},\n"


def test_short_field_name_pads_further():
    assert format_row("url", "u") == "  url          = {u},\n"


def test_month_is_emitted_without_braces():
    assert format_row("month", "aug") == "  month        = aug,\n"


def test_all_digit_value_is_emitted_without_braces():
    assert format_row("year", "2026") == "  year         = 2026,\n"


def test_url_is_braced_even_though_it_may_look_bare():
    assert format_row("url", "https://doi.org/10.5281/zenodo.1") == (
        "  url          = {https://doi.org/10.5281/zenodo.1},\n"
    )


def test_string_values_are_stripped_before_formatting():
    assert format_row("title", "  T  ") == "  title        = {T},\n"


def test_single_author_has_no_continuation_line():
    assert format_row("author", ["Doe, Jane"]) == "  author       = {Doe, Jane},\n"


def test_multiple_authors_join_with_and_and_eighteen_spaces():
    assert format_row("author", ["Doe, Jane", "Roe, Ann"]) == (
        "  author       = {Doe, Jane and\n                  Roe, Ann},\n"
    )


def test_long_list_value_does_not_raise():
    # Upstream reaches ``textwrap.wrap`` with a list here and raises TypeError.
    # We fall through to the list-repr branch instead; see the spec's
    # "Defensive divergences".
    assert format_row("address", ["x"] * 51).startswith("  address      = {[")


# Verbatim from record 21465761, whose server output exhibits the stray indent.
LONG_TITLE = "SDCflows: Susceptibility Distortion Correction workFLOWS."


def test_compat_wrapping_reproduces_the_server_layout():
    assert format_row("title", LONG_TITLE) == (
        "  title        = {SDCflows: Susceptibility Distortion Correction\n"
        "                   workFLOWS.\n"
        "                  },\n"
    )


def test_fixed_wrapping_aligns_continuations_and_closes_inline():
    assert format_row("title", LONG_TITLE, Wrapping.FIXED) == (
        "  title        = {SDCflows: Susceptibility Distortion Correction\n"
        "                  workFLOWS.},\n"
    )


def test_value_of_exactly_wrap_width_is_not_wrapped():
    value = "x" * WRAP_WIDTH
    assert format_row("title", value) == f"  title        = {{{value}}},\n"


def test_value_one_char_over_wrap_width_is_wrapped():
    assert "\n" in format_row("title", "x" * (WRAP_WIDTH + 1)).rstrip("\n")


def test_wrapping_uses_textwrap_semantics():
    lines = textwrap.wrap(LONG_TITLE, WRAP_WIDTH)
    assert lines == ["SDCflows: Susceptibility Distortion Correction", "workFLOWS."]


def _record(person: dict) -> dict:
    return {"metadata": {"creators": [{"person_or_org": person}]}}


def test_key_combines_family_name_year_and_id():
    record = _record({"name": "Esteban, Oscar", "family_name": "Esteban"})
    assert citation_key(record, year="2026", record_id="22101090") == (
        "esteban_2026_22101090"
    )


def test_key_falls_back_to_full_name_when_family_name_key_absent():
    record = _record({"name": "Oscar Esteban"})
    assert citation_key(record, year="2026", record_id="21465761") == (
        "oscar_esteban_2026_21465761"
    )


def test_present_but_empty_family_name_is_used_not_replaced():
    # Upstream uses ``.get("family_name", name)``, so an empty string wins.
    record = _record({"name": "Ann Roe", "family_name": ""})
    assert citation_key(record, year="2026", record_id="7") == "_2026_7"


def test_key_omits_year_when_no_year_was_parsed():
    record = _record({"name": "Roe, Ann", "family_name": "Roe"})
    assert citation_key(record, year=None, record_id="7") == "roe_7"


def test_key_is_the_bare_id_when_there_are_no_creators():
    assert citation_key({"metadata": {}}, year="2026", record_id="7") == "7"


def test_organisation_name_is_slugified():
    record = _record({"name": "The Turing Way Community"})
    assert citation_key(record, year="2019", record_id="3233986") == (
        "the_turing_way_community_2019_3233986"
    )


def test_name_is_truncated_to_forty_characters():
    record = _record({"name": "A" * 60})
    key = citation_key(record, year="2020", record_id="1")
    assert key == "a" * 40 + "_2020_1"
