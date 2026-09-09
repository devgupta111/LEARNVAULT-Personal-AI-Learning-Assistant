"""
agents/crag_agent.py

CRAG (Corrective Retrieval-Augmented Generation) Agent — PLANNED FOR DAY 5.

This file is intentionally a stub on Day 4.

Day 5 will implement:
  - Triggered only when cross-encoder reranker score is below threshold.
  - Generates exactly ONE alternative search query via LLM.
  - Caller re-embeds and re-runs Qdrant + reranking exactly once.
  - If still weak → unified refusal. No loops.

Day 4 does NOT use CRAG. If retrieval is weak, Day 4 returns the refusal
message directly without any corrective retry.
"""
