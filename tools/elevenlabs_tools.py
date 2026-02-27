"""ElevenLabs Conversational AI tools for Google ADK agents.

Only Conversational AI (live calls) — no cold-call TTS drops.
Calls are gated: only triggered after explicit written permission from the lead.
"""
import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


def _headers() -> Dict[str, str]:
    return {
        "xi-api-key": os.environ["ELEVENLABS_API_KEY"],
        "Content-Type": "application/json",
    }


def elevenlabs_create_conv_agent(
    agent_name: str,
    system_prompt: str,
    first_message: str,
    voice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update an ElevenLabs Conversational AI agent.

    Args:
        agent_name: Display name for the agent.
        system_prompt: Full system prompt including persona, objection handling, etc.
        first_message: Opening line the agent says when the call connects.
        voice_id: ElevenLabs voice ID (defaults to env ELEVENLABS_VOICE_ID).

    Returns:
        Dict with 'agent_id' and creation status.
    """
    existing_id = os.environ.get("ELEVENLABS_CONV_AGENT_ID", "").strip()
    if existing_id:
        return {"agent_id": existing_id, "reused": True}

    vid = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "")
    payload = {
        "name": agent_name,
        "conversation_config": {
            "agent": {
                "prompt": {"prompt": system_prompt},
                "first_message": first_message,
            },
            "tts": {"voice_id": vid} if vid else {},
        },
    }
    try:
        resp = requests.post(
            f"{ELEVENLABS_BASE}/convai/agents/create",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        agent_id = data.get("agent_id", "")
        logger.info(
            "Created new ElevenLabs agent: %s — set ELEVENLABS_CONV_AGENT_ID=%s in .env to reuse it",
            agent_id,
            agent_id,
        )
        return {"agent_id": agent_id, "status": "created", "reused": False}
    except Exception as exc:
        return {"agent_id": "", "status": "error", "error": str(exc)}


def elevenlabs_initiate_call(
    agent_id: str,
    phone_number: str,
    metadata: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Initiate an outbound call using an ElevenLabs Conversational AI agent.

    IMPORTANT: This function must only be called when call_permission_granted == True.
    The caller (ConversationalVoiceAgent) is responsible for enforcing this gate.

    Args:
        agent_id: ElevenLabs Conversational AI agent ID.
        phone_number: E.164 format phone number (e.g. +15551234567).
        metadata: Optional key-value pairs passed to the agent (e.g. lead context).

    Returns:
        Dict with 'call_id' and 'status'.
    """
    payload: Dict[str, Any] = {
        "agent_id": agent_id,
        "customer_number": phone_number,
    }
    if metadata:
        payload["metadata"] = metadata

    try:
        resp = requests.post(
            f"{ELEVENLABS_BASE}/convai/twilio/outbound-call",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "call_id": data.get("callSid", data.get("call_id", "")),
            "status": "initiated",
        }
    except Exception as exc:
        return {"call_id": "", "status": "error", "error": str(exc)}


def elevenlabs_get_call_status(call_id: str) -> Dict[str, Any]:
    """Get the status and outcome of a completed call.

    Args:
        call_id: Call SID or ID returned by elevenlabs_initiate_call.

    Returns:
        Dict with 'status', 'transcript', 'outcome'.
    """
    try:
        resp = requests.get(
            f"{ELEVENLABS_BASE}/convai/calls/{call_id}",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "call_id": call_id,
            "status": data.get("status", "unknown"),
            "transcript": data.get("transcript", ""),
            "outcome": data.get("analysis", {}).get("call_successful", "unknown"),
        }
    except Exception as exc:
        return {"call_id": call_id, "status": "unknown", "error": str(exc)}
