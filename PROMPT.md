Build a Customer Support AI Agent Platform with the following specifications. **CRITICAL: Every detail matters — read all constraints before writing any code.**

## Architecture
- FastAPI backend, single-file SPA frontend (no build step), pgvector for vector storage, LangGraph for the agent workflow
- Everything must run in Docker Compose so it's fully reproducible regardless of host OS/Python version

## Constraints (MANDATORY)
1. **No OpenAI API key required** — the app must work fully offline with mock/random responses when no key is set
2. **Python 3.13** — Python 3.14 breaks pydantic-core and asyncpg
3. **`FROM python:3.13-slim`** for the app container
4. **`pgvector/pgvector:pg17`** for the database (includes pgvector extension)
5. **`langgraph` v1.x** — use `InMemorySaver` as checkpointer (NOT PostgresSaver — it requires psycopg v3 and is overkill for dev)
6. **Do NOT use `langgraph-checkpoint-postgres`** — use `InMemorySaver` from `langgraph.checkpoint.memory`
7. **Do NOT use `psycopg` v3** — use `psycopg2-binary` and SQLAlchemy sync for seed scripts, asyncpg for async operations
8. **All `::vector` casts must use string interpolation** (f-strings), NOT `:param::vector` syntax — SQLAlchemy's `text()` cannot handle `:param::vector` correctly with asyncpg
9. **The app must create its own tables automatically** — no separate Alembic migration step. Use SQLAlchemy `Base.metadata.create_all` on startup, or embed table creation SQL in an init script
10. **Single-file frontend** at `/app/static/index.html` — vanilla HTML/CSS/JS, no build step, served by `mount("/static", StaticFiles(...))`

## Database Setup
- The `docker-compose.yml` must include a `db` service with `pgvector/pgvector:pg17` and a healthcheck
- The app container must wait for the DB to be healthy before starting
- The app must run a startup function that calls `CREATE EXTENSION IF NOT EXISTS vector` and creates all tables
- The default database: `support_db`, user: `support_user`, password: `support_pass`

## Project Structure
```
/app
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, startup event creates tables
│   ├── config.py            # pydantic-settings, all fields have safe defaults
│   ├── database.py           # async engine + session factory
│   ├── models/               # SQLAlchemy models:
│   │   ├── ticket.py         #   Ticket, TicketMessage
│   │   └── document.py       #   DocumentSource, DocumentChunk (embedding: vector(1536))
│   ├── schemas/              # Pydantic request/response models
│   ├── api/                  # FastAPI routers
│   ├── services/
│   │   ├── classifier.py     # Ticket classification (mock when no API key)
│   │   ├── rag_service.py    # Hybrid search + RAG response (mock when no API key)
│   │   └── ticket_service.py # CRUD for tickets
│   ├── graph/
│   │   ├── state.py          # TypedDict state
│   │   ├── nodes.py          # LangGraph nodes (use config["configurable"]["db"] pattern)
│   │   └── graph.py          # Compiled graph with InMemorySaver
│   └── core/
│       ├── deps.py           # get_db dependency
│       └── errors.py         # Exception handlers
├── scripts/
│   └── seed.py               # Seeds mock documents + tickets (with mock embeddings)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Mock Mode Requirements
- `classify_ticket()`: when `OPENAI_API_KEY` is not set, use keyword matching (look for "billing", "login", "error", "urgent" etc. in the description to determine category/priority/sentiment)
- `embed_text()`: when no key, return deterministic random vector `[random.random() * 2 - 1 for _ in range(1536)]` seeded by `hash(text)`
- `generate_rag_response()`: when no key, return a template string mentioning the first retrieved chunk's title and first 300 chars
- Seed script must also work in mock mode with the same random embedding approach

## Seed Data
- 3 support documents (Refund Policy, Account Recovery Guide, Billing FAQ) with 3 chunks each
- 8 tickets in various statuses (open, processing, approved, resolved), mix of categories/priorities
- At least 2 tickets marked `requires_escalation: true` (critical priority + negative sentiment)

## Endpoints
- `POST /api/v1/tickets` — create ticket, invoke LangGraph (classify → retrieve → analyze → check_escalation → generate_response → resolve). On escalation, interrupt for human review
- `GET /api/v1/tickets` — list all
- `GET /api/v1/tickets/{id}` — get one
- `POST /api/v1/tickets/{id}/approve` — approve/reject with optional edited response
- `POST /api/v1/chat` — RAG chat over support docs
- `POST /api/v1/documents/upload` — upload support doc
- `GET /health` — health check
- `GET /ready` — readiness check
- Frontend at `/` serves `index.html`

## LangGraph Flow
```
START → classify → retrieve → analyze → check_escalation
                                              │
                                     ┌────────┴────────┐
                                     ▼                 ▼
                               human_review    generate_response
                                     │                 │
                                     └──────┬──────────┘
                                            ▼
                                         resolve → END
```

## Key Code Patterns to Follow
- Node functions: `async def my_node(state: SupportState, config: RunnableConfig) -> dict:` — extract `db` from `config["configurable"]["db"]`
- Hybrid search: embed query, then `1 - (dc.embedding <=> '{embedding_str}'::vector)` (use f-string, NOT parameterized `:vec::vector`)
- Config defaults: `openai_api_key = ""`, `openai_model = "gpt-4o-mini"`, `embedding_model = "text-embedding-3-small"` — all with safe defaults
- DB URL: `postgresql+asyncpg://support_user:support_pass@db:5432/support_db`

## Docker Setup
- `Dockerfile`: multi-stage, `python:3.13-slim`, install deps, copy app, expose 8000
- `docker-compose.yml`: app + db services, depends_on with condition, env vars, volume for pgvector data
- Entrypoint script that waits for db, runs `python -c "from app.database import engine; ..."` to create extensions and tables, then starts uvicorn

Now build the entire project with all files. Make it run with just `docker compose up --build`.
