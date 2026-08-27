from zenodo_bibtex.entries import BOOK, select_entry


def test_software_resource_type_selects_software_entry():
    assert select_entry("software", {}).name == "software"


def test_unmapped_resource_type_falls_back_to_misc():
    assert select_entry("presentation", {}).name == "misc"


def test_book_selected_when_all_required_fields_present():
    fields = {"author": ["A"], "title": "T", "publisher": "P", "year": "2026"}
    assert select_entry("publication-book", fields).name == "book"


def test_book_degrades_to_booklet_when_publisher_missing():
    fields = {"author": ["A"], "title": "T", "year": "2026"}
    assert select_entry("publication-book", fields).name == "booklet"


def test_preprint_is_misc_because_note_can_never_be_populated():
    # `unpublished` requires `note`, which upstream can never produce.
    # See the spec's "Two entry types are unreachable, for different reasons".
    fields = {"author": ["A"], "title": "T"}
    assert select_entry("publication-preprint", fields).name == "misc"


def test_empty_value_does_not_satisfy_a_required_field():
    assert select_entry("publication-technicalnote", {"title": ""}).name == "misc"


def test_fields_property_orders_required_before_optional():
    assert BOOK.fields[:4] == ("author", "title", "publisher", "year")
    assert "volume" in BOOK.fields[4:]
