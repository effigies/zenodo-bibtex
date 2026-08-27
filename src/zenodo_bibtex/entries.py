"""BibTeX entry types and the resource-type mapping.

Ports the entry table from invenio-rdm-records
``invenio_rdm_records/resources/serializers/bibtex/schema_formats.py`` and the
selection rule from ``.../bibtex/schema.py:212``, at commit 36ab307.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class EntryType:
    """A BibTeX entry type and the fields it accepts."""

    name: str
    req_fields: tuple[str, ...]
    opt_fields: tuple[str, ...]

    @property
    def fields(self) -> tuple[str, ...]:
        """Fields in emission order: required first, then optional."""
        return self.req_fields + self.opt_fields


BOOK = EntryType(
    "book",
    ("author", "title", "publisher", "year"),
    ("volume", "address", "month", "note", "doi", "url"),
)
BOOKLET = EntryType(
    "booklet",
    ("title",),
    ("author", "address", "month", "year", "note", "doi", "url"),
)
MISC = EntryType(
    "misc",
    (),
    ("author", "title", "month", "year", "note", "publisher", "version", "doi", "url"),
)
IN_PROCEEDINGS = EntryType(
    "inproceedings",
    ("author", "title", "booktitle", "year"),
    ("pages", "publisher", "address", "month", "note", "venue", "doi", "url"),
)
PROCEEDINGS = EntryType(
    "proceedings",
    ("title", "year"),
    ("publisher", "address", "month", "note", "doi", "url"),
)
IN_COLLECTION = EntryType(
    "incollection",
    ("author", "title", "booktitle", "year", "publisher"),
    ("pages", "address", "month", "editor", "volume", "number", "series", "doi", "url"),
)
IN_BOOK = EntryType(
    "inbook",
    ("author", "title", "pages", "year", "publisher"),
    (
        "address",
        "month",
        "editor",
        "edition",
        "volume",
        "number",
        "series",
        "note",
        "doi",
        "url",
    ),
)
ARTICLE = EntryType(
    "article",
    ("author", "title", "journal", "year"),
    ("volume", "number", "pages", "month", "note", "doi", "url"),
)
UNPUBLISHED = EntryType(
    "unpublished",
    ("author", "title", "note"),
    ("month", "year", "doi", "url"),
)
THESIS = EntryType(
    "phdthesis",
    ("author", "title", "school", "year"),
    ("address", "month", "note", "doi", "url"),
)
MANUAL = EntryType(
    "manual",
    ("title",),
    ("author", "address", "month", "year", "note", "doi", "url"),
)
DATASET = EntryType(
    "dataset",
    (),
    ("author", "title", "month", "year", "note", "publisher", "version", "doi", "url"),
)
SOFTWARE = EntryType(
    "software",
    (),
    (
        "author",
        "title",
        "month",
        "year",
        "note",
        "publisher",
        "version",
        "doi",
        "url",
        "swhid",
    ),
)

RESOURCE_TYPE_MAP: dict[str, tuple[EntryType, ...]] = {
    "publication-conferencepaper": (IN_PROCEEDINGS,),
    "publication-conferenceproceeding": (PROCEEDINGS,),
    "publication-book": (BOOK, BOOKLET),
    "publication-section": (IN_COLLECTION, IN_BOOK),
    "publication-article": (ARTICLE,),
    "publication-preprint": (UNPUBLISHED,),
    "publication-thesis": (THESIS,),
    "publication-dissertation": (THESIS,),
    "publication-technicalnote": (MANUAL,),
    "publication-workingpaper": (UNPUBLISHED,),
    "software": (SOFTWARE,),
    "dataset": (DATASET,),
}
"""Resource type to ordered candidate entry types. Anything absent becomes MISC."""


def select_entry(resource_type: str, fields: Mapping[str, object]) -> EntryType:
    """Return the first candidate whose required fields are all truthy, else MISC.

    Truthiness rather than presence is deliberate: upstream tests
    ``all(fields_map.get(f) for f in req_fields)``, so an empty string or empty
    list fails to satisfy a requirement.
    """
    for candidate in RESOURCE_TYPE_MAP.get(resource_type, ()):
        if all(fields.get(name) for name in candidate.req_fields):
            return candidate
    return MISC
