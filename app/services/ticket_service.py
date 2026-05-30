import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket, TicketMessage
from app.schemas.ticket import TicketCreate


async def create_ticket(db: AsyncSession, data: TicketCreate) -> Ticket:
    ticket = Ticket(
        customer_id=data.customer_id,
        subject=data.subject,
        description=data.description,
        metadata_=data.metadata_ or {},
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def get_ticket(db: AsyncSession, ticket_id: str) -> Ticket | None:
    uid = uuid.UUID(ticket_id)
    result = await db.execute(select(Ticket).where(Ticket.id == uid))
    return result.scalar_one_or_none()


async def update_ticket(db: AsyncSession, ticket_id: uuid.UUID, updates: dict) -> Ticket | None:
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        return None
    for key, value in updates.items():
        setattr(ticket, key, value)
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def add_message(db: AsyncSession, ticket_id: uuid.UUID, role: str, content: str) -> TicketMessage:
    msg = TicketMessage(ticket_id=ticket_id, role=role, content=content)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg
