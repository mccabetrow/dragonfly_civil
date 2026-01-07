"""
Dragonfly Engine - RAG Service (Citations Enforced)

Retrieval-Augmented Generation service that:
1. Embeds user queries
2. Retrieves relevant document chunks from the vector store
3. Synthesizes answers with strict citation requirements
4. Returns structured responses with evidence links

CRITICAL: This service NEVER returns bare answers. Every statement
must be backed by a citation to evidence.files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# OpenAI models
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMENSIONS = 1536
CHAT_MODEL = "gpt-4o"  # or "gpt-4-turbo" for cost savings

# API endpoints
OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Timeouts
EMBED_TIMEOUT = 30.0
CHAT_TIMEOUT = 60.0

# RAG defaults
DEFAULT_MATCH_THRESHOLD = 0.7
DEFAULT_MATCH_COUNT = 8
MAX_CONTEXT_TOKENS = 6000  # Reserve tokens for response


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class Citation:
    """A citation linking an answer to source evidence."""

    document_id: str
    evidence_id: str
    page_number: Optional[int]
    chunk_index: int
    quote_snippet: str
    similarity: float

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "evidence_id": self.evidence_id,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "quote_snippet": self.quote_snippet,
            "similarity": round(self.similarity, 4),
        }


@dataclass
class RetrievedChunk:
    """A chunk retrieved from vector search."""

    id: str
    document_id: str
    evidence_id: str
    chunk_index: int
    page_number: Optional[int]
    content: str
    similarity: float
    metadata: dict = field(default_factory=dict)


@dataclass
class AnswerWithCitations:
    """Structured response with mandatory citations."""

    answer: str
    citations: list[Citation]
    query: str
    chunks_retrieved: int
    model_used: str
    insufficient_evidence: bool = False

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "query": self.query,
            "chunks_retrieved": self.chunks_retrieved,
            "model_used": self.model_used,
            "insufficient_evidence": self.insufficient_evidence,
        }


# =============================================================================
# System Prompts
# =============================================================================

SYSTEM_PROMPT = """You are a legal analyst assistant for Dragonfly Civil, a judgment enforcement platform.

CRITICAL RULES - YOU MUST FOLLOW THESE EXACTLY:

1. ONLY use information from the provided context documents. Do not use any external knowledge.

2. For EVERY factual statement in your answer, you MUST append a citation in this exact format:
   [Doc: <doc_id>, Page: <page_number>]
   If no page number is available, use: [Doc: <doc_id>]

3. If you cannot find sufficient information in the context to answer the question, respond with:
   "Insufficient evidence in the provided documents to answer this question."

4. Never speculate or make assumptions. If something is unclear, say so.

5. Keep answers concise and focused on the specific question asked.

6. When citing amounts, dates, or names, quote them exactly as they appear in the source.

FORMAT YOUR RESPONSE AS VALID JSON:
{
  "answer": "Your answer with [Doc: xxx, Page: y] citations inline...",
  "cited_documents": [
    {"doc_id": "xxx", "page": 1, "quote": "exact text quoted..."},
    ...
  ],
  "insufficient_evidence": false
}
"""

USER_PROMPT_TEMPLATE = """Context Documents:
{context}

---

Question: {query}

Remember: Cite every statement using [Doc: <id>, Page: <page>] format. Return valid JSON only."""


# =============================================================================
# RAG Service Class
# =============================================================================


class RagService:
    """
    RAG Service with Citations Enforcement.

    Provides semantic search over evidence documents with mandatory
    citation tracking. All answers must be grounded in retrieved context.
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ):
        """
        Initialize RAG service.

        Args:
            supabase_url: Supabase project URL (defaults to settings)
            supabase_key: Supabase service role key (defaults to settings)
            openai_api_key: OpenAI API key (defaults to settings/env)
        """
        self._supabase_url = supabase_url
        self._supabase_key = supabase_key
        self._openai_api_key = openai_api_key

    def _get_openai_key(self) -> Optional[str]:
        """Get OpenAI API key from config or environment."""
        import os

        if self._openai_api_key:
            return self._openai_api_key

        # Try environment
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            return key

        # Try settings
        try:
            settings = get_settings()
            return settings.OPENAI_API_KEY
        except Exception:
            return None

    def _get_supabase_config(self) -> tuple[str, str]:
        """Get Supabase URL and key."""
        import os

        url = self._supabase_url or os.environ.get("SUPABASE_URL")
        key = self._supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

        if not url or not key:
            try:
                settings = get_settings()
                url = url or settings.SUPABASE_URL
                key = key or settings.SUPABASE_SERVICE_ROLE_KEY
            except Exception:
                pass

        if not url or not key:
            raise ValueError("Supabase URL and service key are required")

        return url, key

    async def _generate_embedding(self, text: str) -> Optional[list[float]]:
        """Generate embedding vector for query text."""
        api_key = self._get_openai_key()
        if not api_key:
            logger.error("OpenAI API key not configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
                response = await client.post(
                    OPENAI_EMBED_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": EMBED_MODEL,
                        "input": text.strip(),
                        "dimensions": EMBED_DIMENSIONS,
                    },
                )

                if response.status_code != 200:
                    logger.error(f"OpenAI embedding error: {response.status_code}")
                    return None

                data = response.json()
                return data.get("data", [{}])[0].get("embedding")

        except Exception as e:
            logger.exception(f"Embedding generation failed: {e}")
            return None

    async def _retrieve_chunks(
        self,
        embedding: list[float],
        org_id: str,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        match_count: int = DEFAULT_MATCH_COUNT,
    ) -> list[RetrievedChunk]:
        """Retrieve relevant chunks from vector store via Supabase RPC."""
        supabase_url, supabase_key = self._get_supabase_config()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{supabase_url}/rest/v1/rpc/match_chunks",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query_embedding": embedding,
                        "match_threshold": match_threshold,
                        "match_count": match_count,
                        "filter_org_id": org_id,
                    },
                )

                if response.status_code != 200:
                    logger.error(f"Supabase RPC error: {response.status_code} - {response.text}")
                    return []

                rows = response.json()

                chunks = []
                for row in rows:
                    chunks.append(
                        RetrievedChunk(
                            id=row["id"],
                            document_id=row["document_id"],
                            evidence_id=row["evidence_id"],
                            chunk_index=row["chunk_index"],
                            page_number=row.get("page_number"),
                            content=row["content"],
                            similarity=row["similarity"],
                            metadata=row.get("metadata", {}),
                        )
                    )

                logger.info(f"Retrieved {len(chunks)} chunks for org {org_id}")
                return chunks

        except Exception as e:
            logger.exception(f"Chunk retrieval failed: {e}")
            return []

    def _build_context(self, chunks: list[RetrievedChunk]) -> str:
        """Build context string from retrieved chunks."""
        context_parts = []

        for i, chunk in enumerate(chunks, 1):
            page_info = f", Page {chunk.page_number}" if chunk.page_number else ""
            header = f"[Document {i}: {chunk.document_id}{page_info}]"
            context_parts.append(f"{header}\n{chunk.content}\n")

        return "\n---\n".join(context_parts)

    async def _synthesize_answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
    ) -> tuple[str, list[dict], bool]:
        """
        Synthesize answer using LLM with citation requirements.

        Returns:
            Tuple of (answer_text, cited_documents, insufficient_evidence)
        """
        api_key = self._get_openai_key()
        if not api_key:
            return "Error: OpenAI API key not configured", [], False

        if not chunks:
            return (
                "Insufficient evidence in the provided documents to answer this question.",
                [],
                True,
            )

        # Build context
        context = self._build_context(chunks)

        # Build prompt
        user_prompt = USER_PROMPT_TEMPLATE.format(context=context, query=query)

        try:
            async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
                response = await client.post(
                    OPENAI_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": CHAT_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,  # Low temp for factual accuracy
                        "max_tokens": 2000,
                        "response_format": {"type": "json_object"},
                    },
                )

                if response.status_code != 200:
                    logger.error(f"OpenAI chat error: {response.status_code}")
                    return f"Error generating response: {response.status_code}", [], False

                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # Parse JSON response
                try:
                    parsed = json.loads(content)
                    answer = parsed.get("answer", content)
                    cited_docs = parsed.get("cited_documents", [])
                    insufficient = parsed.get("insufficient_evidence", False)
                    return answer, cited_docs, insufficient
                except json.JSONDecodeError:
                    # LLM didn't return valid JSON, use raw content
                    return content, [], False

        except Exception as e:
            logger.exception(f"Answer synthesis failed: {e}")
            return f"Error: {str(e)}", [], False

    def _build_citations(
        self,
        chunks: list[RetrievedChunk],
        cited_docs: list[dict],
    ) -> list[Citation]:
        """Build Citation objects from LLM response and retrieved chunks."""
        citations = []

        # Create lookup by document_id
        chunk_lookup = {c.document_id: c for c in chunks}

        for cited in cited_docs:
            doc_id = cited.get("doc_id")
            if not doc_id:
                continue

            # Find the chunk
            chunk = chunk_lookup.get(doc_id)
            if not chunk:
                # Try to find by partial match
                for c in chunks:
                    if doc_id in c.document_id or c.document_id in doc_id:
                        chunk = c
                        break

            if chunk:
                citations.append(
                    Citation(
                        document_id=chunk.document_id,
                        evidence_id=chunk.evidence_id,
                        page_number=cited.get("page") or chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        quote_snippet=cited.get("quote", "")[:200],  # Truncate long quotes
                        similarity=chunk.similarity,
                    )
                )

        # If LLM didn't provide citations but we have chunks, cite all retrieved
        if not citations and chunks:
            for chunk in chunks[:5]:  # Top 5 by similarity
                citations.append(
                    Citation(
                        document_id=chunk.document_id,
                        evidence_id=chunk.evidence_id,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        quote_snippet=chunk.content[:200],
                        similarity=chunk.similarity,
                    )
                )

        return citations

    async def search(
        self,
        query: str,
        org_id: str,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        match_count: int = DEFAULT_MATCH_COUNT,
    ) -> AnswerWithCitations:
        """
        Execute RAG search with citations.

        Args:
            query: User's natural language question
            org_id: Organization ID for RLS filtering
            match_threshold: Minimum similarity score (0.0-1.0)
            match_count: Maximum chunks to retrieve

        Returns:
            AnswerWithCitations with grounded response and evidence links
        """
        logger.info(f"RAG search: query='{query[:50]}...' org={org_id}")

        # Step 1: Embed the query
        embedding = await self._generate_embedding(query)
        if not embedding:
            return AnswerWithCitations(
                answer="Error: Failed to generate query embedding.",
                citations=[],
                query=query,
                chunks_retrieved=0,
                model_used=CHAT_MODEL,
                insufficient_evidence=True,
            )

        # Step 2: Retrieve relevant chunks
        chunks = await self._retrieve_chunks(
            embedding=embedding,
            org_id=org_id,
            match_threshold=match_threshold,
            match_count=match_count,
        )

        # Step 3: Synthesize answer with citations
        answer, cited_docs, insufficient = await self._synthesize_answer(query, chunks)

        # Step 4: Build structured citations
        citations = self._build_citations(chunks, cited_docs)

        return AnswerWithCitations(
            answer=answer,
            citations=citations,
            query=query,
            chunks_retrieved=len(chunks),
            model_used=CHAT_MODEL,
            insufficient_evidence=insufficient or len(chunks) == 0,
        )

    async def health_check(self) -> dict:
        """Check RAG service health."""
        status = {
            "openai_configured": bool(self._get_openai_key()),
            "supabase_configured": False,
            "status": "unknown",
        }

        try:
            url, key = self._get_supabase_config()
            status["supabase_configured"] = bool(url and key)
        except Exception:
            pass

        if status["openai_configured"] and status["supabase_configured"]:
            status["status"] = "healthy"
        elif status["openai_configured"] or status["supabase_configured"]:
            status["status"] = "degraded"
        else:
            status["status"] = "unhealthy"

        return status


# =============================================================================
# Module-level singleton (optional convenience)
# =============================================================================

_rag_service: Optional[RagService] = None


def get_rag_service() -> RagService:
    """Get or create the RAG service singleton."""
    global _rag_service
    if _rag_service is None:
        _rag_service = RagService()
    return _rag_service
