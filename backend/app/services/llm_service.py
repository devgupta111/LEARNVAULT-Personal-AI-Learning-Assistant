"""
services/llm_service.py

LLM client for grounded RAG generation.

Day 4 uses RAG_API_KEY + RAG_MODEL from config (Groq API).
Day 4 does NOT stream — generate_rag_response() returns the complete answer.

Streaming (SSE) is intentionally deferred to Day 7.

Responsibilities:
  - Non-streaming grounded RAG generation using retrieved parent context.
  - Strict grounding prompt: answer only from context, cite sources, refuse if
    evidence is insufficient.
  - Unified refusal message constant (used both here and in chat.py).
  - Citation metadata extraction from parent result payloads.

Design notes:
  - All API errors are raised as RuntimeError so the caller (chat endpoint)
    can catch them cleanly and return a proper HTTP error.
  - Parent texts are truncated if the total context exceeds MAX_CONTEXT_CHARS
    to avoid exceeding model context windows.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ─── Unified refusal message (matches brain.md spec) ──────────────────────────
REFUSAL_MESSAGE = (
    "I couldn't find sufficient information in your uploaded documents "
    "to answer that question."
)

# ─── Context window limit ──────────────────────────────────────────────────────
MAX_CONTEXT_CHARS = 12_000   # Truncate parent_text if total context is very large


def _get_generation_client():
    """
    Return (client, model_name) for LLM generation using RAG_API_KEY.

    Uses the Groq SDK. RAG_API_KEY must be set in .env.

    Raises:
        RuntimeError: If RAG_API_KEY is not configured.
    """
    from app.config import settings

    api_key = settings.RAG_API_KEY
    if not api_key:
        raise RuntimeError(
            "RAG_API_KEY is not configured. "
            "Set RAG_API_KEY=<your-groq-api-key> in your .env file."
        )

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except ImportError as exc:
        raise RuntimeError(
            "The 'groq' package is required. Install it with: pip install groq"
        ) from exc

    model = settings.RAG_MODEL
    logger.debug("LLM: using model=%s with RAG_API_KEY", model)
    return client, model


# ─── Prompt builders ───────────────────────────────────────────────────────────

def _build_rag_system_prompt() -> str:
    """
    Build the strict grounded-generation system prompt.

    Rules enforced:
      1. Answer ONLY from the provided context — no outside knowledge.
      2. If context is insufficient, use the exact refusal string.
      3. Cite every factual claim using [Source N] notation.
      4. Do not fabricate page numbers, source IDs, or facts.
      5. Keep the answer relevant and concise.
    """
    return (
        "You are a precise academic study assistant. "
        "Your job is to answer the student's question using ONLY the context "
        "provided below. Do not use any outside knowledge.\n\n"
        "Rules:\n"
        "1. Answer only from the provided context — do not invent facts or "
        "use knowledge from outside the context.\n"
        "2. If the context does not contain enough information to answer the "
        "question, respond EXACTLY with this sentence and nothing else:\n"
        f'   "{REFUSAL_MESSAGE}"\n'
        "3. Cite every factual statement using [Source N] notation, "
        "where N is the source number shown in the context header. "
        "Do not fabricate source IDs or page numbers.\n"
        "4. Do not cite a source that does not support your statement.\n"
        "5. Be concise, clear, and accurate.\n"
        "6. Do not hallucinate or invent information."
    )


def _format_context_block(parent_results: List[Dict]) -> str:
    """
    Format retrieved parent contexts into the numbered source block
    that the grounded generation prompt expects.

    Example output:
        [Source 1 | Page 4-5]
        ...text...

        [Source 2 | Page 12]
        ...text...
    """
    blocks = []
    total_chars = 0
    for i, ctx in enumerate(parent_results, start=1):
        page_start = ctx.get("page_start", "?")
        page_end = ctx.get("page_end", "?")
        if page_start == page_end:
            page_label = f"Page {page_start}"
        else:
            page_label = f"Page {page_start}-{page_end}"
        text = ctx.get("parent_text", ctx.get("text", ""))
        # Truncate very long parent texts to stay within context budget
        remaining = MAX_CONTEXT_CHARS - total_chars
        if remaining <= 0:
            break
        text = text[:remaining]
        total_chars += len(text)
        blocks.append(f"[Source {i} | {page_label}]\n{text}")
    return "\n\n".join(blocks)


def _build_messages_for_rag(
    query: str,
    parent_results: List[Dict],
    history: List[Dict],
) -> List[Dict]:
    """Build the full messages list for a grounded RAG request."""
    context_block = _format_context_block(parent_results)
    system_msg = _build_rag_system_prompt()
    full_system = (
        f"{system_msg}\n\n--- CONTEXT ---\n{context_block}\n--- END CONTEXT ---"
    )

    messages = [{"role": "system", "content": full_system}]
    # Add recent chat history (already chronological from caller)
    for turn in history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": query})
    return messages


# ─── Public API ────────────────────────────────────────────────────────────────

def generate_rag_response(
    query: str,
    parent_results: List[Dict],
    history: Optional[List[Dict]] = None,
) -> str:
    """
    Non-streaming grounded generation using retrieved parent context.

    The complete answer is generated and returned as a string.
    Day 4 does NOT stream. Streaming is deferred to Day 7 (SSE).

    Args:
        query:          The user's message (used directly — no router/rewriting on Day 4).
        parent_results: Deduplicated parent context chunks from reranker.
        history:        Recent chat history (chronological, role/content dicts).
                        Typically the last 3-4 messages.

    Returns:
        Complete response string from the LLM.

    Raises:
        RuntimeError: On LLM API failure (caller maps to HTTP 503).
    """
    client, model = _get_generation_client()
    messages = _build_messages_for_rag(query, parent_results, history or [])
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=1024,
            stream=False,
        )
        answer = response.choices[0].message.content
        return answer or REFUSAL_MESSAGE
    except Exception as exc:
        logger.error("LLM generation failed: %s", exc)
        raise RuntimeError(f"LLM generation error: {exc}") from exc


def get_citations(parent_results: List[Dict]) -> List[Dict]:
    """
    Extract citation metadata from parent results.

    Returns a list of citation dicts, one per unique parent context.
    Each dict includes source_id, document_id, page_start, page_end,
    parent_chunk_id, and subject.

    The source_id matches the [Source N] notation used in the answer.
    """
    citations = []
    for i, ctx in enumerate(parent_results, start=1):
        citations.append(
            {
                "source_id": f"Source {i}",
                "document_id": ctx.get("document_id", ""),
                "page_start": ctx.get("page_start"),
                "page_end": ctx.get("page_end"),
                "parent_chunk_id": ctx.get("parent_chunk_id", ""),
                "subject": ctx.get("subject", ""),
            }
        )
    return citations


def generate_direct_chat_response(
    query: str,
    history: Optional[List[Dict]] = None,
) -> str:
    """
    Direct conversational LLM response for greetings and non-retrieval chit-chat (Day 5).

    Does NOT perform document retrieval, embedding, or citation tracking.
    Uses the existing LLM provider and credentials (RAG_API_KEY / RAG_MODEL).
    Non-streaming.

    Args:
        query:   The user's conversational message (e.g. "hi", "thank you").
        history: Recent chat history (chronological, role/content dicts).

    Returns:
        Conversational response string.
    """
    client, model = _get_generation_client()
    messages = [
        {
            "role": "system",
            "content": (
                "You are a friendly, helpful AI learning assistant for students. "
                "Respond politely, warmly, and concisely to the student's greeting or comment. "
                "Remind them gently that they can ask questions about their uploaded study material."
            ),
        }
    ]
    for turn in (history or []):
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": query})

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=300,
            stream=False,
        )
        return (
            response.choices[0].message.content
            or "Hello! How can I help you with your studies today?"
        )
    except Exception as exc:
        logger.error("Direct chat LLM generation failed: %s", exc)
        raise RuntimeError(f"Direct chat generation error: {exc}") from exc
