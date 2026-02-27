"""Hunter.io email enrichment tools for Google ADK agents.

Calls Hunter.io REST API directly (no official Python SDK).
"""
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests


HUNTER_BASE = "https://api.hunter.io/v2"
PRIORITY_TITLES = [
    "vp marketing", "director of events", "director marketing", "cmo",
    "chief marketing", "executive director", "membership director",
    "director of communications", "director communications",
    "head of marketing", "marketing manager",
]


def _api_key() -> str:
    return os.environ["HUNTER_API_KEY"]


def hunter_domain_search(domain: str, limit: int = 5) -> Dict[str, Any]:
    """Search Hunter.io for email addresses at a domain.

    Args:
        domain: Company domain to search (e.g. example.com).
        limit: Max contacts to return (default 5).

    Returns:
        Dict with 'pattern', 'contacts' list, and 'organization'.
    """
    try:
        params = urlencode({
            "domain": domain,
            "limit": limit,
            "api_key": _api_key(),
        })
        resp = requests.get(f"{HUNTER_BASE}/domain-search?{params}", timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {})

        contacts = []
        for email_entry in data.get("emails", []):
            full_name = f"{email_entry.get('first_name', '')} {email_entry.get('last_name', '')}".strip()
            contacts.append({
                "name": full_name,
                "title": email_entry.get("position", ""),
                "email": email_entry.get("value", ""),
                "verified": email_entry.get("verification", {}).get("status") == "valid",
            })

        # Sort: prioritize decision-maker titles
        def _priority(c: Dict) -> int:
            title_lower = c.get("title", "").lower()
            for i, t in enumerate(PRIORITY_TITLES):
                if t in title_lower:
                    return i
            return 99

        contacts.sort(key=_priority)

        return {
            "domain": domain,
            "organization": data.get("organization", ""),
            "email_pattern": data.get("pattern", ""),
            "contacts": contacts[:limit],
        }
    except Exception as exc:
        return {"domain": domain, "contacts": [], "error": str(exc)}


def hunter_verify_email(email: str) -> Dict[str, Any]:
    """Verify whether an email address is valid via Hunter.io.

    Args:
        email: Email address to verify.

    Returns:
        Dict with 'email', 'status' (valid/invalid/accept_all/unknown), 'score'.
    """
    try:
        params = urlencode({"email": email, "api_key": _api_key()})
        resp = requests.get(f"{HUNTER_BASE}/email-verifier?{params}", timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {
            "email": email,
            "status": data.get("status", "unknown"),
            "score": data.get("score", 0),
            "verified": data.get("status") == "valid",
        }
    except Exception as exc:
        return {"email": email, "status": "unknown", "verified": False, "error": str(exc)}


def hunter_find_email(
    domain: str,
    first_name: str,
    last_name: str,
) -> Dict[str, Any]:
    """Find and verify a specific person's email via Hunter.io.

    Args:
        domain: Company domain.
        first_name: Contact's first name.
        last_name: Contact's last name.

    Returns:
        Dict with 'email', 'score', 'verified'.
    """
    try:
        params = urlencode({
            "domain": domain,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": _api_key(),
        })
        resp = requests.get(f"{HUNTER_BASE}/email-finder?{params}", timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {
            "email": data.get("email", ""),
            "score": data.get("score", 0),
            "verified": data.get("score", 0) >= 70,
        }
    except Exception as exc:
        return {"email": "", "verified": False, "error": str(exc)}
