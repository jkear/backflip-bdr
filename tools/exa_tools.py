"""Exa semantic search tools for Google ADK agents."""
import os
from typing import Any, Dict, List, Optional

from exa_py import Exa


def _client() -> Exa:
    return Exa(api_key=os.environ["EXA_API_KEY"])


def exa_search_companies(
    query: str,
    num_results: int = 10,
    category: str = "company",
) -> Dict[str, Any]:
    """Search for companies using Exa semantic search.

    Args:
        query: Natural language search query.
        num_results: Number of results to return (max 25).
        category: Exa category filter (default: "company").

    Returns:
        Dict with 'results' list, each containing url, title, text, highlights.
    """
    try:
        client = _client()
        response = client.search_and_contents(
            query,
            num_results=min(num_results, 25),
            category=category,
            text=True,
            highlights=True,
        )
        results = [
            {
                "url": r.url,
                "title": r.title or "",
                "text": (r.text or "")[:2000],
                "highlights": r.highlights or [],
            }
            for r in response.results
        ]
        return {"results": results, "query": query}
    except Exception as exc:
        return {"results": [], "query": query, "error": str(exc)}


def exa_find_contact(company_name: str, domain: str) -> Dict[str, Any]:
    """Search for decision-maker contact info for a company.

    Args:
        company_name: Company name.
        domain: Company domain (e.g. example.com).

    Returns:
        Dict with 'results' containing contact clues found.
    """
    queries = [
        f"{company_name} VP Marketing director email",
        f"site:{domain} team leadership marketing",
        f"{company_name} executive director membership",
    ]
    all_results: List[Dict] = []
    client = _client()
    for q in queries:
        try:
            resp = client.search_and_contents(q, num_results=3, text=True)
            for r in resp.results:
                all_results.append({
                    "url": r.url,
                    "title": r.title or "",
                    "text": (r.text or "")[:1000],
                })
        except Exception:
            continue
    return {"results": all_results, "company": company_name, "domain": domain}
