from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.state import SupportState
from app.services.classifier import classify_ticket
from app.services.rag_service import hybrid_search, generate_rag_response


async def classify_node(state: SupportState, db: AsyncSession) -> dict:
    description = state.get("description", "")
    if not description:
        return {"error": "No description provided for classification"}

    result = classify_ticket(description)
    return {
        "category": result.category,
        "priority": result.priority,
        "sentiment": result.sentiment,
        "confidence": result.confidence,
        "summary": result.summary,
    }


async def retrieve_node(state: SupportState, db: AsyncSession) -> dict:
    query = state.get("description", "")
    if state.get("summary"):
        query = state["summary"]

    docs = await hybrid_search(db, query, top_k=8)
    return {"retrieved_docs": docs}


async def analyze_node(state: SupportState, db: AsyncSession) -> dict:
    docs = state.get("retrieved_docs", [])
    high_score_docs = [d for d in docs if d.get("score", 0) > 0.5]
    return {
        "has_relevant_docs": len(high_score_docs) > 0,
    }


async def check_escalation_node(state: SupportState) -> dict:
    sentiment = state.get("sentiment")
    priority = state.get("priority")
    confidence = state.get("confidence", 0.0)

    requires_escalation = False
    if sentiment == "negative" and priority == "critical":
        requires_escalation = True
    if confidence is not None and confidence < 0.5:
        requires_escalation = True

    return {"requires_escalation": requires_escalation}


async def generate_response_node(state: SupportState, db: AsyncSession) -> dict:
    query = state.get("description", "")
    docs = state.get("retrieved_docs", [])

    rag_result = await generate_rag_response(query, docs)
    return {"draft_response": rag_result.answer}


async def human_review_node(state: SupportState) -> dict:
    value = interrupt(
        {
            "draft_response": state.get("draft_response"),
            "ticket_id": state.get("ticket_id"),
            "category": state.get("category"),
            "priority": state.get("priority"),
            "sentiment": state.get("sentiment"),
        }
    )
    approved = value.get("approved", False)
    edited_response = value.get("edited_response")
    return {
        "human_approved": approved,
        "human_edited_response": edited_response,
    }


async def resolve_node(state: SupportState) -> dict:
    final_response = state.get("human_edited_response") or state.get("draft_response")
    return {
        "draft_response": final_response,
        "status": "resolved",
    }


def should_escalate(state: SupportState) -> str:
    if state.get("requires_escalation"):
        return "human_review"
    return "generate_response"
