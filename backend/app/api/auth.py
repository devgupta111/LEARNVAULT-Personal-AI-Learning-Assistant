"""
auth.py

Authentication endpoints.
Implemented in Phase 2.

Planned endpoints:
  POST /auth/register
  POST /auth/login
  GET  /auth/me
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/status")
def auth_status():
    return {"phase": 2, "message": "Auth endpoints — implemented in Phase 2"}
