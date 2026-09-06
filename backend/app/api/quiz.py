"""
quiz.py

Quiz generation and auto-grading endpoints.
Implemented in Phase 8.

Planned endpoints:
  POST /quiz/generate
  GET  /quiz/{quiz_id}
  POST /quiz/{quiz_id}/submit
  GET  /quiz/history
"""

from fastapi import APIRouter

router = APIRouter(prefix="/quiz", tags=["Quiz"])


@router.get("/status")
def quiz_status():
    return {"phase": 8, "message": "Quiz endpoints — implemented in Phase 8"}
