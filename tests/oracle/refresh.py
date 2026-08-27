"""Regenerate oracle fixtures from Zenodo. Run by hand, never in CI.

    ZENODO_TOKEN=... uv run python -m tests.oracle.refresh
        --query 'creators.orcid:0000-...'

Writes ``<id>.json`` (the RDM record) and ``<id>.bib`` (the server's own BibTeX)
into ``tests/oracle/fixtures/``.

The per-record BibTeX requests here are exactly the N+1 pattern this project
exists to avoid. That is appropriate for a fixture generator run occasionally by
a human with a token, and inappropriate for the shipping tool.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import time
from collections.abc import Callable

import httpx

from zenodo_bibtex.fetch import rate_limit_delay

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
API = "https://zenodo.org/api/records"
RDM_MEDIA_TYPE = "application/vnd.inveniordm.v1+json"
SEARCH_DELAY_SECONDS = 2.5  # search API allows 30 requests/minute
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


def _get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    **kwargs,
) -> httpx.Response:
    """GET with backoff on transient server errors and rate limiting.

    Zenodo throws occasional 504s under load; a single one is not fatal. 429 is
    retried too, and is the most likely status a bulk refresh will meet: this
    script makes one request per record against a 30 req/min budget, so it is
    far closer to the limit than the shipping tool ever gets.

    Rate limiting waits until the server's own reset instant rather than using
    the exponential backoff applied to 5xx, because the window is what has to
    elapse. ``rate_limit_delay`` is shared with ``zenodo_bibtex.fetch`` so the
    "X-RateLimit-Reset is an absolute epoch, not a delay" correction cannot
    drift between the two callers. Nothing the oracle validates is shared --
    only the transport arithmetic.
    """
    for attempt in range(MAX_ATTEMPTS):
        response = client.get(url, **kwargs)
        if response.status_code not in RETRY_STATUSES:
            response.raise_for_status()
            return response
        if attempt == MAX_ATTEMPTS - 1:
            response.raise_for_status()
        if response.status_code == 429:
            sleep(rate_limit_delay(response, now=now))
        else:
            sleep(2**attempt)
    raise RuntimeError("unreachable")  # pragma: no cover


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--size", type=int, default=100)
    args = parser.parse_args()

    token = os.environ["ZENODO_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    FIXTURES.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers=headers, timeout=30.0) as client:
        listing = _get_with_retry(
            client,
            API,
            params={"q": args.query, "size": args.size},
            headers={"Accept": RDM_MEDIA_TYPE},
        )
        records = listing.json()["hits"]["hits"]

        for record in records:
            record_id = record["id"]
            (FIXTURES / f"{record_id}.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False) + "\n"
            )
            reference = _get_with_retry(
                client,
                f"{API}/{record_id}",
                headers={"Accept": "application/x-bibtex"},
            )
            (FIXTURES / f"{record_id}.bib").write_text(reference.text)
            print(f"wrote {record_id}")
            time.sleep(SEARCH_DELAY_SECONDS)


if __name__ == "__main__":
    main()
