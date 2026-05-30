import uuid
from datetime import datetime

from pydantic import BaseModel


class TicketCreate(BaseModel):
    customer_id: str
    subject: str | None = None
    description: str | None = None
    metadata_: dict | None = None


class TicketResponse(BaseModel):
    id: uuid.UUID
    customer_id: str
    subject: str | None
    description: str | None
    category: str | None
    priority: str | None
    sentiment: str | None
    confidence: float | None
    summary: str | None
    status: str
    draft_response: str | None
    requires_escalation: bool
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class TicketApprove(BaseModel):
    approved: bool
    edited_response: str | None = None
