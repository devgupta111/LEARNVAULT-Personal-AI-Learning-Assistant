"""
config.py

Central configuration loaded from the .env file at the project root.
All settings are environment-variable driven — no secrets in source code.
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


    @field_validator("UPLOAD_DIR", mode="after")
    @classmethod
    def resolve_upload_dir(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            return str((PROJECT_ROOT / p).resolve())
        return str(p)

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
