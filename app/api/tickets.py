from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import TicketNotFoundError
from app.graph.graph import support_graph
from app.graph.state import SupportState
from app.schemas.ticket import TicketApprove, TicketCreate, TicketResponse
from app.services.ticket_service import create_ticket, get_ticket, list_tickets, update_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TicketResponse, status_code=201)
async def create_ticket_endpoint(data: TicketCreate, db: AsyncSession = Depends(get_db)):
    ticket = await create_ticket(db, data)

    state = SupportState(
        messages=[],
        ticket_id=str(ticket.id),
        customer_id=ticket.customer_id,
        description=ticket.description or "",
    )
    config = {"configurable": {"thread_id": str(ticket.id)}}
    await support_graph.ainvoke(state, config, db=db)

    ticket = await update_ticket(db, ticket.id, {"status": "processing"})
    return ticket


@router.get("", response_model=list[TicketResponse])
async def list_tickets_endpoint(db: AsyncSession = Depends(get_db)):
    return await list_tickets(db)


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket_endpoint(ticket_id: str, db: AsyncSession = Depends(get_db)):
    ticket = await get_ticket(db, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(ticket_id)
    return ticket


@router.post("/{ticket_id}/approve", response_model=TicketResponse)
async def approve_ticket_endpoint(
    ticket_id: str,
    data: TicketApprove,
    db: AsyncSession = Depends(get_db),
):
    ticket = await get_ticket(db, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(ticket_id)

    updates = {"status": "approved" if data.approved else "rejected"}
    if data.edited_response:
        updates["draft_response"] = data.edited_response

    ticket = await update_ticket(db, ticket.id, updates)
    return ticket
