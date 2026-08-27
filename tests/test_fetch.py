import re

import httpx
import pytest

from zenodo_bibtex.fetch import (
    MAX_ATTEMPTS,
    MAX_SLEEP_SECONDS,
    THROTTLE_SLEEP_SECONDS,
    FetchError,
    ShapeError,
    fetch_records,
)

# A plausible wall-clock epoch, injected so rate-limit maths is deterministic.
# X-RateLimit-Reset is an *absolute* epoch, so every expectation below is
# expressed as an offset from this instant rather than as a bare number.
NOW = 1787777850.0


def _at_now() -> float:
    return NOW


def _record(record_id: str) -> dict:
    return {"id": record_id, "metadata": {"resource_type": {"id": "software"}}}


def _page(records, total):
    return {"hits": {"hits": records, "total": total}}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_single_page_is_returned():
    def handler(request):
        return httpx.Response(200, json=_page([_record("1")], 1))

    assert fetch_records("q", client=_client(handler)) == [_record("1")]


def test_pagination_follows_until_total_is_reached():
    pages = {
        "1": _page([_record("1")], 2),
        "2": _page([_record("2")], 2),
    }

    def handler(request):
        page = dict(request.url.params)["page"]
        return httpx.Response(200, json=pages[page])

    records = fetch_records("q", client=_client(handler), page_size=1)
    assert [r["id"] for r in records] == ["1", "2"]


def test_request_asks_for_the_rdm_media_type():
    seen = {}

    def handler(request):
        seen["accept"] = request.headers["accept"]
        return httpx.Response(200, json=_page([_record("1")], 1))

    fetch_records("q", client=_client(handler))
    assert seen["accept"] == "application/vnd.inveniordm.v1+json"


def test_retries_a_retryable_status_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(504, text="gateway timeout")
        return httpx.Response(200, json=_page([_record("1")], 1))

    records = fetch_records("q", client=_client(handler), sleep=lambda _: None)
    assert [r["id"] for r in records] == ["1"]
    assert calls["n"] == 2


def test_gives_up_after_max_attempts():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, json={"error_id": "abc", "status": 500})

    with pytest.raises(FetchError, match="abc"):
        fetch_records("q", client=_client(handler), sleep=lambda _: None)
    assert calls["n"] == MAX_ATTEMPTS


def _rate_limited_once(headers: dict):
    """Return a handler that 429s with ``headers`` once, then succeeds."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers=headers)
        return httpx.Response(200, json=_page([_record("1")], 1))

    return handler


def test_rate_limit_reset_is_an_absolute_epoch_not_a_delay():
    # The regression this guards: X-RateLimit-Reset is UTC epoch seconds, so
    # sleeping for its face value waits ~56.7 years. Measured live against
    # Zenodo: header 1787777909 with Date 2026-08-26T20:57:29Z (epoch
    # 1787777850) -- i.e. now+60. The delay must be reset - now, not reset.
    slept = []
    handler = _rate_limited_once({"X-RateLimit-Reset": str(int(NOW) + 60)})

    records = fetch_records(
        "q", client=_client(handler), sleep=slept.append, now=_at_now
    )

    assert slept == [60.0]
    assert [r["id"] for r in records] == ["1"]


def test_rate_limit_reset_already_past_waits_the_floor_not_a_negative_delay():
    slept = []
    handler = _rate_limited_once({"X-RateLimit-Reset": str(int(NOW) - 300)})

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == [1.0]


def test_rate_limit_reset_far_in_the_future_is_clamped():
    # A stale or hostile header must not be able to hang the process.
    slept = []
    handler = _rate_limited_once({"X-RateLimit-Reset": str(int(NOW) + 10**9)})

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == [MAX_SLEEP_SECONDS]


def test_missing_rate_limit_headers_fall_back_to_the_backoff_base():
    slept = []
    handler = _rate_limited_once({})

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == [1.0]


def test_record_missing_a_required_path_is_rejected_by_name():
    def handler(request):
        return httpx.Response(200, json=_page([{"id": "1", "metadata": {}}], 1))

    # re.escape because the dots are literal: unescaped they would match any
    # character, so the assertion would pass on a differently-named path.
    with pytest.raises(ShapeError, match=re.escape("metadata.resource_type.id")):
        fetch_records("q", client=_client(handler))


def test_retry_after_takes_precedence_over_rate_limit_reset():
    # Retry-After is a genuine delta, so its face value is used as-is. Pairing
    # it with an epoch-shaped X-RateLimit-Reset proves precedence rather than
    # coincidence: 5 is not derivable from the reset header under either model.
    slept = []
    handler = _rate_limited_once(
        {"Retry-After": "5", "X-RateLimit-Reset": str(int(NOW) + 600)}
    )

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == [5.0]


def test_hostile_retry_after_is_clamped():
    slept = []
    handler = _rate_limited_once({"Retry-After": "999999"})

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == [MAX_SLEEP_SECONDS]


def test_malformed_retry_after_falls_back_to_rate_limit_reset():
    slept = []
    handler = _rate_limited_once(
        {"Retry-After": "not-a-number", "X-RateLimit-Reset": str(int(NOW) + 45)}
    )

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == [45.0]


def test_low_rate_limit_remaining_throttles_before_the_budget_runs_out():
    # The spec requires honouring X-RateLimit-Remaining as well as -Reset:
    # a short pre-emptive sleep is much cheaper than taking a 429 and waiting
    # out the whole window.
    slept = []

    def handler(request):
        return httpx.Response(
            200,
            json=_page([_record("1")], 1),
            headers={"X-RateLimit-Remaining": "1"},
        )

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == [THROTTLE_SLEEP_SECONDS]


def test_ample_rate_limit_remaining_does_not_throttle():
    slept = []

    def handler(request):
        return httpx.Response(
            200,
            json=_page([_record("1")], 1),
            headers={"X-RateLimit-Remaining": "29"},
        )

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == []


def test_unparseable_rate_limit_remaining_does_not_throttle():
    slept = []

    def handler(request):
        return httpx.Response(
            200,
            json=_page([_record("1")], 1),
            headers={"X-RateLimit-Remaining": "lots"},
        )

    fetch_records("q", client=_client(handler), sleep=slept.append, now=_at_now)

    assert slept == []


def test_non_retryable_error_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404, text="nope")

    with pytest.raises(FetchError):
        fetch_records("q", client=_client(handler), sleep=lambda _: None)
    assert calls["n"] == 1
