"""
services/query_router_service.py

Day 5 — Query Router & Rewriter Agent.

Responsibilities:
  - Single structured LLM call that simultaneously:
      1. Classifies user intent into: direct_chat | rag_query | quiz_mode
      2. Rewrites the query when retrieval is required (rag_query) to resolve
         anaphoras, pronouns, and references against recent chat history.
  - Uses dedicated ROUTER_API_KEY and ROUTER_MODEL if configured, falling back
    gracefully to RAG_API_KEY.
  - Safe fallback: On any LLM failure, timeout, or malformed schema, safely
    defaults to route="rag_query" with rewritten_query=original_user_query.
  - Never logs secrets, API keys, or raw confidential document payloads.
"""

import json
import logging
import re
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.schemas.chat_schemas import RouterOutput

logger = logging.getLogger(__name__)

# Common conversational greetings that can be fast-routed to direct_chat
SIMPLE_GREETINGS = {
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "thanks",
    "thank you",
    "bye",
    "goodbye",
    "how are you",
    "who are you",
}

ROUTER_SYSTEM_PROMPT = """You are an intent classification and search query rewriting assistant for a student study application.
You must analyze the student's message in the context of recent chat history and output ONLY valid JSON matching this exact structure:
{
  "route": "direct_chat" | "rag_query" | "quiz_mode",
  "rewritten_query": "..."
}

ROUTE DEFINITIONS:
1. "direct_chat":
   - Use for greetings, social pleasantries, thanks, casual conversation, or small talk.
   - Examples: "hello", "hi there", "thanks!", "who are you?", "bye".
   - For direct_chat, "rewritten_query" should be the student's original message.

2. "quiz_mode":
   - Use when the student explicitly asks for a quiz, test, diagnostic questions, MCQs, or practice exam.
   - Examples: "quiz me on chapter 2", "create a 5 question test", "give me some practice MCQs".
   - For quiz_mode, "rewritten_query" can be the topic or the original request.

3. "rag_query":
   - Use when the student is asking about concepts, explanations, facts, details, summaries, or references from their uploaded study material.
   - Examples: "What is database normalization?", "Explain B-Trees", "Can you elaborate on the second point?", "Why did that happen?".
   - For rag_query, "rewritten_query" MUST be a clear, standalone search query optimized for semantic document retrieval:
     * Resolve all pronouns and ambiguous references ("it", "they", "the previous concept", "that equation") using the conversation history.
     * Strip unnecessary conversational filler ("tell me about", "can you please explain").
     * Keep it concise and focused on core domain terms.
     * Do NOT invent new facts or answer the question.

Output ONLY valid JSON. Do not include markdown formatting or explanations outside the JSON object."""


def _get_router_client() -> Tuple[object, str]:
    """
    Obtain the Groq client and model name for query routing.

    Uses ROUTER_API_KEY if configured; otherwise falls back to RAG_API_KEY.
    Uses ROUTER_MODEL (default: openai/gpt-oss-120b).

    Raises:
        RuntimeError: If neither ROUTER_API_KEY nor RAG_API_KEY is configured.
    """
    api_key = settings.ROUTER_API_KEY or settings.RAG_API_KEY
    if not api_key:
        raise RuntimeError(
            "Neither ROUTER_API_KEY nor RAG_API_KEY is configured."
        )

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except ImportError as exc:
        raise RuntimeError(
            "The 'groq' package is required. Install it with: pip install groq"
        ) from exc

    model = settings.ROUTER_MODEL or "openai/gpt-oss-120b"
    return client, model


def _build_router_messages(query: str, history: List[Dict]) -> List[Dict]:
    """Build message list for router prompt with recent history."""
    messages = [{"role": "system", "content": ROUTER_SYSTEM_PROMPT}]

    # Include recent history (chronological) to allow pronoun/reference resolution
    if history:
        history_text_parts = []
        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                history_text_parts.append(f"{role.capitalize()}: {content}")

        if history_text_parts:
            context_block = (
                "Recent Conversation History:\n"
                + "\n".join(history_text_parts)
            )
            messages.append({"role": "user", "content": context_block})

    messages.append({
        "role": "user",
        "content": f"Student Message: {query}\n\nRespond with JSON:"
    })
    return messages


def route_and_rewrite_query(
    query: str,
    history: Optional[List[Dict]] = None,
) -> RouterOutput:
    """
    Route and optionally rewrite the user's message in a single structured LLM call.

    Args:
        query:   The raw student message.
        history: Recent chat messages in chronological order (role/content dicts).

    Returns:
        RouterOutput: Pydantic model with validated route and rewritten_query.

    Fallback:
        On any error or invalid response, safely falls back to:
        route="rag_query", rewritten_query=query
    """
    cleaned_query = query.strip()
    history = history or []

    # ── Fast path: Simple greetings route directly without LLM latency ────────
    normalized = re.sub(r"[^\w\s]", "", cleaned_query.lower()).strip()
    if normalized in SIMPLE_GREETINGS and not history:
        logger.info("Router: Fast-path direct_chat detected for '%s'", cleaned_query)
        return RouterOutput(route="direct_chat", rewritten_query=cleaned_query)

    # ── Structured LLM Router Call ───────────────────────────────────────────
    try:
        client, model = _get_router_client()
        messages = _build_router_messages(cleaned_query, history)

        logger.info(
            "Router: Calling model=%s for query='%s...' (history_len=%d)",
            model,
            cleaned_query[:50],
            len(history),
        )

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 1024,
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

        # Validate against Pydantic schema
        route = parsed.get("route", "rag_query")
        rewritten = parsed.get("rewritten_query", cleaned_query)
        if not rewritten or not isinstance(rewritten, str) or not rewritten.strip():
            rewritten = cleaned_query

        result = RouterOutput(route=route, rewritten_query=rewritten.strip())
        logger.info(
            "Router success: route='%s', rewritten='%s...'",
            result.route,
            result.rewritten_query[:60],
        )
        return result

    except Exception as exc:
        # Fallback requirement: On any failure, safely default to rag_query
        logger.warning(
            "Router failed or timed out: %s. Falling back to rag_query with original message.",
            exc,
        )
        return RouterOutput(route="rag_query", rewritten_query=cleaned_query)
