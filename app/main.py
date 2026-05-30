from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.errors import global_exception_handler
from app.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Customer Support AI Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)
app.add_exception_handler(Exception, global_exception_handler)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}
