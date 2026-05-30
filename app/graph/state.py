from typing import Annotated, Literal, TypedDict
from operator import add

from langgraph.graph.message import add_messages


class SupportState(TypedDict):
    messages: Annotated[list, add_messages]
    ticket_id: str
    customer_id: str
    description: str
    category: str | None
    priority: str | None
    sentiment: str | None
    confidence: float | None
    summary: str | None
    retrieved_docs: Annotated[list[dict], add]
    draft_response: str | None
    requires_escalation: bool
    human_approved: bool | None
    human_edited_response: str | None
    error: str | None
