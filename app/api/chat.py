import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.graph.graph import support_graph
from app.graph.state import SupportState
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    state = SupportState(
        messages=[],
        ticket_id=request.ticket_id,
        customer_id="",
        description=request.message,
    )
    config = {"configurable": {"thread_id": request.ticket_id}}
    result = await support_graph.ainvoke(state, config, db=db)
    return ChatResponse(
        ticket_id=result.get("ticket_id", request.ticket_id),
        response=result.get("draft_response", ""),
    )
