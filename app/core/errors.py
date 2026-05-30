from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "message": str(exc)},
    )


class TicketNotFoundError(HTTPException):
    def __init__(self, ticket_id: str):
        super().__init__(status_code=404, detail=f"Ticket {ticket_id} not found")
