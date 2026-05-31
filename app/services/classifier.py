import random

from pydantic import BaseModel

from app.config import settings


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

_has_key = bool(settings.openai_api_key) and settings.openai_api_key != "sk-..."
if _has_key:
    from openai import OpenAI
    _client = OpenAI(api_key=settings.openai_api_key)


def _mock_classify(description: str) -> TicketClassification:
    desc_lower = description.lower()
    if any(w in desc_lower for w in ["billing", "charge", "payment", "invoice", "refund"]):
        category = "billing"
    elif any(w in desc_lower for w in ["login", "password", "access", "account"]):
        category = "account"
    elif any(w in desc_lower for w in ["error", "bug", "crash", "broken", "not working", "fail"]):
        category = "technical"
    else:
        category = "general"

    if any(w in desc_lower for w in ["urgent", "critical", "emergency", "immediately", "asap"]):
        priority = "critical"
    elif any(w in desc_lower for w in ["high", "important"]):
        priority = "high"
    else:
        priority = random.choice(["low", "medium", "high"])

    sentiment = "positive" if any(w in desc_lower for w in ["please", "thanks", "thank you"]) else random.choice(["neutral", "negative"])
    if "furious" in desc_lower or "angry" in desc_lower:
        sentiment = "negative"

    requires_immediate = priority in ("critical", "high")
    summary = description[:100] + ("..." if len(description) > 100 else "")
    confidence = round(random.uniform(0.6, 0.95), 2)

    return TicketClassification(
        category=category,
        priority=priority,
        sentiment=sentiment,
        confidence=confidence,
        summary=summary,
        requires_immediate=requires_immediate,
    )


def classify_ticket(description: str) -> TicketClassification:
    if not _has_key:
        return _mock_classify(description)
    response = _client.beta.chat.completions.parse(
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
