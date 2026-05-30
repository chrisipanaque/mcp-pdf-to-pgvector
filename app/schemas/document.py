import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    source_type: str
    url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
