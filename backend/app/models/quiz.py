"""
models/quiz.py

SQLAlchemy ORM model for the quizzes table.

A quiz is tied to a user and a document.
Questions are stored as a JSON-encoded list in the questions column.

Brain.md schema:
    id, user_id, document_id, title, questions, created_at

Security:
    user_id is stored so every quiz access can verify ownership.
    No query should return a quiz whose user_id doesn't match the
    authenticated user.
"""

import datetime
import uuid
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func

from app.db.base import Base


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Authenticated user who owns this quiz.
    # Derived from JWT on every request — never trusted from the browser.
    user_id = Column(String(36), nullable=False, index=True)

    # The document this quiz was generated from.
    document_id = Column(String(36), nullable=False, index=True)

    # Primary topic of the quiz (e.g., a detected weak topic or user-supplied hint).
    topic = Column(String(255), nullable=False, default="General")

    # JSON-encoded list of QuizQuestion dicts.
    # Validated by Pydantic before insertion, parsed by callers on retrieval.
    questions = Column(Text, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
