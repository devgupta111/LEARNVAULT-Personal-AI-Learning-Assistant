"""
schemas/chat_schemas.py

Pydantic request and response models for the Day-4 chat API.

Day 4 uses normal JSON request/response — no SSE, no streaming.
"""

from typing import List, Optional
from pydantic import BaseModel, field_validator


# ─── Request schemas ──────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """Body for POST /sessions — creates a new chat session."""
    document_id: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("document_id must not be empty")
        return v


class ChatRequest(BaseModel):
    """Body for POST /chat."""
    session_id: str
    document_id: str
    message: str

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("session_id must not be empty")
        return v

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("document_id must not be empty")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        return v


# ─── Response schemas ─────────────────────────────────────────────────────────

class CitationItem(BaseModel):
    """A single citation referencing a source chunk used in the answer."""
    source_id: str          # e.g. "Source 1"
    document_id: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    parent_chunk_id: Optional[str] = None
    subject: Optional[str] = None


class ChatResponse(BaseModel):
    """Response from POST /chat."""
    session_id: str
    answer: str
    citations: List[CitationItem] = []


class SessionResponse(BaseModel):
    """Represents a single chat session."""
    session_id: str
    document_id: str
    created_at: str


class MessageResponse(BaseModel):
    """Represents a single message in a session."""
    message_id: str
    session_id: str
    sender: str         # "user" or "assistant"
    content: str
    citations: List[CitationItem] = []
    created_at: str
