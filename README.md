<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green.svg">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-1.28.1-purple.svg">
  <img alt="pgvector" src="https://img.shields.io/badge/pgvector-0.8+-orange.svg">
  <img alt="Status" src="https://img.shields.io/badge/status-production%20ready-brightgreen.svg">
</p>

<h1 align="center">PDF to Vector MCP Server</h1>

<p align="center">
  An MCP server that ingests PDF documents into pgvector for semantic search and RAG pipelines.
  <br>
  The ingestion half of a production RAG system — extract, chunk, embed, and store.
</p>

<hr>

## Problem

Large language models have no direct access to documents, PDFs, or private knowledge bases. Building a RAG pipeline requires stitching together PDF parsing, text chunking, embedding generation, and vector database operations — a fragile, multi-step process that every agent project reinvents.

This MCP server collapses that pipeline into a single agent-callable tool: point it at a directory of PDFs, and it handles extraction, chunking, embedding (nomic-embed-text-v2-moe, 768-dim), and storage in pgvector — ready for semantic search.

## Features

- **Single `uv run` or `pip install`** — no project scaffolding, no boilerplate.
- **Local embeddings** — nomic-embed-text-v2-moe runs on CPU via sentence-transformers, no API keys or network calls.
- **Background ingestion** — `index_pdfs_for_rag` returns immediately; poll `check_indexing_progress` for updates.
- **Idempotent resume** — re-running indexes only new/changed files (SHA-256 content hash).
- **Per-file error isolation** — one corrupt PDF never blocks the batch.
- **Auto HNSW index** — pgvector index created after ingestion for sub-10ms similarity search.
- **Production stable** — uses `mcp==1.28.1` (stable SDK), no pre-releases.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│  Agent (OpenCode, Claude Desktop, etc.)                    │
│  calls index_pdfs_for_rag(pdf_directory, collection_name)  │
└─────────────────────┬──────────────────────────────────────┘
                      │ JSON-RPC (stdio)
┌─────────────────────▼──────────────────────────────────────┐
│  server.py — MCP Server (FastMCP v1)                       │
│                                                             │
│  1. Scan PDF directory (recursive glob)                     │
│  2. Compute SHA-256 hash of each file                       │
│  3. Extract text (PyMuPDF)                                  │
│  4. Recursive character chunking (1000/200 default)         │
│  5. Batch embed (nomic-embed-text-v2-moe, 768-dim)          │
│  6. Batch insert into pgvector (ON CONFLICT DO NOTHING)     │
│  7. Create HNSW index on completion                         │
└─────────────────────┬──────────────────────────────────────┘
                      │ asyncpg
┌─────────────────────▼──────────────────────────────────────┐
│  PostgreSQL + pgvector                                      │
│                                                             │
│  documents (                                                │
│    collection_name TEXT,     ← namespace for multi-tenant   │
│    file_hash TEXT,           ← SHA-256 for resume/dedup     │
│    file_path TEXT,           ← original source              │
│    chunk_index INT,          ← position within file         │
│    content TEXT,             ← chunk text                   │
│    embedding vector(768),    ← nomic embedding              │
│    metadata JSONB,           ← extensible                   │
│    UNIQUE(collection_name, file_hash, chunk_index)          │
│  )                                                          │
└────────────────────────────────────────────────────────────┘
```

## Quick Start — Agent (OpenCode)

Add to your `opencode.json` or `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "pdf-to-vector": {
      "type": "local",
      "command": ["/path/to/pdf-to-vector-mcp/.venv/bin/python", "server.py"],
      "enabled": true
    }
  }
}
```

Once configured, the agent can call:

```
index_pdfs_for_rag(
  pdf_directory="/path/to/pdfs",
  collection_name="company-policies"
)
```

Then poll progress:

```
check_indexing_progress(task_id="...")
```

## Quick Start — Local Testing

### Prerequisites

- Python 3.10+
- PostgreSQL 15+ with [pgvector](https://github.com/pgvector/pgvector) extension

### Setup

```bash
# Clone and enter
git clone <url>
cd pdf-to-vector-mcp

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure pgvector connection
cp .env.example .env
# Edit .env with your pgvector credentials

# Start the server (listens on stdio)
python server.py
```

### Test with MCP Inspector

```bash
source .venv/bin/activate
mcp dev server.py
```

Opens a browser UI where you can call `index_pdfs_for_rag` with a PDF directory path and collection name, then monitor progress with `check_indexing_progress`.

## Configuration

All configuration is via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PGVECTOR_HOST` | `localhost` | PostgreSQL host |
| `PGVECTOR_PORT` | `5432` | PostgreSQL port |
| `PGVECTOR_DATABASE` | `vectordb` | Database name |
| `PGVECTOR_USER` | `postgres` | Database user |
| `PGVECTOR_PASSWORD` | `""` | Database password |

No API keys, no model configuration. Embeddings run entirely locally.

## Tools

| Tool | When to use |
|------|-------------|
| `index_pdfs_for_rag` | User wants PDFs searchable via natural language (knowledge base, RAG, Q&A). Starts background ingestion, returns `task_id`. |
| `check_indexing_progress` | After `index_pdfs_for_rag`, to monitor completion or when user asks "is it done yet?" |
| `cancel_pdf_indexing` | User wants to stop a running ingestion, or a task is stuck. |

## Schema

```sql
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    collection_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_path TEXT NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(collection_name, file_hash, chunk_index)
);

CREATE INDEX idx_documents_collection ON documents (collection_name);

-- Auto-created after ingestion:
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200)
    WHERE collection_name = ?;
```

## Production Considerations

- **Embedding model** (~1.9GB) is downloaded on first run to `~/.cache/huggingface/hub/`. Subsequent runs use the cached copy.
- **First load** takes 10–30 seconds (model download + torch import). Lifespan handler pre-loads at startup.
- **Memory**: ~2GB RSS during ingestion (model + torch). Returns to ~200MB after ingestion completes.
- **PostgreSQL**: Ensure `max_connections` is sufficient. The server uses a connection pool (min: 2, max: 8).
- **Retrieval**: Add a `search_indexed_content` tool to query the indexed data — the schema and HNSW index are ready for it.

## License

MIT
