"""Tests for the oracle fixture generator's transport behaviour.

``refresh.py`` never runs in CI, but a bulk refresh is the single most likely
thing in this repository to exhaust Zenodo's 30 req/min search budget, so its
rate-limit handling is worth pinning down.
"""

import httpx
import pytest

from tests.oracle.refresh import MAX_ATTEMPTS, RETRY_STATUSES, _get_with_retry

NOW = 1787777850.0


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_rate_limiting_is_a_retryable_status():
    # 429 was originally absent from this set, so the one status a bulk fixture
    # run is most likely to hit was the one it treated as fatal.
    assert 429 in RETRY_STATUSES


def test_a_rate_limited_request_waits_for_the_reset_then_succeeds():
    calls = {"n": 0}
    slept = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429, headers={"X-RateLimit-Reset": str(int(NOW) + 30)}
            )
        return httpx.Response(200, text="@misc{x,\n}")

    response = _get_with_retry(
        _client(handler),
        "https://example.invalid/records",
        sleep=slept.append,
        now=lambda: NOW,
    )

    assert response.text == "@misc{x,\n}"
    # Waits until the window resets, not a blind exponential backoff, and
    # certainly not the header's face value (~56.7 years).
    assert slept == [30.0]


def test_a_transient_server_error_uses_exponential_backoff():
    calls = {"n": 0}
    slept = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(504, text="gateway timeout")
        return httpx.Response(200, text="ok")

    response = _get_with_retry(
        _client(handler),
        "https://example.invalid/records",
        sleep=slept.append,
        now=lambda: NOW,
    )

    assert response.text == "ok"
    assert slept == [1, 2]


def test_a_persistent_failure_eventually_raises():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    with pytest.raises(httpx.HTTPStatusError):
        _get_with_retry(
            _client(handler),
            "https://example.invalid/records",
            sleep=lambda _: None,
            now=lambda: NOW,
        )
    assert calls["n"] == MAX_ATTEMPTS


def test_a_non_retryable_error_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404, text="nope")

    with pytest.raises(httpx.HTTPStatusError):
        _get_with_retry(
            _client(handler),
            "https://example.invalid/records",
            sleep=lambda _: None,
            now=lambda: NOW,
        )
    assert calls["n"] == 1
