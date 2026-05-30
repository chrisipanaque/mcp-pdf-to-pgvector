import pytest

from app.graph.state import SupportState


def test_support_state_defaults():
    state: SupportState = {
        "messages": [],
        "ticket_id": "test-123",
        "customer_id": "cust-001",
        "description": "My order hasn't arrived",
        "category": None,
        "priority": None,
        "sentiment": None,
        "confidence": None,
        "summary": None,
        "retrieved_docs": [],
        "draft_response": None,
        "requires_escalation": False,
        "human_approved": None,
        "human_edited_response": None,
        "error": None,
    }
    assert state["ticket_id"] == "test-123"
    assert state["description"] == "My order hasn't arrived"
    assert state["requires_escalation"] is False


@pytest.mark.asyncio
async def test_classify_node_missing_description():
    from app.graph.nodes import classify_node

    state: SupportState = {
        "messages": [],
        "ticket_id": "test-1",
        "customer_id": "cust-001",
        "description": "",
        "category": None,
        "priority": None,
        "sentiment": None,
        "confidence": None,
        "summary": None,
        "retrieved_docs": [],
        "draft_response": None,
        "requires_escalation": False,
        "human_approved": None,
        "human_edited_response": None,
        "error": None,
    }
    result = await classify_node(state, None)
    assert "error" in result


def test_should_escalate():
    from app.graph.nodes import should_escalate

    state: SupportState = {
        "messages": [],
        "ticket_id": "test-1",
        "customer_id": "cust-001",
        "description": "test",
        "category": None,
        "priority": None,
        "sentiment": None,
        "confidence": None,
        "summary": None,
        "retrieved_docs": [],
        "draft_response": None,
        "requires_escalation": True,
        "human_approved": None,
        "human_edited_response": None,
        "error": None,
    }
    assert should_escalate(state) == "human_review"

    state["requires_escalation"] = False
    assert should_escalate(state) == "generate_response"
