"""Unit tests for context_harness_tools — no running server required."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.context_harness_tools import ctx_search


def test_graceful_degradation_connection_error():
    """Should return empty results + error key when server is unreachable."""
    with patch(
        "tools.context_harness_tools.requests.post",
        side_effect=requests.exceptions.ConnectionError("Connection refused"),
    ):
        result = ctx_search("personalization hooks that converted")

    assert result["results"] == []
    assert result["query"] == "personalization hooks that converted"
    assert "error" in result
    assert "unavailable" in result["error"]


def test_parses_results_correctly():
    """Should correctly return the results array from the server response."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"id": "doc-1", "content": "ICP profiler context for event organizers", "score": 0.92},
            {"id": "doc-2", "content": "Objection handling for pricing questions", "score": 0.78},
        ]
    }
    mock_response.raise_for_status.return_value = None

    with patch("tools.context_harness_tools.requests.post", return_value=mock_response):
        result = ctx_search("ICP scoring event organizer", limit=3)

    assert len(result["results"]) == 2
    assert result["results"][0]["content"] == "ICP profiler context for event organizers"
    assert result["query"] == "ICP scoring event organizer"
    assert "error" not in result


def test_handles_generic_exception():
    """Should return error key for any unexpected exception."""
    with patch(
        "tools.context_harness_tools.requests.post",
        side_effect=ValueError("unexpected error"),
    ):
        result = ctx_search("test query")

    assert result["results"] == []
    assert "error" in result
    assert "unexpected error" in result["error"]


def test_empty_results_from_server():
    """Should handle a valid response with an empty results list."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.raise_for_status.return_value = None

    with patch("tools.context_harness_tools.requests.post", return_value=mock_response):
        result = ctx_search("email history Acme Corp")

    assert result["results"] == []
    assert result["query"] == "email history Acme Corp"
    assert "error" not in result


def test_uses_env_vars_for_url_and_timeout(monkeypatch):
    """Should respect CTX_MCP_URL and CTX_SEARCH_TIMEOUT env vars."""
    monkeypatch.setenv("CTX_MCP_URL", "http://custom-host:9000")
    monkeypatch.setenv("CTX_SEARCH_TIMEOUT", "10")

    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        raise requests.exceptions.ConnectionError("test")

    with patch("tools.context_harness_tools.requests.post", side_effect=fake_post):
        # Re-import to pick up the new env var (module-level CTX_BASE_URL is read at call time)
        import importlib
        import tools.context_harness_tools as mod
        importlib.reload(mod)
        mod.ctx_search("test")

    assert captured["url"] == "http://custom-host:9000/tools/search"
    assert captured["timeout"] == 10
