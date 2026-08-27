"""Assemble BibTeX entries and documents.

Ports ``dump_record`` and ``_dump_data`` from invenio-rdm-records
``invenio_rdm_records/resources/serializers/bibtex/schema.py:196-257`` at commit
36ab307.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from .entries import select_entry
from .fields import build_fields, record_id, resource_type
from .format import Wrapping, citation_key, escape, format_row

ENTRY_SEPARATOR = "\n\n"
"""Separator between entries.

Not a ported behaviour. The only endpoint that would reveal how upstream joins
entries is the one that returns 500, so this is our choice. Individual entries
end without a newline, matching the server; documents end with one.

``serialize_records`` is the single owner of this contract, and the CLI's
``convert`` goes through it, so changing this constant changes what a user
sees. It previously did not: ``convert`` joined entries itself.
"""


def serialize_record(
    record: Mapping,
    *,
    all_versions: bool = False,
    wrapping: Wrapping = Wrapping.COMPAT,
) -> str:
    """Serialize one RDM record to a BibTeX entry, without a trailing newline."""
    fields = build_fields(record, all_versions=all_versions)
    entry = select_entry(resource_type(record), fields)
    key = citation_key(
        record,
        year=fields["year"],
        record_id=record_id(record, all_versions=all_versions),
    )
    body = "".join(
        format_row(name, fields[name], wrapping)
        for name in entry.fields
        if fields.get(name) is not None
    )
    return f"@{entry.name}{{{key},\n{escape(body)}}}"


def serialize_records(
    records: Iterable[Mapping],
    *,
    all_versions: bool = False,
    wrapping: Wrapping = Wrapping.COMPAT,
    on_error: Callable[[object, Exception], None] | None = None,
) -> str:
    """Serialize many records into one BibTeX document.

    ``on_error`` opts into per-record isolation: it is called with
    ``(record, exception)`` for every record that fails, and the remaining
    records still reach the document. Without it the first failure propagates,
    so a caller cannot be handed a silently short bibliography.

    The record is passed back uninspected -- it may not even be a mapping --
    because the caller is better placed to decide how to identify it.
    """
    entries = []
    for record in records:
        try:
            entries.append(
                serialize_record(record, all_versions=all_versions, wrapping=wrapping)
            )
        except Exception as exc:
            # Deliberately broad, and only reachable when the caller supplied
            # on_error. A malformed record can provoke almost any exception
            # shape -- KeyError, TypeError, AttributeError from a null
            # "metadata" -- and none of them should cost the caller the rest of
            # the bibliography. The exception object itself is handed to
            # on_error rather than swallowed, so breadth here cannot hide a
            # real serializer bug.
            if on_error is None:
                raise
            on_error(record, exc)
    if not entries:
        return ""
    return ENTRY_SEPARATOR.join(entries) + "\n"
