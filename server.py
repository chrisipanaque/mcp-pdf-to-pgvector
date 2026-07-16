from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import fitz
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Context
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "nomic-ai/nomic-embed-text-v2-moe"
EMBEDDING_DIM = 768


class Settings:
    pgvector_host: str = os.getenv("PGVECTOR_HOST", "localhost")
    pgvector_port: int = int(os.getenv("PGVECTOR_PORT", "5432"))
    pgvector_database: str = os.getenv("PGVECTOR_DATABASE", "vectordb")
    pgvector_user: str = os.getenv("PGVECTOR_USER", "postgres")
    pgvector_password: str = os.getenv("PGVECTOR_PASSWORD", "")

    @property
    def pgvector_dsn(self) -> str:
        return (
            f"postgresql://{self.pgvector_user}:{self.pgvector_password}"
            f"@{self.pgvector_host}:{self.pgvector_port}/{self.pgvector_database}"
        )


class Embedder:
    def __init__(self, model: SentenceTransformer) -> None:
        self._model = model

    @classmethod
    def load(cls) -> Embedder:
        return cls(
            SentenceTransformer(MODEL_NAME, trust_remote_code=True)
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.tolist()


def scan_pdfs(pdf_directory: str) -> list[str]:
    pdf_dir = Path(pdf_directory).expanduser().resolve()
    if not pdf_dir.is_dir():
        raise NotADirectoryError(f"PDF directory not found: {pdf_dir}")
    return sorted(
        str(p) for p in pdf_dir.rglob("*.pdf") if p.suffix.lower() == ".pdf"
    )


def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def chunk_text(
    text: str, chunk_size: int = 1000, chunk_overlap: int = 200
) -> list[str]:
    if not text.strip():
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            search_start = max(start + chunk_size // 2, end - chunk_size // 2)
            candidate = end
            for sep in ["\n\n", "\n", ". ", "! ", "? ", " "]:
                pos = text.rfind(sep, search_start, end)
                if pos > search_start:
                    candidate = pos + len(sep)
                    break
            end = candidate

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - chunk_overlap if end < text_len else text_len

    return chunks


def compute_file_hash(pdf_path: str) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        while True:
            buf = f.read(65536)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


class VectorStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> VectorStore:
        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=8)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def ensure_table(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS documents (
                    id BIGSERIAL PRIMARY KEY,
                    collection_name TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    chunk_index INT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({EMBEDDING_DIM}),
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(collection_name, file_hash, chunk_index)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_documents_collection
                ON documents (collection_name)
            """)

    async def chunk_exists(
        self, collection_name: str, file_hash: str, chunk_index: int
    ) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT 1 FROM documents WHERE collection_name=$1 AND file_hash=$2 AND chunk_index=$3",
                collection_name,
                file_hash,
                chunk_index,
            )
            return row is not None

    async def insert_batch(
        self,
        collection_name: str,
        contents: list[str],
        embeddings: list[list[float]],
        metadata_list: list[dict],
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO documents
                    (collection_name, file_hash, file_path, chunk_index, content, embedding, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)
                ON CONFLICT (collection_name, file_hash, chunk_index) DO NOTHING
                """,
                [
                    (
                        collection_name,
                        m["file_hash"],
                        m["file_path"],
                        m["chunk_index"],
                        content,
                        embedding,
                        m.get("metadata", {}),
                    )
                    for content, embedding, m in zip(
                        contents, embeddings, metadata_list
                    )
                ],
            )

    async def create_hnsw_index(self, collection_name: str) -> None:
        index_name = f"idx_{collection_name}_embedding_hnsw"
        async with self._pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_indexes WHERE indexname = $1",
                index_name,
            )
            if not exists:
                await conn.execute(
                    f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}
                    ON documents USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 200)
                    WHERE collection_name = $1
                    """,
                    collection_name,
                )


# ── MCP Server ──────────────────────────────────────────────────────

tasks: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    settings = Settings()
    embedder = await asyncio.to_thread(Embedder.load)
    db = await VectorStore.connect(settings.pgvector_dsn)
    try:
        yield {"settings": settings, "embedder": embedder, "db": db}
    finally:
        await db.close()


mcp = FastMCP("mcp-pdf-to-pgvector", lifespan=lifespan)


@mcp.tool()
async def index_pdfs_for_rag(
    pdf_directory: str,
    collection_name: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    batch_size: int = 50,
    resume: bool = True,
    ctx: Context | None = None,
) -> str:
    """Index PDF documents into a vector database for semantic search and RAG.

    Use this when a user wants to make a directory of PDFs searchable via natural
    language queries — for example, building a knowledge base, enabling Q&A over
    documents, or powering a RAG pipeline.

    Starts a background task that extracts text, splits into chunks, generates
    embeddings (nomic-embed-text-v2, 768-dim), and stores in pgvector. Returns a
    task_id immediately — poll check_indexing_progress to monitor completion.

    chunk_size (1000 chars) and chunk_overlap (200) are good defaults for most
    documents. For code-heavy or highly technical PDFs, consider chunk_size=500
    for more precise retrieval. collection_name is the logical namespace used at
    query time — use descriptive names like "company-policies".
    """
    assert ctx is not None
    lifespan_data = ctx.request_context.lifespan_context
    embedder: Embedder = lifespan_data["embedder"]
    db: VectorStore = lifespan_data["db"]

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "running",
        "total_files": 0,
        "processed_files": 0,
        "skipped_files": 0,
        "failed_files": 0,
        "total_chunks": 0,
        "inserted_chunks": 0,
        "skipped_chunks": 0,
        "errors": [],
        "current_file": "",
    }
    asyncio.create_task(
        _run_ingestion(
            task_id,
            pdf_directory,
            collection_name,
            chunk_size,
            chunk_overlap,
            batch_size,
            resume,
            embedder,
            db,
        )
    )
    return json.dumps({"task_id": task_id, "status": "started"})


@mcp.tool()
async def check_indexing_progress(task_id: str) -> str:
    """Check the progress of a PDF indexing task.

    Use this after calling index_pdfs_for_rag to monitor completion, or when a
    user asks "is it done yet?" or wants a summary of what was indexed.

    Returns status (running/completed/failed/cancelled), file counts, chunk
    counts, per-file errors, and the current file being processed.
    """
    task = tasks.get(task_id)
    if task is None:
        return json.dumps({"error": f"Task {task_id} not found"})
    return json.dumps(task, default=str)


@mcp.tool()
async def cancel_pdf_indexing(task_id: str) -> str:
    """Cancel a running PDF indexing task.

    Use this when a user wants to stop an ongoing indexing operation, or when a
    task appears stuck or is taking too long. Only takes effect if the task is
    currently in "running" state.
    """
    task = tasks.get(task_id)
    if task is None:
        return json.dumps({"error": f"Task {task_id} not found"})
    if task["status"] != "running":
        return json.dumps(
            {
                "error": f"Task {task_id} is not running (status: {task['status']})"
            }
        )
    task["status"] = "cancelling"
    return json.dumps({"task_id": task_id, "status": "cancelling"})


async def _run_ingestion(
    task_id: str,
    pdf_directory: str,
    collection_name: str,
    chunk_size: int,
    chunk_overlap: int,
    batch_size: int,
    resume: bool,
    embedder: Embedder,
    db: VectorStore,
) -> None:
    task = tasks[task_id]

    try:
        pdf_files = await asyncio.to_thread(scan_pdfs, pdf_directory)
    except Exception as e:
        task["status"] = "failed"
        task["errors"].append(f"scan: {e}")
        return

    if not pdf_files:
        task["status"] = "completed"
        task["total_files"] = 0
        return

    task["total_files"] = len(pdf_files)

    try:
        await db.ensure_table()
    except Exception as e:
        task["status"] = "failed"
        task["errors"].append(f"table: {e}")
        return

    pending_texts: list[str] = []
    pending_metadata: list[dict] = []

    for pdf_path in pdf_files:
        if task["status"] == "cancelling":
            task["status"] = "cancelled"
            return

        task["current_file"] = pdf_path

        try:
            text = extract_text(pdf_path)
            chunks = chunk_text(text, chunk_size, chunk_overlap)
            file_hash = compute_file_hash(pdf_path)

            if not chunks:
                task["skipped_files"] += 1
                continue

            for i, chunk in enumerate(chunks):
                if resume:
                    exists = await db.chunk_exists(
                        collection_name, file_hash, i
                    )
                    if exists:
                        task["skipped_chunks"] += 1
                        continue

                pending_texts.append(chunk)
                pending_metadata.append(
                    {
                        "file_hash": file_hash,
                        "file_path": pdf_path,
                        "chunk_index": i,
                    }
                )

                if len(pending_texts) >= batch_size:
                    await _flush(
                        embedder, db, collection_name, pending_texts, pending_metadata
                    )
                    task["inserted_chunks"] += len(pending_texts)
                    pending_texts.clear()
                    pending_metadata.clear()

            task["processed_files"] += 1
            task["total_chunks"] += len(chunks)

        except Exception as e:
            task["failed_files"] += 1
            task["errors"].append(f"{pdf_path}: {e}")

    if pending_texts:
        await _flush(
            embedder, db, collection_name, pending_texts, pending_metadata
        )
        task["inserted_chunks"] += len(pending_texts)

    try:
        await db.create_hnsw_index(collection_name)
    except Exception as e:
        task["errors"].append(f"index: {e}")

    task["status"] = (
        "completed" if task["failed_files"] == 0 else "completed_with_errors"
    )


async def _flush(
    embedder: Embedder,
    db: VectorStore,
    collection_name: str,
    texts: list[str],
    metadata: list[dict],
) -> None:
    embeddings = await asyncio.to_thread(embedder.encode, texts)
    await db.insert_batch(collection_name, texts, embeddings, metadata)


if __name__ == "__main__":
    mcp.run()
