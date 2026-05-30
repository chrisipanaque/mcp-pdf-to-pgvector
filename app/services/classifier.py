from pydantic import BaseModel
from openai import OpenAI

from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)


class TicketClassification(BaseModel):
    category: str
    priority: str
    sentiment: str
    confidence: float
    summary: str
    requires_immediate: bool


SYSTEM_PROMPT = """You are a support ticket classifier. Classify the ticket into:
- category: "billing" | "technical" | "account" | "general"
- priority: "low" | "medium" | "high" | "critical"
- sentiment: "positive" | "neutral" | "negative"
- confidence: float between 0.0 and 1.0
- summary: one-sentence summary of the issue
- requires_immediate: true if this is a critical/urgent issue"""


def classify_ticket(description: str) -> TicketClassification:
    response = client.beta.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        response_format=TicketClassification,
        temperature=0.0,
    )
    result = response.choices[0].message.parsed
    if result is None:
        raise ValueError("OpenAI returned null classification")
    return result
