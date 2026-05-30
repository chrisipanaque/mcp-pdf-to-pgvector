import uuid

from pydantic import BaseModel


class ChatRequest(BaseModel):
    ticket_id: str
    message: str


class ChatResponse(BaseModel):
    ticket_id: uuid.UUID
    response: str
