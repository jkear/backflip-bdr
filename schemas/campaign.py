"""Email campaign and response handling schemas."""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class EmailTouch(BaseModel):
    touch_number: int = Field(ge=1, le=3)
    send_day: int
    subject: str
    body: str


class EmailSequence(BaseModel):
    lead_id: str
    lead_name: str
    contacts: List[str]  # list of email addresses
    emails: List[EmailTouch] = Field(min_length=3, max_length=3)
    send_schedule: dict = Field(
        default_factory=lambda: {"touch_1": 1, "touch_2": 5, "touch_3": 10}
    )
    unsubscribe_footer: str = (
        "To unsubscribe from these emails, reply with 'unsubscribe'."
    )


class CampaignOutput(BaseModel):
    campaign_path: str
    lead_count: int
    sequences: List[EmailSequence]


ReplyClassification = Literal["INTERESTED", "NURTURE", "NOT_FIT", "UNSUBSCRIBE"]


class ReplyClassificationOutput(BaseModel):
    classification: ReplyClassification
    reasoning: str
    key_phrase: str
    lead_id: str


class CallPermissionEmailOutput(BaseModel):
    email_draft: str
    subject: str
    awaiting_call_permission: bool = True
    lead_id: str


class NurtureScheduleOutput(BaseModel):
    lead_id: str
    recontact_date: str  # YYYY-MM-DD
    recontact_note: str
