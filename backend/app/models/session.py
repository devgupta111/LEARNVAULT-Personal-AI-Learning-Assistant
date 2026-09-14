"""
models/session.py

SQLAlchemy ORM model for the sessions table.

A session ties a user to a specific document for a conversation.
One user can have multiple sessions per document.

Security:
    user_id is stored here so every session access can verify ownership.
    No query should return a session whose user_id doesn't match the
    authenticated user.
"""

import datetime
import uuid
from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func

from app.db.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Authenticated user who owns this session.
    # Derived from JWT on every request — never trusted from the browser.
    user_id = Column(String(36), nullable=False, index=True)

    # The document this session is scoped to.
    # Every chat message in this session queries only this document's vectors.
    document_id = Column(String(36), nullable=False)

    # Optional custom title for the session (renamed by user)
    title = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
