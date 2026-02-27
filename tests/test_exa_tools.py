"""Unit tests for exa_tools — verifies migration to search() with highlights."""
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_result(url="https://example.com", title="Example", highlights=None):
    r = MagicMock()
    r.url = url
    r.title = title
    r.highlights = highlights or ["relevant excerpt"]
    return r


def _make_mock_response(results=None):
    resp = MagicMock()
    resp.results = results or [_make_mock_result()]
    return resp


class TestExaSearchCompanies:
    @patch("tools.exa_tools._client")
    def test_uses_search_not_search_and_contents(self, mock_client_fn):
        """search() should be called, not the deprecated search_and_contents()."""
        client = MagicMock()
        client.search.return_value = _make_mock_response()
        mock_client_fn.return_value = client

        from tools.exa_tools import exa_search_companies
        exa_search_companies("B2B event organizers")

        client.search.assert_called_once()
        client.search_and_contents.assert_not_called()

    @patch("tools.exa_tools._client")
    def test_passes_highlights_not_text(self, mock_client_fn):
        """Should request highlights mode, not full text."""
        client = MagicMock()
        client.search.return_value = _make_mock_response()
        mock_client_fn.return_value = client

        from tools.exa_tools import exa_search_companies
        exa_search_companies("event organizers", num_results=5)

        call_kwargs = client.search.call_args
        assert "contents" in call_kwargs.kwargs
        contents = call_kwargs.kwargs["contents"]
        assert "highlights" in contents
        assert contents["highlights"]["maxCharacters"] == 4000

    @patch("tools.exa_tools._client")
    def test_uses_type_auto(self, mock_client_fn):
        """Should use type='auto' for best quality search."""
        client = MagicMock()
        client.search.return_value = _make_mock_response()
        mock_client_fn.return_value = client

        from tools.exa_tools import exa_search_companies
        exa_search_companies("test query")

        call_kwargs = client.search.call_args
        assert call_kwargs.kwargs.get("type") == "auto"

    @patch("tools.exa_tools._client")
    def test_returns_highlights_in_results(self, mock_client_fn):
        """Result dicts should contain highlights, not text."""
        client = MagicMock()
        client.search.return_value = _make_mock_response([
            _make_mock_result(highlights=["key insight about events"]),
        ])
        mock_client_fn.return_value = client

        from tools.exa_tools import exa_search_companies
        result = exa_search_companies("test")

        assert len(result["results"]) == 1
        assert "highlights" in result["results"][0]
        assert "text" not in result["results"][0]

    @patch("tools.exa_tools._client")
    def test_graceful_error_handling(self, mock_client_fn):
        """Should return error dict on exception, not raise."""
        client = MagicMock()
        client.search.side_effect = RuntimeError("API down")
        mock_client_fn.return_value = client

        from tools.exa_tools import exa_search_companies
        result = exa_search_companies("test")

        assert result["results"] == []
        assert "error" in result


class TestExaFindContact:
    @patch("tools.exa_tools._client")
    def test_uses_people_category(self, mock_client_fn):
        """Should use category='people' for contact searches."""
        client = MagicMock()
        client.search.return_value = _make_mock_response()
        mock_client_fn.return_value = client

        from tools.exa_tools import exa_find_contact
        exa_find_contact("Acme Corp", "acme.com")

        for call in client.search.call_args_list:
            assert call.kwargs.get("category") == "people"

    @patch("tools.exa_tools._client")
    def test_returns_highlights_not_text(self, mock_client_fn):
        """Contact results should use highlights, not full text."""
        client = MagicMock()
        client.search.return_value = _make_mock_response([
            _make_mock_result(highlights=["VP Marketing at Acme"]),
        ])
        mock_client_fn.return_value = client

        from tools.exa_tools import exa_find_contact
        result = exa_find_contact("Acme Corp", "acme.com")

        assert len(result["results"]) > 0
        assert "highlights" in result["results"][0]
        assert "text" not in result["results"][0]
