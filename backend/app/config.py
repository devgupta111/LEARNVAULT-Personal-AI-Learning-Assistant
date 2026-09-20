"""
config.py

Central configuration loaded from the .env file at the project root.
All settings are environment-variable driven — no secrets in source code.

Day 6 additions:
  GRADER_API_KEY  — Dedicated API key for Hallucination & Citation Grader.
  GRADER_MODEL    — Model for grader (dedicated credentials with RAG fallback).
  QUIZ_API_KEY    — Dedicated API key for Adaptive Quiz & Diagnostic Agent.
  QUIZ_MODEL      — Model for quiz generation.
"""

from typing import Optional
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Project root is three levels up from this file:
# backend/app/config.py  →  backend/app/  →  backend/  →  project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_learning_db"
    )
    UPLOAD_DIR: str = str(PROJECT_ROOT / "data" / "uploads")
    PROCESSED_DIR: str = str(PROJECT_ROOT / "data" / "processed")
    MAX_FILE_SIZE_MB: int = 20

    # Day 3 — Qdrant Vector Database
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION_NAME: str = "learning_assistant"
    QDRANT_BATCH_SIZE: int = 64

    # Day 4 — RAG LLM Generation (server-side only, never exposed to frontend)
    # RAG_API_KEY: Groq API key used for grounded generation.
    # RAG_MODEL:   Groq model for generation (e.g. openai/gpt-oss-120b).
    RAG_API_KEY: Optional[str] = None
    RAG_MODEL: str = "openai/gpt-oss-120b"

    # Day 4 — Cross-Encoder Reranker (local FlashRank, no API key)
    # Threshold below which retrieval is considered weak → refusal.
    # Treat as a tunable value, not a universal constant.
    RERANK_THRESHOLD: float = 0.35
    RERANK_TOP_K: int = 4       # Max unique parent contexts sent to LLM

    # Day 5 — Query Router & Rewriter Agent (dedicated credentials with RAG fallback)
    ROUTER_API_KEY: Optional[str] = None
    ROUTER_MODEL: str = "llama-3.1-8b-instant"

    # Day 5 — CRAG Agent (dedicated credentials with RAG fallback)
    CRAG_API_KEY: Optional[str] = None
    CRAG_MODEL: str = "llama-3.1-8b-instant"

    # Day 6 — Hallucination & Citation Grader (dedicated credentials with RAG fallback)
    GRADER_API_KEY: Optional[str] = None
    GRADER_MODEL: str = "llama-3.1-8b-instant"

    # Day 6 — Adaptive Quiz & Diagnostic Agent (dedicated credentials with RAG fallback)
    QUIZ_API_KEY: Optional[str] = None
    QUIZ_MODEL: str = "llama-3.1-8b-instant"

    # Day 7 — Google Identity Services Client ID
    GOOGLE_CLIENT_ID: str = "345444138884-bbigs9vt771fii89o3kf0ncs1snl01fu.apps.googleusercontent.com"

    # Production CORS Configuration — safe environment-based origins
    # Comma-separated list of allowed origins. Defaults to local dev servers.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    CORS_ORIGIN_REGEX: Optional[str] = r"https:\/\/.*\.vercel\.app"
    FRONTEND_URL: Optional[str] = None

    # Supabase Storage — Persistent PDF storage backend (Render ephemeral disk solution)
    # The bucket 'learnvault-documents' must remain PRIVATE.
    # SUPABASE_SECRET_KEY is strictly backend-only (never exposed to client/browser).
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SECRET_KEY: Optional[str] = None
    SUPABASE_BUCKET_NAME: str = "learnvault-documents"

    @field_validator("UPLOAD_DIR", "PROCESSED_DIR", mode="after")
    @classmethod
    def resolve_directory_paths(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            return str((PROJECT_ROOT / p).resolve())
        return str(p)

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
