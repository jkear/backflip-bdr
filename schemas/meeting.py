"""Meeting booking and voice call schemas."""
from typing import List, Literal, Optional
from pydantic import BaseModel


CallStatus = Literal["BOOKED", "NO_ANSWER", "RESCHEDULED", "DECLINED", "SKIPPED"]


class CallPermissionRecord(BaseModel):
    lead_id: str
    contact_email: str
    contact_name: str
    company_name: str
    call_permission_granted: bool
    permission_granted_at: Optional[str] = None  # ISO datetime


class CallOutcome(BaseModel):
    lead_id: str
    call_status: CallStatus
    event_id: Optional[str] = None
    next_action: str
    reason: Optional[str] = None  # used when SKIPPED


class MeetingSlot(BaseModel):
    start_datetime: str   # ISO 8601
    end_datetime: str     # ISO 8601
    timezone: str = "America/Chicago"


class CalendarProposalOutput(BaseModel):
    lead_id: str
    proposed_slots: List[MeetingSlot]
    email_draft: str


class ConfirmedSlot(BaseModel):
    lead_id: str
    contact_name: str
    contact_email: str
    company_name: str
    slot: MeetingSlot


class ConfirmationOutput(BaseModel):
    event_id: str
    event_verified: bool
    confirmation_sent: bool
    confirmation_email_draft: str
