"""
agents/query_router.py

Query Router & Rewriter Agent — PLANNED FOR DAY 5.

This file is intentionally a stub on Day 4.

Day 5 will implement:
  - One structured LLM call that classifies user intent and rewrites the query.
  - Routes: "direct_chat" | "rag_query" | "quiz_mode"
  - Fallback to raw user message on any failure.

Day 4 does NOT use a router. The chat pipeline embeds the raw user message
directly and runs the RAG pipeline without routing or rewriting.
"""
