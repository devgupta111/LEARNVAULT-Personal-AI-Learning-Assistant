"""
schemas/document.py

Pydantic request/response schemas for the documents API.
These are separate from the ORM model to keep API contracts explicit.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str


class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    subject: Optional[str]
    status: str
    page_count: Optional[int]


class DocumentDetail(BaseModel):
    document_id: str
    filename: str
    subject: Optional[str]
    status: str
    page_count: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
