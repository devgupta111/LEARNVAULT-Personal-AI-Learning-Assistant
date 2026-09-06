"""
chat.py

RAG chat endpoints.
Implemented in Phase 6.

Planned endpoints:
  POST /chat
  GET  /sessions
  GET  /sessions/{session_id}/messages
"""

from fastapi import APIRouter

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.get("/status")
def chat_status():
    return {"phase": 6, "message": "Chat endpoints — implemented in Phase 6"}
