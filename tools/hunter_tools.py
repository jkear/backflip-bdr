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


# ---------------------------------------------------------------------------
# Hunter Campaigns (Email Sequences) — all calls are FREE
# ---------------------------------------------------------------------------


def hunter_create_lead(
    email: str,
    first_name: str = "",
    last_name: str = "",
    position: str = "",
    company: str = "",
    website: str = "",
    leads_list_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a lead in Hunter. Free API call — no credits consumed.

    Args:
        email: Lead email address (required).
        first_name: Contact first name.
        last_name: Contact last name.
        position: Job title.
        company: Company name.
        website: Company domain.
        leads_list_id: Optional list to add the lead to.

    Returns:
        Dict with 'lead_id' and 'email'.
    """
    try:
        payload: Dict[str, Any] = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "company": company,
            "website": website,
        }
        if leads_list_id is not None:
            payload["leads_list_id"] = leads_list_id
        resp = requests.post(
            f"{HUNTER_BASE}/leads",
            params={"api_key": _api_key()},
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {"lead_id": data.get("id"), "email": email}
    except Exception as exc:
        return {"lead_id": None, "email": email, "error": str(exc)}


def hunter_add_recipient(
    campaign_id: int,
    emails: List[str],
) -> Dict[str, Any]:
    """Add recipients to a Hunter email sequence. Free API call.

    WARNING: If the sequence is already started, emails may send shortly
    after this call — there is no undo window.

    Args:
        campaign_id: Hunter campaign/sequence ID.
        emails: List of email addresses (max 50 per call).

    Returns:
        Dict with 'campaign_id', 'added' list, and 'skipped' list.
    """
    try:
        resp = requests.post(
            f"{HUNTER_BASE}/campaigns/{campaign_id}/recipients",
            params={"api_key": _api_key()},
            json={"emails": emails[:50]},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {
            "campaign_id": campaign_id,
            "added": data.get("recipients", []),
            "skipped": data.get("skipped_recipients", []),
        }
    except Exception as exc:
        return {"campaign_id": campaign_id, "added": [], "skipped": [], "error": str(exc)}


def hunter_list_campaigns(
    started: Optional[bool] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """List email sequences in the Hunter account. Free API call.

    Args:
        started: Filter to only started (True) or not-started (False) sequences.
        limit: Max sequences to return (1-100, default 20).

    Returns:
        Dict with 'campaigns' list.
    """
    try:
        params: Dict[str, Any] = {"api_key": _api_key(), "limit": min(limit, 100)}
        if started is not None:
            params["started"] = str(started).lower()
        resp = requests.get(f"{HUNTER_BASE}/campaigns", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {"campaigns": data.get("campaigns", [])}
    except Exception as exc:
        return {"campaigns": [], "error": str(exc)}


def hunter_start_campaign(campaign_id: int) -> Dict[str, Any]:
    """Start a Hunter email sequence. Free API call.

    Once started, emails begin sending to all recipients on the configured
    schedule. This action cannot be undone — the sequence can only be paused.

    Args:
        campaign_id: Hunter campaign/sequence ID.

    Returns:
        Dict with 'campaign_id' and 'started' status.
    """
    try:
        resp = requests.put(
            f"{HUNTER_BASE}/campaigns/{campaign_id}/start",
            params={"api_key": _api_key()},
            timeout=10,
        )
        resp.raise_for_status()
        return {"campaign_id": campaign_id, "started": True}
    except Exception as exc:
        return {"campaign_id": campaign_id, "started": False, "error": str(exc)}
