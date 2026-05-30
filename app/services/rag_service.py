from pydantic import BaseModel
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)


class RAGResponse(BaseModel):
    answer: str
    citations: list[dict]
    confidence: str


def embed_text(text: str) -> list[float]:
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=text,
    )
    return response.data[0].embedding


async def hybrid_search(
    db: AsyncSession,
    query: str,
    top_k: int = 8,
    source_filter: str | None = None,
) -> list[dict]:
    query_embedding = embed_text(query)

    sql = text("""
        WITH vector_results AS (
            SELECT
                dc.id,
                dc.content,
                dc.source_id,
                dc.heading,
                ds.title AS source_title,
                1 - (dc.embedding <=> :vec::vector) AS vector_score,
                ts_rank(
                    to_tsvector('english', dc.content),
                    plainto_tsquery('english', :query)
                ) AS text_score
            FROM document_chunks dc
            JOIN document_sources ds ON ds.id = dc.source_id
            WHERE (:source IS NULL OR ds.id::text = :source)
            ORDER BY vector_score DESC
            LIMIT :top_k * 2
        )
        SELECT id, content, source_id, heading, source_title,
               (0.7 * vector_score + 0.3 * text_score) AS combined_score
        FROM vector_results
        ORDER BY combined_score DESC
        LIMIT :top_k
    """)

    result = await db.execute(
        sql,
        {
            "vec": str(query_embedding),
            "query": query,
            "source": source_filter,
            "top_k": top_k,
        },
    )
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]),
            "content": r[1],
            "source_id": str(r[2]),
            "heading": r[3],
            "source_title": r[4],
            "score": float(r[5]),
        }
        for r in rows
    ]


async def generate_rag_response(
    query: str,
    retrieved_chunks: list[dict],
) -> RAGResponse:
    if not retrieved_chunks:
        return RAGResponse(
            answer="I could not find any relevant information in the support documentation to answer this question.",
            citations=[],
            confidence="low",
        )

    context = "\n\n".join(
        f"[Source: {c['heading'] or c['source_title']}]\n{c['content']}"
        for c in retrieved_chunks
    )

    response = client.beta.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer the question using ONLY the provided context. "
                    "If the context doesn't contain the answer, say so. "
                    "Cite specific sources for each claim."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {query}",
            },
        ],
        response_format=RAGResponse,
        temperature=0.0,
    )
    result = response.choices[0].message.parsed
    if result is None:
        raise ValueError("OpenAI returned null RAG response")
    return result
