"""Initialize the LLM backend from environment variables.

Provider selection:
  - ANTHROPIC_API_KEY set → Anthropic API (no Vertex AI init needed)
  - Otherwise → Vertex AI (requires GOOGLE_CLOUD_PROJECT + service account)

Import this module before instantiating any LlmAgent.
"""
import logging
import os
import vertexai

logger = logging.getLogger(__name__)


def init_vertex_ai() -> None:
    """Initialize the active LLM provider."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("LLM provider: Anthropic API (ANTHROPIC_API_KEY is set)")
    else:
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-east5")
        vertexai.init(project=project, location=location)
        logger.info("LLM provider: Vertex AI (project=%s, location=%s)", project, location)

    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        import litellm
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
