"""
models/message.py

SQLAlchemy ORM model for the messages table.

Stores every user message and assistant response within a session.
Citations are stored as a JSON string in the citations column.

Sender values:
    "user"      — the student's question
    "assistant" — the RAG-generated answer (or refusal)

Security:
    Messages are accessed only through their parent session, which is
    already ownership-checked before any message query runs.
"""

import datetime
import uuid
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func

from app.db.base import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    session_id = Column(String(36), nullable=False, index=True)

    # "user" or "assistant"
    sender = Column(String(20), nullable=False)

    # The text of the message or answer (or refusal string).
    content = Column(Text, nullable=False)

    # JSON-encoded list of citation dicts.
    # Stored as text for SQLite compatibility; parsed by callers.
    # Empty string / null means no citations (user messages, refusals).
    citations = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
