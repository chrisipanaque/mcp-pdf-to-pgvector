from fastapi import APIRouter

from app.api.tickets import router as tickets_router
from app.api.chat import router as chat_router
from app.api.ingestion import router as ingestion_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(tickets_router)
api_router.include_router(chat_router)
api_router.include_router(ingestion_router)
