"""Client-side BibTeX serialization for Zenodo records."""

from .format import Wrapping
from .serialize import serialize_record, serialize_records

__all__ = ["Wrapping", "serialize_record", "serialize_records"]
