"""Command line interface.

``fetch`` performs all network I/O; ``convert`` is pure, so a bibliography can
be regenerated from saved JSON without a token.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Annotated

import httpx
import typer

from .fetch import DEFAULT_BASE_URL, fetch_records
from .format import Wrapping
from .serialize import serialize_records

app = typer.Typer(add_completion=False, help=__doc__)


def load_records(payload: object) -> list[dict]:
    """Accept a bare list, a fetch envelope, or a raw Zenodo response."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "records" in payload:
            return payload["records"]
        if "hits" in payload:
            return payload["hits"]["hits"]
    raise ValueError("unrecognised input shape: expected records, hits, or a list")


@app.command()
def fetch(
    query: str = typer.Option(None, "--query", help="Raw Zenodo query string."),
    orcid: str = typer.Option(None, "--orcid", help="Shorthand for creators.orcid."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url"),
) -> None:
    """Fetch matching records as RDM JSON and write them to stdout."""
    if (query is None) == (orcid is None):
        typer.echo("error: pass exactly one of --query or --orcid", err=True)
        raise typer.Exit(2)
    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        typer.echo("error: ZENODO_TOKEN is unset", err=True)
        raise typer.Exit(2)

    resolved = query if query is not None else f"creators.orcid:{orcid}"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(headers=headers, timeout=30.0) as client:
        records = fetch_records(resolved, client=client, base_url=base_url)
    typer.echo(json.dumps({"records": records}, ensure_ascii=False))


@app.command()
def convert(
    all_versions: bool = typer.Option(
        False, "--all-versions", help="Cite the concept DOI instead of the version DOI."
    ),
    # The default lives outside the typer.Option(...) call (in the parameter's
    # `= Wrapping.COMPAT`, not as an argument to Option()), so ruff's B008
    # (no function calls in argument defaults) never applies here. Putting an
    # enum member directly inside typer.Option(Wrapping.COMPAT, ...) does trip
    # B008 -- confirmed empirically: ruff only exempts Option()/Argument() calls
    # when the parameter's declared type is a builtin it trusts (str, bool,
    # ...), not a custom Enum -- and moving that value to a module-level
    # singleton does not clear the warning either. The Annotated form is the
    # only fix that satisfies ruff without changing behaviour, and it also
    # restores typer's native enum handling (choices in --help, its own
    # rejection of invalid values).
    wrapping: Annotated[
        Wrapping,
        typer.Option("--wrapping", help="compat matches the server byte for byte."),
    ] = Wrapping.COMPAT,
) -> None:
    """Convert RDM JSON on stdin into BibTeX on stdout."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        typer.echo(f"error: input is not valid JSON: {exc}", err=True)
        raise typer.Exit(2) from exc
    try:
        records = load_records(payload)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    failures = 0

    def report(record: object, exc: Exception) -> None:
        # Passing a callback rather than joining entries here keeps the
        # per-record isolation while leaving serialize_records the single owner
        # of the document format. The exception is reported verbatim (via !r)
        # so a real serializer bug cannot hide behind the isolation.
        nonlocal failures
        failures += 1
        record_id = (
            record.get("id", "<unknown>") if isinstance(record, dict) else "<unknown>"
        )
        typer.echo(f"error: record {record_id}: {exc!r}", err=True)

    document = serialize_records(
        records, all_versions=all_versions, wrapping=wrapping, on_error=report
    )
    # Written rather than echoed: serialize_records already terminates a
    # non-empty document with a newline, and typer.echo would add a second.
    sys.stdout.write(document)
    if failures:
        typer.echo(f"error: {failures} record(s) failed", err=True)
        raise typer.Exit(1)
