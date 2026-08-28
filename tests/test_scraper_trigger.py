"""Tests for the protected Tool 1 workflow dispatcher."""

import json
from urllib.error import HTTPError, URLError

import pytest

from scraper_trigger import (
    ScraperTriggerError,
    dispatch_scraper,
    workflow_dispatch_url,
)


class _Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status


def test_dispatch_targets_tool1_main_without_leaking_token_into_url():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    dispatch_scraper("secret-token", opener=opener)

    request = captured["request"]
    assert request.full_url == workflow_dispatch_url()
    assert "secret-token" not in request.full_url
    assert json.loads(request.data) == {"ref": "main"}
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert captured["timeout"] == 20


def test_dispatch_requires_a_configured_token():
    with pytest.raises(ScraperTriggerError, match="not configured"):
        dispatch_scraper("")


def test_http_error_is_sanitised_and_does_not_include_response_body():
    def opener(request, timeout):
        raise HTTPError(request.full_url, 403, "forbidden", {}, None)

    with pytest.raises(ScraperTriggerError, match="HTTP 403") as exc_info:
        dispatch_scraper("secret-token", opener=opener)
    assert "secret-token" not in str(exc_info.value)


def test_network_failure_returns_retryable_message():
    def opener(_request, timeout):
        assert timeout == 20
        raise URLError("offline")

    with pytest.raises(ScraperTriggerError, match="temporarily unavailable"):
        dispatch_scraper("secret-token", opener=opener)
