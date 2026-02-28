"""context-harness MCP search tool for Google ADK agents."""
import logging
import os
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)


def ctx_search(query: str, limit: int = 5) -> Dict[str, Any]:
    """Search the context-harness knowledge base.

    Queries the local context-harness MCP server for relevant history,
    playbook content, or past campaign data. Fails open — if the server
    is not running, returns empty results so the pipeline can continue.

    Args:
        query: Natural language search query.
        limit: Maximum number of results to return (default 5).

    Returns:
        Dict with 'results' list and 'query' echo. On error, includes 'error' key.
    """
    base_url = os.environ.get("CTX_MCP_URL", "http://127.0.0.1:7331")
    timeout = int(os.environ.get("CTX_SEARCH_TIMEOUT", "5"))
    try:
        resp = requests.post(
            f"{base_url}/tools/search",
            json={"query": query, "limit": limit},
            timeout=timeout,
        )
        resp.raise_for_status()
        return {"results": resp.json().get("results", []), "query": query}
    except requests.exceptions.ConnectionError:
        logger.warning("context-harness not reachable — search skipped")
        return {"results": [], "query": query, "error": "context-harness unavailable"}
    except Exception as exc:
        return {"results": [], "query": query, "error": str(exc)}
