"""Byte-exact BibTeX emission.

Ports ``_format_output_row`` and ``_clean_input`` from invenio-rdm-records
``invenio_rdm_records/resources/serializers/bibtex/schema.py:287-338`` at commit
36ab307. Every constant here exists to match that output byte for byte; see
``docs/superpowers/specs/2026-08-26-zenodo-bibtex-serializer-design.md``.
"""

from __future__ import annotations

import enum
import textwrap
from collections.abc import Mapping

from slugify import slugify

ESCAPED_CHARS = frozenset("&%$_#")
FIELD_WIDTH = 12
WRAP_WIDTH = 50
CONTINUATION_INDENT = 19
CLOSING_INDENT = 18
AUTHOR_INDENT = 18
CITATION_KEY_NAME_LIMIT = 40


class Wrapping(enum.StrEnum):
    """How to lay out values longer than ``WRAP_WIDTH``."""

    COMPAT = "compat"
    FIXED = "fixed"


def escape(text: str) -> str:
    """Backslash-escape the characters upstream treats as unsupported.

    Upstream applies this to the whole assembled field block, so it also
    escapes characters inside DOIs and URLs. That is reproduced deliberately.
    """
    return "".join("\\" + c if c in ESCAPED_CHARS else c for c in text)


def format_row(field: str, value: object, wrapping: Wrapping = Wrapping.COMPAT) -> str:
    """Format one field row, including its trailing comma and newline.

    Branch order matches upstream exactly: author, then long values, then
    ``month``, then ``url``, then the all-digit check.
    """
    if isinstance(value, str):
        value = value.strip()
    if field == "author":
        return _format_author(value)
    if isinstance(value, str) and len(value) > WRAP_WIDTH:
        return _format_wrapped(field, value, wrapping)
    if field == "month":
        return _bare(field, value)
    if field == "url":
        return _braced(field, value)
    if not isinstance(value, list) and value.isdigit():
        return _bare(field, value)
    return _braced(field, value)


def _bare(field: str, value: object) -> str:
    return f"  {field:<{FIELD_WIDTH}} = {value},\n"


def _braced(field: str, value: object) -> str:
    return f"  {field:<{FIELD_WIDTH}} = {{{value}}},\n"


def _format_author(names: list[str]) -> str:
    lines = [names[0], *(" " * AUTHOR_INDENT + name for name in names[1:])]
    return _braced("author", " and\n".join(lines))


def _format_wrapped(field: str, value: str, wrapping: Wrapping) -> str:
    """Lay out a value too long for one line.

    ``COMPAT`` reproduces upstream exactly, including the 19-space continuation
    indent and the closing brace stranded on its own line. ``FIXED`` aligns
    continuations under the opening brace and closes inline; it is the single
    sanctioned deviation from server output.
    """
    lines = textwrap.wrap(value, WRAP_WIDTH)
    if wrapping is Wrapping.FIXED:
        return _braced(field, ("\n" + " " * CLOSING_INDENT).join(lines))
    out = f"  {field:<{FIELD_WIDTH}} = {{{lines[0]}\n"
    for line in lines[1:]:
        out += " " * CONTINUATION_INDENT + line + "\n"
    return out + " " * CLOSING_INDENT + "},\n"


def citation_key(record: Mapping, *, year: str | None, record_id: str) -> str:
    """Build the citation key for a record.

    ``record_id`` is supplied by the caller because ``--all-versions`` builds the
    key from the parent id rather than the version id.
    """
    creators = record["metadata"].get("creators", [])
    if not creators:
        return record_id
    person = creators[0].get("person_or_org", {})
    name = person.get("family_name", person["name"])
    suffix = record_id if year is None else f"{year}_{record_id}"
    slug = slugify(name, separator="_", max_length=CITATION_KEY_NAME_LIMIT)
    return f"{slug}_{suffix}"
