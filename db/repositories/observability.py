"""Observability repository — agent run and API cost logging."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentRunLog, ApiCostLog

logger = logging.getLogger(__name__)


async def log_agent_run(
    session: AsyncSession,
    agent_name: str,
    *,
    session_id: Optional[str] = None,
    team_name: Optional[str] = None,
    stage_number: Optional[int] = None,
    org_id: Optional[UUID] = None,
    langfuse_trace_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
    duration_ms: Optional[int] = None,
    success: Optional[bool] = None,
    error_message: Optional[str] = None,
    model_used: Optional[str] = None,
    input_token_count: Optional[int] = None,
    output_token_count: Optional[int] = None,
    estimated_llm_cost_usd=None,
) -> AgentRunLog:
    """Log a completed (or failed) agent run."""
    run = AgentRunLog(
        session_id=session_id,
        agent_name=agent_name,
        team_name=team_name,
        stage_number=stage_number,
        org_id=org_id,
        langfuse_trace_id=langfuse_trace_id,
        started_at=started_at or datetime.now(timezone.utc),
        completed_at=completed_at,
        duration_ms=duration_ms,
        success=success,
        error_message=error_message,
        model_used=model_used,
        input_token_count=input_token_count,
        output_token_count=output_token_count,
        estimated_llm_cost_usd=estimated_llm_cost_usd,
    )
    session.add(run)
    await session.flush()
    return run


async def log_api_cost(
    session: AsyncSession,
    service: str,
    *,
    operation: Optional[str] = None,
    org_id: Optional[UUID] = None,
    agent_run_id: Optional[UUID] = None,
    estimated_cost_usd=None,
    units_used: Optional[int] = None,
    success: Optional[bool] = None,
) -> ApiCostLog:
    """Log an external API call cost (Exa, Hunter, ElevenLabs, Google Calendar)."""
    cost = ApiCostLog(
        service=service,
        operation=operation,
        org_id=org_id,
        agent_run_id=agent_run_id,
        estimated_cost_usd=estimated_cost_usd,
        units_used=units_used,
        success=success,
    )
    session.add(cost)
    await session.flush()
    return cost
