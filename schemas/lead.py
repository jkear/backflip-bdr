"""Lead discovery and scoring schemas."""
from typing import List, Optional
from pydantic import BaseModel, Field


class Contact(BaseModel):
    name: str
    title: str
    email: str
    verified: bool = False


class RawLead(BaseModel):
    name: str
    website: str
    description: str
    event_type: str
    estimated_event_size: Optional[str] = None
    why_fit: str


class EnrichedLead(BaseModel):
    name: str
    website: str
    description: str
    event_type: str
    estimated_event_size: Optional[str] = None
    why_fit: str
    contacts: List[Contact] = Field(default_factory=list)


class IcpScoreDimensions(BaseModel):
    event_relevance: int = Field(ge=0, le=35)
    digital_ad_readiness: int = Field(ge=0, le=25)
    contact_quality: int = Field(ge=0, le=20)
    organization_size_fit: int = Field(ge=0, le=20)
    reasoning: str


class ScoredLead(BaseModel):
    name: str
    website: str
    description: str
    event_type: str
    estimated_event_size: Optional[str] = None
    why_fit: str
    contacts: List[Contact]
    personalization_hook: Optional[str] = None
    score: int = Field(ge=0, le=100)
    score_dimensions: IcpScoreDimensions


class LeadDiscoveryOutput(BaseModel):
    leads: List[RawLead]


class LeadEnrichmentOutput(BaseModel):
    leads: List[EnrichedLead]


class LeadScoringOutput(BaseModel):
    qualified_leads: List[ScoredLead]
    rejected_leads: List[ScoredLead]
