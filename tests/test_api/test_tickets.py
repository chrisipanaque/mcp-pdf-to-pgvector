import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_ready_check(client: AsyncClient):
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_create_ticket(client: AsyncClient):
    payload = {
        "customer_id": "cust-001",
        "subject": "Cannot login",
        "description": "I keep getting an error when trying to log in to my account.",
    }
    response = await client.post("/api/v1/tickets", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["customer_id"] == "cust-001"
    assert data["status"] == "processing"


@pytest.mark.asyncio
async def test_get_ticket_not_found(client: AsyncClient):
    response = await client.get("/api/v1/tickets/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_documents_empty(client: AsyncClient):
    response = await client.get("/api/v1/documents")
    assert response.status_code == 200
    assert response.json() == []
