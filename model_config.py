"""Model provider selection.

Priority:
  1. ANTHROPIC_API_KEY set → use Anthropic API directly (faster, simpler)
  2. Otherwise → use Vertex AI (requires GOOGLE_CLOUD_PROJECT + service account)

Usage:
    from model_config import get_llm_model
    model = get_llm_model()
"""
import os
from google.adk.models.lite_llm import LiteLlm

# Model identifiers
ANTHROPIC_MODEL = "anthropic/claude-sonnet-4-6"
VERTEX_MODEL = "vertex_ai/claude-sonnet-4-5@20250929"


def get_llm_model() -> LiteLlm:
    """Return a LiteLlm instance for the active provider.

    Selects Anthropic API if ANTHROPIC_API_KEY is set, otherwise Vertex AI.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LiteLlm(ANTHROPIC_MODEL)
    return LiteLlm(VERTEX_MODEL)


def active_provider() -> str:
    """Return 'anthropic' or 'vertex_ai' depending on which is active."""
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "vertex_ai"
