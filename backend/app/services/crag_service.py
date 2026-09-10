"""
services/crag_service.py

Day 5 — CRAG (Corrective Retrieval-Augmented Generation) Agent.

Responsibilities:
  - Triggered ONLY when initial vector retrieval + reranking yields weak evidence
    (i.e. top score < RERANK_THRESHOLD).
  - Generates exactly ONE concise alternative search query using synonyms,
    related terminology, or entity expansion to attempt a second retrieval.
  - Strict query length limit (<= ~60 tokens / under 300 characters).
  - Uses dedicated CRAG_API_KEY and CRAG_MODEL if configured, falling back
    to RAG_API_KEY.
  - Safe fallback: If the model fails, times out, or produces invalid output,
    returns None, signaling the chat pipeline to immediately return the Day-4 refusal.
  - Never attempts multiple retries (exactly one retry allowed in the pipeline).
  - Never answers the user's question directly.
"""

import json
import logging
import re
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.schemas.chat_schemas import CRAGOutput

logger = logging.getLogger(__name__)

CRAG_SYSTEM_PROMPT = """You are a Corrective Retrieval (CRAG) search query reformulation agent.
The user's initial search query yielded weak or insufficient evidence from the document index.
Your ONLY job is to reformulate the query into ONE concise, alternative search query that is more likely to match academic text passages.

TECHNIQUES:
- Use synonyms and standard academic/textbook terminology.
- Expand acronyms or technical concepts.
- Rephrase passive/conversational expressions into core keywords.
- Broaden slightly if the original query was too specific, or focus on key entities.

CONSTRAINTS:
1. Output ONLY valid JSON matching this exact structure:
   {
     "alternative_query": "..."
   }
2. The alternative query must be very concise (maximum 60 tokens, under 25 words).
3. Do NOT answer the user's question.
4. Do NOT include explanations, preambles, or markdown formatting outside the JSON.
5. Preserve the original question's core subject and intent."""


def _get_crag_client() -> Tuple[object, str]:
    """
    Obtain the Groq client and model name for CRAG query reformulation.

    Uses CRAG_API_KEY if configured; otherwise falls back to RAG_API_KEY.
    Uses CRAG_MODEL (default: llama-3.1-8b-instant).

    Raises:
        RuntimeError: If neither CRAG_API_KEY nor RAG_API_KEY is configured.
    """
    api_key = settings.CRAG_API_KEY or settings.RAG_API_KEY
    if not api_key:
        raise RuntimeError(
            "Neither CRAG_API_KEY nor RAG_API_KEY is configured."
        )

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except ImportError as exc:
        raise RuntimeError(
            "The 'groq' package is required. Install it with: pip install groq"
        ) from exc

    model = settings.CRAG_MODEL or "llama-3.1-8b-instant"
    return client, model


def generate_crag_query(
    query: str,
    history: Optional[List[Dict]] = None,
) -> Optional[CRAGOutput]:
    """
    Generate ONE concise alternative search query for a second retrieval attempt.

    Args:
        query:   The current query that yielded weak retrieval.
        history: Recent chat messages (optional context).

    Returns:
        CRAGOutput with the alternative query, or None if CRAG failed.
    """
    cleaned_query = query.strip()
    history = history or []

    messages = [{"role": "system", "content": CRAG_SYSTEM_PROMPT}]

    # Provide brief recent context if available to help identify subject matter
    if history:
        recent_turns = []
        for turn in history[-2:]:  # Limit to last 2 turns to keep prompt focused
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if content:
                recent_turns.append(f"{role.capitalize()}: {content[:100]}")
        if recent_turns:
            messages.append({
                "role": "user",
                "content": "Context:\n" + "\n".join(recent_turns)
            })

    messages.append({
        "role": "user",
        "content": f"Initial query that yielded weak evidence: {cleaned_query}\n\nReformulate as JSON:"
    })

    try:
        client, model = _get_crag_client()
        logger.info(
            "CRAG: Triggered for weak query='%s...'. Calling model=%s",
            cleaned_query[:50],
            model,
        )

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 500,
            "stream": False,
        }
        # Groq rejects response_format={"type": "json_object"} for openai/ models
        if not model.startswith("openai/"):
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)

        raw_content = response.choices[0].message.content or "{}"
        match = re.search(r"\{[^{}]*\}", raw_content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
        else:
            parsed = json.loads(raw_content)

        alt_query = parsed.get("alternative_query", "").strip()

        # Strict validation: cannot be empty or excessively long (> 300 chars)
        if not alt_query or len(alt_query) > 300:
            logger.warning(
                "CRAG: Output failed validation (empty or too long: length=%d). Treating as failed.",
                len(alt_query),
            )
            return None

        result = CRAGOutput(alternative_query=alt_query)
        logger.info("CRAG success: generated alternative query='%s'", result.alternative_query)
        return result

    except Exception as exc:
        logger.warning("CRAG call failed: %s. Safe fallback to refusal.", exc)
        return None
