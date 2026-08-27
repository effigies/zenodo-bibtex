"""Fetch Zenodo records in the RDM-native JSON representation.

``GET /api/records`` returns HTTP 500 for ``application/x-bibtex``, but serves
``application/vnd.inveniordm.v1+json`` correctly — and that payload is the same
record shape Zenodo's own BibTeX serializer consumes. That media type is not in
Zenodo's published documentation, so every record is shape-checked before use.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

RDM_MEDIA_TYPE = "application/vnd.inveniordm.v1+json"
DEFAULT_BASE_URL = "https://zenodo.org/api/records"
MAX_PAGE_SIZE = 100
RETRY_STATUSES = frozenset({500, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.0
MAX_SLEEP_SECONDS = 120.0
"""Upper bound on any single wait.

The search window is a minute wide, so no legitimate wait needs to exceed
this. The clamp exists so a stale, skewed or hostile header cannot translate
into an unbounded sleep -- see ``rate_limit_delay``.
"""

LOW_REMAINING_THRESHOLD = 2
"""Requests left in the window below which we throttle pre-emptively."""

THROTTLE_SLEEP_SECONDS = 2.0
"""Pre-emptive pause once the budget is nearly gone.

The search API allows 30 requests/minute, so ~2s per request is the sustainable
rate. Pausing briefly is much cheaper than taking a 429 and waiting out the
remainder of the window.
"""

REQUIRED_PATHS = (("id",), ("metadata", "resource_type", "id"))


class FetchError(RuntimeError):
    """A request failed in a way retrying will not fix."""


class ShapeError(FetchError):
    """A record lacked a path the serializer depends on."""


def fetch_records(
    query: str,
    *,
    client: httpx.Client,
    base_url: str = DEFAULT_BASE_URL,
    page_size: int = MAX_PAGE_SIZE,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> list[dict]:
    """Return every record matching ``query``, paging as needed.

    ``sleep`` and ``now`` are injectable so rate-limit waits are testable
    without patching the clock globally: ``X-RateLimit-Reset`` is an absolute
    epoch, so the delay derived from it depends on the current time.
    """
    records: list[dict] = []
    page = 1
    while True:
        payload = _get_page(
            client, base_url, query, page, page_size, sleep=sleep, now=now
        )
        hits = payload["hits"]["hits"]
        for record in hits:
            _validate_shape(record)
        records.extend(hits)
        if not hits or len(records) >= payload["hits"]["total"]:
            return records
        page += 1


def _get_page(
    client: httpx.Client,
    base_url: str,
    query: str,
    page: int,
    page_size: int,
    *,
    sleep: Callable[[float], None],
    now: Callable[[], float],
) -> dict:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.get(
            base_url,
            params={"q": query, "size": page_size, "page": page},
            headers={"Accept": RDM_MEDIA_TYPE},
        )
        if response.status_code == 200:
            _throttle(response, sleep=sleep)
            return response.json()
        if response.status_code == 429:
            sleep(rate_limit_delay(response, now=now))
            continue
        if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
            continue
        raise FetchError(_describe(response))
    raise FetchError(f"giving up after {MAX_ATTEMPTS} attempts")


def rate_limit_delay(
    response: httpx.Response, *, now: Callable[[], float] = time.time
) -> float:
    """Return how long to wait before retrying a rate-limited request.

    The two headers use different units, and conflating them is a serious bug:

    - ``Retry-After`` is a delta in seconds, so its value is the delay.
    - ``X-RateLimit-Reset`` is an **absolute UTC epoch timestamp**, so the
      delay is ``reset - now``. Measured against Zenodo: a 429 carrying
      ``x-ratelimit-reset: 1787777909`` alongside ``date: Wed, 26 Aug 2026
      20:57:29 GMT`` (epoch 1787777850) means "wait 60s", not "wait
      1787777909s" -- the latter is roughly 56.7 years.

    ``Retry-After`` wins when both are present and parseable. Every result is
    clamped to ``[1.0, MAX_SLEEP_SECONDS]``: the floor absorbs clock skew and
    already-elapsed windows, and the ceiling means neither header can hang the
    process regardless of how stale or hostile its value is.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return _clamp(float(retry_after))
        except ValueError:
            pass
    raw = response.headers.get("X-RateLimit-Reset")
    try:
        return _clamp(float(raw) - now())
    except (TypeError, ValueError):
        return BACKOFF_BASE_SECONDS


def _clamp(delay: float) -> float:
    return min(max(1.0, delay), MAX_SLEEP_SECONDS)


def _throttle(response: httpx.Response, *, sleep: Callable[[float], None]) -> None:
    """Pause before spending the last of the rate-limit budget.

    Reads ``X-RateLimit-Remaining`` so a long pagination run slows down instead
    of running headlong into a 429. A missing or unparseable header means the
    server told us nothing, so we do not invent a delay.
    """
    try:
        remaining = int(response.headers["X-RateLimit-Remaining"])
    except (KeyError, ValueError):
        return
    if remaining <= LOW_REMAINING_THRESHOLD:
        sleep(THROTTLE_SLEEP_SECONDS)


def _describe(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    error_id = body.get("error_id")
    suffix = f" (error_id {error_id})" if error_id else ""
    return f"HTTP {response.status_code}: {body.get('message', '')}{suffix}"


def _validate_shape(record: dict) -> None:
    for path in REQUIRED_PATHS:
        cursor = record
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                raise ShapeError(
                    f"record {record.get('id', '<unknown>')} is missing "
                    f"{'.'.join(path)}; the RDM media type may have changed"
                )
            cursor = cursor[key]
