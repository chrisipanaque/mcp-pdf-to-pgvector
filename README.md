# Customer Support AI Agent Platform

Automated ticket triage using LLMs, RAG over support docs, and a LangGraph-powered agent workflow with human-in-the-loop escalation.

## Features

- **Ticket Classification** — GPT-4o-mini structured output → category, priority, sentiment, confidence
- **Sentiment Analysis** — Built into classification, flags negative + critical tickets
- **RAG over Support Docs** — pgvector hybrid search (0.7 vector cosine + 0.3 BM25) with HNSW indexing
- **LangGraph Agent** — 7-node state machine with conditional escalation
- **Human-in-the-Loop** — `interrupt()` pauses workflow for manual approval/editing
- **Ready for External Systems** — Webhook-friendly for Salesforce, Zendesk, Intercom, HubSpot

## Tech Stack

```
FastAPI + SQLAlchemy (async) → PostgreSQL + pgvector → OpenAI (GPT-4o-mini + text-embedding-3-small) → LangGraph → Docker → Kubernetes
```

## LangGraph Workflow

```
                      ┌──────────────────────────┐
                      │         START            │
                      └───────────┬──────────────┘
                                  │
                      ┌───────────▼──────────────┐
                      │     classify_node        │
                      │  OpenAI structured output │
                      │  → category, priority,   │
                      │    sentiment, confidence  │
                      └───────────┬──────────────┘
                                  │
                      ┌───────────▼──────────────┐
                      │     retrieve_node         │
                      │  pgvector hybrid_search   │
                      │  (0.7 vec + 0.3 BM25)     │
                      │  → top_k=8 docs           │
                      └───────────┬──────────────┘
                                  │
                      ┌───────────▼──────────────┐
                      │     analyze_node          │
                      │  Check if docs match      │
                      │  → has_relevant_docs      │
                      └───────────┬──────────────┘
                                  │
                      ┌───────────▼──────────────┐
                      │  check_escalation_node    │
                      │  Rules:                  │
                      │  • sentiment=negative     │
                      │    AND priority=critical  │
                      │  • confidence < 0.5       │
                      └───────────┬──────────────┘
                                  │
                     ┌────────────┴────────────┐
                     ↓                         ↓
          ┌─────────────────────┐   ┌──────────────────────┐
          │  human_review_node  │   │ generate_response_node│
          │  interrupt()        │   │  RAG context + LLM    │
          │  pause for human    │   │  → draft_response     │
          │  approval           │   │    with citations     │
          └─────────┬───────────┘   └──────────┬───────────┘
                     └────────┬────────────────┘
                              ↓
                    ┌────────────────────┐
                    │    resolve_node    │
                    │  → final response  │
                    │  → status=resolved │
                    └────────┬───────────┘
                             ↓
                           END
```

**State fields**: `messages`, `ticket_id`, `customer_id`, `description`, `category`, `priority`, `sentiment`, `confidence`, `summary`, `retrieved_docs`, `draft_response`, `requires_escalation`, `human_approved`, `human_edited_response`, `error`

## Quick Start

### Prerequisites

- Python 3.12+
- Docker (for PostgreSQL + pgvector)
- OpenAI API key

### Setup

```bash
git clone <repo> && cd customer-support-ai-agent
cp .env.example .env
```

Edit `.env` and set your `OPENAI_API_KEY`.

### Step 1: Start the database

```bash
docker compose up -d db
```

PostgreSQL with pgvector starts in the background on port 5432.

### Step 2: Seed demo data

```bash
pip install -r requirements.txt
python scripts/seed.py
```

Creates 3 support documents with embedded chunks and 8 mock tickets in various states (resolved, escalated, processing, approved). Run with `--clear` to reset.

### Step 3: Start the backend

```bash
uvicorn app.main:app --reload
```

FastAPI starts on `http://localhost:8000`.

### Step 4: Open the frontend

Open **http://localhost:8000** in your browser. The SPA provides:

| Page | Route | What you can do |
|---|---|---|
| **New Ticket** | `#create` | Fill out the form and submit — triggers the LangGraph agent |
| **Tickets** | `#tickets` | Browse all tickets, click to see details |
| **Ticket Detail** | `#ticket/{id}` | View classification, sentiment, draft response. If escalated: approve/reject with edits |
| **Chat** | `#chat` | Ask questions — agent searches the knowledge base and responds |
| **Upload** | `#upload` | Upload support documents for RAG |

### Or use Docker Compose (all-in-one)

```bash
docker compose up
```

This starts PostgreSQL + the API with hot-reload. Then seed data in another terminal:

```bash
python scripts/seed.py
```

### Verify

```bash
curl http://localhost:8000/health
# {"status":"healthy"}
```

## API Reference

### Health

```bash
curl http://localhost:8000/health
# {"status":"healthy"}

curl http://localhost:8000/ready
# {"status":"ready"}
```

### Tickets

```bash
# Create a ticket (triggers LangGraph agent)
curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "cust-456",
    "subject": "Billing overcharge",
    "description": "I was charged $299 instead of $99 for my monthly plan. This is the second time this has happened."
  }'
# Response: 201
# {
#   "id": "abc-123...",
#   "customer_id": "cust-456",
#   "status": "processing",
#   "category": "billing",
#   "priority": "high",
#   "sentiment": "negative",
#   "summary": "Customer was overcharged $299 instead of $99 for monthly plan"
# }

# Get ticket details and status
curl http://localhost:8000/api/v1/tickets/abc-123...
# {
#   "id": "abc-123...",
#   "customer_id": "cust-456",
#   "category": "billing",
#   "priority": "high",
#   "sentiment": "negative",
#   "confidence": 0.95,
#   "summary": "Customer was overcharged...",
#   "status": "processing",
#   "draft_response": "I see the overcharge...",
#   "requires_escalation": true,
#   "created_at": "2026-05-30T...",
#   ...
# }

# Approve a draft response
curl -X POST http://localhost:8000/api/v1/tickets/abc-123.../approve \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'
# Response: 200 → status becomes "approved"

# Approve with manual edits
curl -X POST http://localhost:8000/api/v1/tickets/abc-123.../approve \
  -H "Content-Type: application/json" \
  -d '{
    "approved": true,
    "edited_response": "Hi, I see the overcharge. I have issued a $200 refund. It will appear in 3-5 business days."
  }'

# Reject a draft (send back to queue)
curl -X POST http://localhost:8000/api/v1/tickets/abc-123.../approve \
  -H "Content-Type: application/json" \
  -d '{"approved": false}'
# Response: 200 → status becomes "rejected"
```

### Documents (RAG Ingestion)

```bash
# Upload a support document (auto-chunked and embedded via pgvector)
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@refund-policy.txt"
# Response: 201
# {"id": "doc-456...", "title": "refund-policy.txt", "size": 2341}

# Upload multiple doc types (plain text, markdown, etc.)
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@getting-started.md"

curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@faq.txt"

# List all ingested documents
curl http://localhost:8000/api/v1/documents
# Response: 200
# [
#   {"id": "doc-456...", "title": "refund-policy.txt", "source_type": "upload", "created_at": "..."},
#   {"id": "doc-789...", "title": "getting-started.md", "source_type": "upload", "created_at": "..."}
# ]
```

### Chat (Ad-hoc Agent Query)

```bash
# Send a message to the agent (runs same LangGraph workflow)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "abc-123...",
    "message": "What is your refund policy for annual plans?"
  }'
# Response: 200
# {"ticket_id": "abc-123...", "response": "Our refund policy for annual plans allows..."}
```

## Database Schema

```
document_sources        document_chunks           tickets
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ id (UUID)       │←───│ source_id (FK)   │    │ id (UUID)        │
│ title           │    │ chunk_index      │    │ customer_id      │
│ source_type     │    │ content          │    │ subject          │
│ url             │    │ heading          │    │ description      │
│ metadata (JSONB)│    │ embedding(VECTOR)│    │ category         │
│ created_at      │    │ metadata (JSONB) │    │ priority         │
└─────────────────┘    │ created_at       │    │ sentiment        │
                       └──────────────────┘    │ status           │
                                                │ draft_response   │
                        ticket_messages         │ requires_escalate│
                        ┌──────────────────┐    │ created_at       │
                        │ id (UUID)        │    └──────────────────┘
                        │ ticket_id (FK)   │
                        │ role             │
                        │ content          │
                        │ created_at       │
                        └──────────────────┘
```

### Key Indexes

- `HNSW` on `document_chunks.embedding` with `vector_cosine_ops` (fast approximate nearest neighbor)
- `GIN` on `document_chunks.metadata` (JSONB filtered search)
- `GIN` on `to_tsvector('english', content)` (BM25 full-text fallback)

## Project Structure

```
customer-support-ai-agent/
├── app/
│   ├── main.py                # FastAPI app, lifespan, health/ready endpoints
│   ├── config.py              # pydantic-settings (env-based)
│   ├── database.py            # Async SQLAlchemy engine + session factory
│   │
│   ├── api/
│   │   ├── router.py          # Root APIRouter with prefixes
│   │   ├── tickets.py         # POST/GET tickets + approve
│   │   ├── chat.py            # Agent chat endpoint
│   │   └── ingestion.py       # Document upload + list
│   │
│   ├── models/
│   │   ├── ticket.py          # Ticket, TicketMessage ORM models
│   │   └── document.py        # DocumentSource, DocumentChunk with Vector type
│   │
│   ├── schemas/
│   │   ├── ticket.py          # TicketCreate, TicketResponse, TicketApprove
│   │   ├── chat.py            # ChatRequest, ChatResponse
│   │   └── document.py        # DocumentResponse
│   │
│   ├── services/
│   │   ├── classifier.py      # OpenAI structured output classification
│   │   ├── rag_service.py     # embed_text, hybrid_search, generate_rag_response
│   │   └── ticket_service.py  # Ticket CRUD business logic
│   │
│   ├── graph/
│   │   ├── state.py           # SupportState TypedDict with LangGraph reducers
│   │   ├── nodes.py           # 7 node functions
│   │   └── graph.py           # Compiled StateGraph with PostgresSaver
│   │
│   └── core/
│       ├── deps.py            # Dependency injection (get_db)
│       └── errors.py          # Exception handlers
│
├── alembic/                   # Database migrations
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── k8s/                       # Kubernetes manifests
│   ├── namespace.yaml
│   ├── secrets.yaml
│   ├── db-statefulset.yaml    # PostgreSQL StatefulSet + 20Gi PVC
│   └── api-deployment.yaml    # 3-replica Deployment + HPA (2-10 pods)
│
├── tests/
│   ├── conftest.py            # Async test fixtures with test DB
│   ├── test_api/
│   │   └── test_tickets.py    # Health, CRUD, edge cases
│   └── test_graph/
│       └── test_graph.py      # State defaults, escalation logic
│
├── Dockerfile                 # Multi-stage build
├── docker-compose.yml         # pgvector + FastAPI with hot-reload
├── requirements.txt
└── .env.example
```

## Kubernetes Deployment

```bash
# 1. Edit secrets with your real credentials
vim k8s/secrets.yaml

# 2. Apply manifests
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/db-statefulset.yaml

# 3. Build and push API image
docker build -t support-agent-api:latest .
# Push to your registry, then update api-deployment.yaml image

kubectl apply -f k8s/api-deployment.yaml

# 4. Verify
kubectl get pods -n customer-support-ai
kubectl get hpa -n customer-support-ai
kubectl logs -n customer-support-ai deployment/api
```

## Recommendations for Production

| Area | Recommendation | Why |
|---|---|---|
| **Monitoring** | Add Prometheus metrics + structured logging (structlog) | Track latency per node, token consumption, escalation rate |
| **Caching** | Redis for embedding cache + rate limiting | Avoid re-embedding identical queries, prevent abuse |
| **Embeddings** | Upgrade to `text-embedding-3-large` (3072 dim) | Higher retrieval accuracy for complex queries |
| **Chunking** | `RecursiveCharacterTextSplitter` (800/150) with heading-aware boundaries | Better semantic chunks than fixed token counts |
| **Connection Pooling** | Deploy PgBouncer as sidecar or separate Deployment | Essential beyond ~50 concurrent connections |
| **Authentication** | API key middleware on all endpoints | Prevent unauthorized access |
| **Webhooks** | POST resolution + draft to Salesforce / Zendesk / Intercom / HubSpot | Close the loop with existing support tools |
| **CI/CD** | GitHub Actions: ruff lint → pytest → build → deploy to K8s | Catch regressions before deployment |
| **Ingress** | TLS termination + rate limiting + WAF | Production security baseline |
| **Human Review** | Slack / MS Teams bot for approval notifications | Faster response times for escalated tickets |
| **LLM Caching** | Cache identical classification results (TTL=1h) | Reduce OpenAI costs on duplicate submissions |
| **A/B Testing** | Compare gpt-4o-mini vs gpt-4o on classification accuracy | Measure cost/accuracy tradeoff empirically |
| **Hybrid Search Tuning** | Tune `0.7 vec + 0.3 txt` weights per domain | Optimal for different knowledge base types |
| **Ticket Routing** | Route classified tickets to specific agent queues by category | Technical → tier-2, Billing → finance team |

## Development

```bash
# Run tests (requires PostgreSQL with pgvector running)
pytest tests/ -v

# Run linter
ruff check app/

# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```
