"""Extract BibTeX field values from an Invenio RDM record.

Ports the ``get_*`` methods of invenio-rdm-records at commit 36ab307:
- ``invenio_rdm_records/resources/serializers/bibtex/schema.py:92-116``
  (get_date_published)
- ``invenio_rdm_records/resources/serializers/bibtex/schema.py:259-285``
  (_fetch_fields_map)
- ``invenio_rdm_records/resources/serializers/bibtex/schema.py:85-90`` (get_id)
- ``invenio_rdm_records/resources/serializers/schemas.py:14-27`` (get_doi)
- ``invenio_rdm_records/resources/serializers/schemas.py:29-55``
  (get_locations)
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping

from babel_edtf import parse_edtf
from edtf.parser.grammar import ParseException
from edtf.parser.parser_classes import Date, Interval


def publication_year_month(record: Mapping) -> tuple[str | None, str | None]:
    """Return ``(year, month)`` parsed from ``metadata.publication_date``.

    Ports upstream at ``invenio_rdm_records/resources/serializers/bibtex/
    schema.py:92-116`` (get_date_published).

    Uses ``babel_edtf.parse_edtf`` specifically, matching upstream's import.
    ``edtf`` ships a different ``parse_edtf`` in ``edtf.parser.grammar``, and
    the two are not interchangeable.

    Unparseable and non-date values yield ``(None, None)``. Upstream instead
    returns ``None`` and then raises ``AttributeError`` when the caller
    subscripts it; omitting the fields is a deliberate divergence. This includes
    EDTF Level 2 season notation (e.g., "2020-21") which raises ``AttributeError``
    inside ``parse_edtf`` rather than ``ParseException``.
    """
    raw = record.get("metadata", {}).get("publication_date")
    if not raw:
        return None, None
    try:
        parsed = parse_edtf(raw)
    except (ParseException, AttributeError):
        # ParseException: malformed EDTF syntax
        # AttributeError: raised by babel_edtf for EDTF Level 2 season notation
        # (e.g., "2020-21") which attempts to access _month on Season objects.
        return None, None
    if isinstance(parsed, Interval):
        parsed = parsed.lower
    elif not isinstance(parsed, Date):
        return None, None
    month = None
    if parsed.month:
        month = calendar.month_abbr[int(parsed.month)].lower()
    return str(parsed.year), month


def resource_type(record: Mapping) -> str:
    """Return the record's resource type id."""
    return record["metadata"]["resource_type"]["id"]


def record_id(record: Mapping, *, all_versions: bool = False) -> str:
    """Return the id used for the DOI and the citation key."""
    if all_versions:
        return str(record["parent"]["id"])
    return str(record["id"])


def _doi(record: Mapping, *, all_versions: bool) -> str | None:
    if all_versions:
        parent_doi = record.get("parent", {}).get("pids", {}).get("doi")
        if parent_doi:
            return parent_doi["identifier"]
    pids = record.get("pids", {})
    if "doi" in pids:
        return pids["doi"]["identifier"]
    for identifier in record.get("metadata", {}).get("identifiers", []):
        if identifier["scheme"] == "doi":
            return identifier["identifier"]
    return None


def _locations(metadata: Mapping) -> list[str]:
    features = metadata.get("locations", {}).get("features", [])
    locations = []
    for feature in features:
        parts = ""
        place = feature.get("place")
        description = feature.get("description")
        if place:
            parts += f"name={place}; "
        if description:
            parts += f"description={description}"
        geometry = feature.get("geometry")
        if geometry and geometry["type"] == "Point":
            coords = geometry["coordinates"]
            parts += f"; lat={coords[0]}; lon={coords[1]}"
        locations.append(parts)
    return locations


def build_fields(record: Mapping, *, all_versions: bool = False) -> dict[str, object]:
    """Map an RDM record onto BibTeX field values.

    Ports upstream at ``invenio_rdm_records/resources/serializers/bibtex/
    schema.py:259-285`` (_fetch_fields_map) using helper fields extracted via
    get_id (line 85-90), get_doi (schemas.py:14-27), and get_locations
    (schemas.py:29-55).

    Absent values are ``None`` so callers can skip them. ``note``, ``editor``,
    ``series`` and ``edition`` are deliberately absent from the result: upstream
    defines no source for any of them, so emitting one would break fidelity. See
    the spec's "Permanently absent fields".

    ``swhid`` is a partial exception to that pattern. The pinned commit's
    ``BibTexSchema`` declares no ``fields.Method`` for it either -- only the
    ``_fetch_fields_map`` dict lookup (``bibtex/schema.py:284``) and the
    ``software`` entry's ``opt_fields`` (``bibtex/schema_formats.py:164``)
    reference a ``swhid`` key, and ``CHANGES.rst:802`` records that Software
    Heritage support was added to the BibTeX export at some point -- so this
    pinned snapshot looks like it lost the wiring for an otherwise-real feature.
    The oracle proved the server still emits it: records 14640297, 17161627 and
    others carry a top-level ``swh.swhid`` whose value appears verbatim in the
    server's BibTeX. This reads that path directly rather than porting a named
    upstream method, because there is no such method left to cite.
    """
    metadata = record.get("metadata", {})
    custom = record.get("custom_fields", {})
    journal = custom.get("journal:journal", {})
    imprint = custom.get("imprint:imprint", {})
    year, month = publication_year_month(record)
    doi = _doi(record, all_versions=all_versions)
    authors = [c["person_or_org"]["name"] for c in metadata.get("creators", [])]
    return {
        "address": _locations(metadata) or None,
        "author": authors or None,
        "publisher": metadata.get("publisher") or None,
        "title": metadata.get("title") or None,
        "year": year,
        "month": month,
        "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else None,
        "version": metadata.get("version") or None,
        # DELIBERATE, NOT A BUG: this reproduces upstream's get_school exactly
        # (invenio_rdm_records/resources/serializers/bibtex/schema.py:181-186 at
        # commit 36ab307), which reads custom_fields["thesis:university"]. Zenodo
        # itself stores the university at custom_fields["thesis:thesis"]["university"]
        # instead -- 56 of 100 sampled theses use "thesis:thesis", zero use
        # "thesis:university" -- so `school` is always None here in practice, and
        # `phdthesis` (whose req_fields include `school`) can never be selected;
        # thesis records always fall through to `@misc`. Verified against the oracle:
        # record 19379015 is a Masters thesis carrying `custom_fields["thesis:thesis"]
        # ["university"]`, and its server BibTeX is `@misc` with no `school` row.
        # "Fixing" this key would populate `school`, promote theses to `@phdthesis`,
        # and BREAK byte-fidelity against a server that emits `@misc`. See
        # test_school_stays_none_when_only_thesis_thesis_is_populated in
        # tests/test_fields.py and the spec's "Two fields are present in the map,
        # and only one is always `None`" section (not "Permanently absent
        # fields", which covers note/editor/series/edition).
        "school": custom.get("thesis:university"),
        "journal": journal.get("title"),
        "volume": journal.get("volume"),
        "number": journal.get("issue"),
        "booktitle": imprint.get("title"),
        "pages": imprint.get("pages"),
        "venue": custom.get("meeting:meeting", {}).get("place"),
        "swhid": (record.get("swh") or {}).get("swhid"),
    }
