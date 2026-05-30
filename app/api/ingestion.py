from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.document import DocumentSource
from app.schemas.document import DocumentResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", status_code=201)
async def upload_document(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = (await file.read()).decode("utf-8")
    source = DocumentSource(
        title=file.filename or "untitled",
        source_type="upload",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return {"id": str(source.id), "title": source.title, "size": len(content)}


@router.get("", response_model=list[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DocumentSource).order_by(DocumentSource.created_at.desc()))
    return result.scalars().all()
